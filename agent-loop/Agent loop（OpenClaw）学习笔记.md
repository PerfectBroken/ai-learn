# Agent loop（OpenClaw）

来源：[OpenClaw Docs - Agent loop](https://docs.openclaw.ai/concepts/agent-loop)（开源项目官方文档）

> 摘要（原文`summary`字段）："Agent loop的生命周期、事件流，以及wait语义"
> 适用场景（原文`read_when`字段）：你需要完整走查一遍agent loop或生命周期事件；你要改动session排队机制、写入方声明（writer claims）、或transcript写屏障（write fencing）

**Agent loop是一次串行化的、按session为单位的运行过程**，负责把一条消息变成实际动作和一条回复：接收消息、组装上下文、模型推理、执行工具、流式输出、持久化。

## 入口点

- Gateway RPC：`agent`和`agent.wait`
- CLI：`openclaw agent`

## 运行流程

1. `agent`这个RPC校验参数、解析session（按`sessionKey`/`sessionId`）、持久化session元数据，然后**立刻**返回`{ runId, acceptedAt }`。
2. `agentCommand`负责跑这一回合：解析模型+思考/详细度/追踪相关的默认配置，加载skills快照，调用`runEmbeddedAgent`；如果内嵌循环还没自己发出生命周期结束/报错事件，这里会兜底补发一个。
3. `runEmbeddedAgent`：通过per-session队列和全局队列把运行**串行化**，解析模型和认证profile，构建OpenClaw session，订阅运行时事件，流式输出assistant/工具的增量内容，强制执行运行超时（超时就中止），最后返回结果payload和用量元数据。对Codex app-server这类回合，如果它在还没到达终止事件前就停止产生app-server进度更新，这一步也会把它中止。
4. `subscribeEmbeddedAgentSession`把运行时事件桥接到`agent`这个事件流上：工具事件对应`stream: "tool"`，assistant的增量内容对应`stream: "assistant"`，生命周期事件对应`stream: "lifecycle"`（`phase`取值为`"start" | "end" | "error"`）。
5. `agent.wait`（内部函数`waitForAgentRun`）会等待某个`runId`的**生命周期结束/报错事件**，然后返回`{ status: ok|error|timeout, startedAt, endedAt, error? }`。

## 排队与并发

**运行按session key（会话通道）做串行化**，还可以额外经过一个全局通道，防止工具/session之间产生竞态。消息渠道会选择一种排队模式（打断续接/追加/合并/中断，即steer/followup/collect/interrupt）来喂给这套通道系统，具体见[Command Queue](/concepts/queue)。

**在开始流式输出之前，一次被接纳的运行会先记录下它自己持久化的`activeWriterRunId`声明**。之后每一次transcript的追加或重写操作，都要带上`expectedWriterRunId`这个参数，同步提交事务时会校验这个值是否仍然跟当前生效的声明一致。**因此一次已经被取代（superseded）的运行，没办法把过期的transcript数据提交进去**。SQLite的写入队列负责给同一个agent的写操作排好顺序，同时Gateway的状态目录锁能防止另一个Gateway进程、或另一个`openclaw agent --local`进程，同时占用同一个状态目录。

## Session与工作区准备

- 解析并创建工作区；如果是沙箱化运行，可能会重定向到一个沙箱工作区根目录。
- 加载skills（或者从快照里复用），注入进环境变量和prompt里。
- 解析bootstrap/上下文文件，注入进系统提示词里。
- **在开始流式输出之前，session的transcript目标和写入方声明就已经准备好了**。后续的重写、压缩（compaction）、截断操作，用的都是同一套事务内的写入方声明屏障机制。

## Prompt组装

系统提示词由OpenClaw自己的基础prompt、skills prompt、bootstrap上下文、以及本次运行的自定义覆盖内容拼装而成。会强制执行针对具体模型的长度限制，并为压缩（compaction）预留token。模型实际会看到什么，具体见[System prompt](/concepts/system-prompt)。

## Hooks（钩子）

OpenClaw有**两套**Hook系统：

- **内部hooks（Gateway hooks）**：由事件驱动的脚本，响应命令和生命周期事件。
- **插件hooks（Plugin hooks）**：agent/工具生命周期内部、以及gateway pipeline里的扩展点。

### 内部hooks（Gateway hooks）

- **`agent:bootstrap`**：在构建bootstrap文件、系统提示词最终确定之前运行。可以用它来增加或移除bootstrap上下文文件。
- **命令hooks**：`/new`、`/reset`、`/stop`等命令事件（详见Hooks文档）。

具体配置方式和例子见[Hooks](/automation/hooks)。

### 插件hooks

这些hook运行在agent loop内部、或者gateway pipeline里：

| Hook | 运行时机 |
| --- | --- |
| `before_model_resolve` | Session开始前（此时还没有`messages`），用来确定性地在解析之前覆盖provider/model |
| `before_prompt_build` | Session加载之后（此时已有`messages`），用来注入`prependContext`、`systemPrompt`、`prependSystemContext`或`appendSystemContext`；在支持"回合范围内工具面收窄"的runtime上，还能用`toolsAllow`收窄这次提交的工具集——`toolsAllow`留空表示这次不提交任何可选工具；不设置这个字段则保持宿主原本解析出来的工具面不变；不支持这个能力的runtime会直接拒绝限制性的值，而不是悄悄忽略 |
| `before_agent_reply` | 内联动作执行完之后、真正调用LLM之前。可以让插件"接管"这一回合，直接返回一条合成的回复，或者完全静默掉这一回合 |
| `agent_end` | 完成之后触发，带上最终的消息列表和这次运行的元数据 |
| `before_compaction` / `after_compaction` | 观察或标注压缩（compaction）周期 |
| `before_tool_call` / `after_tool_call` | 拦截工具的参数/结果 |
| `before_install` | 在运营方的安装策略跑完之后、针对已暂存的skill/plugin安装素材、且插件hooks已经在当前进程加载完毕时触发 |
| `tool_result_persist` | 在工具结果被写入OpenClaw自己管理的session transcript**之前**，同步地对结果做一次转换 |
| `message_received` / `message_sending` / `message_sent` | 入站和出站消息相关的hook |
| `session_start` / `session_end` | Session生命周期的起止节点 |
| `gateway_start` / `gateway_stop` | Gateway自身的生命周期事件 |

针对出站消息/工具的"拦截判定"规则：

- `before_tool_call`：返回`{ block: true }`是**终止性**的，会阻止后面优先级更低的handler继续执行；返回`{ block: false }`是**空操作**，不会清除之前已经生效的block。
- `before_install`：跟上面一样，也是终止性/空操作这套语义。运营方需要覆盖CLI安装和更新路径的allow/warn/block决策，应该用`security.installPolicy`来配置，不要用`before_install`。
- `message_sending`：返回`{ cancel: true }`是**终止性**的，会阻止后面优先级更低的handler继续执行；返回`{ cancel: false }`是**空操作**，不会清除之前已经生效的cancel。

Hook API和注册方式的细节见[Plugin hooks](/plugins/hooks)。

不同的harness可以自己适配这些hook。Codex app-server这个harness，把OpenClaw插件hooks当作已文档化的镜像接口的兼容层来维护；Codex原生的hooks是另一套独立的、更底层的Codex自己的机制。

### 模块架构关系图

上面几节讲的排队并发、Session准备、Prompt组装、六类插件hook，各自挂在整体架构的哪个位置，画一张图串起来看更直观（**画之前先用`gh search code`核实了几处不确定的挂接顺序**，跟原始猜测的结构不一样，图里已经按源码修正）：

- `before_model_resolve`这个hook，一开始以为挂在`agentCommand`之前，查了`embedded-agent-runner/run/setup.ts`的源码注释（"Run before_model_resolve hooks early so plugins can override the provider/model before resolveModel()"）才确认它其实挂在`runEmbeddedAgent`内部、解析model之前。
- Session/工作区准备、Prompt组装，一开始误画成`agentCommand`和`runEmbeddedAgent`核心循环之间两级独立台阶，实际上根据Run sequence第3步的措辞和源码目录结构，这两块都是`runEmbeddedAgent`内部"构建session"这个子步骤的一部分，全部包在同一次函数调用里。

![OpenClaw Agent模块架构关系图：agentCommand只负责起止两端；中间全部装在runEmbeddedAgent一个容器里，内部子模块从上到下是排队+写入方声明、解析model+auth、构建session、Prompt组装、核心工具使用小循环、Reply整形；左列并发控制层（session lane/global lane/SQLite写入队列/状态目录锁/writer-claim）用点线门控进入这个容器；右列上下文装配层（workspace/skills快照/bootstrap文件）汇入构建session子步骤；右侧绿色hooks区块精确标出六类插件hook各自挂在容器内哪个子模块上；底部持久化层是Session Transcript，writer-claim核对每次写入；外围虚线红框标出六种叠加的超时体系覆盖范围](openclaw-architecture.svg)

（触发流程图——从Gateway RPC入口到返回payload的完整时序——放在[Turn Loop设计](TurnLoop.md)里，跟`create_agent`的流程图并排对照着看。）

## 流式输出

- Assistant的增量内容以`assistant`事件的形式从agent runtime里流出来。
- 按block（内容块）流式输出时，可以在`text_end`或`message_end`这两个时机吐出部分回复。
- 思考过程（Reasoning）的流式输出，可以走一条独立的流，也可以直接拦截阻塞正常回复。

具体的分块方式和block回复行为见[Streaming](/concepts/streaming)。

## 工具执行

- 工具的开始/更新/结束事件都发在`tool`这条流上。
- 工具结果在被记录日志/发出之前，会先针对大小和图片payload做一次脱敏/精简处理。
- 消息类工具的发送会被专门跟踪，防止assistant对同一条消息重复确认。

## 回复整形

最终的payload是这样拼出来的：assistant的文本内容（加上可选的思考过程）+ 内联的工具摘要（仅在详细模式且被允许的情况下）+ 模型报错时的assistant错误文本。

- 完全静默的特殊token `NO_REPLY`会从最终输出的payload里被过滤掉。
- 消息类工具产生的重复内容，会从最终payload列表里被剔除。
- 如果最后没有任何可渲染的payload、但有工具报了错，会兜底发出一条工具错误回复——除非某个消息类工具已经主动发过一条用户可见的回复了。

## 压缩与重试

自动压缩（Auto-compaction）会发出`compaction`这条流上的事件，并且可能触发一次重试。重试时，内存里的缓冲区和工具摘要都会重置，避免输出重复内容。详见[Compaction](/concepts/compaction)。

## 事件流

- `lifecycle`：由`subscribeEmbeddedAgentSession`发出（`agentCommand`会做兜底补发）。
- `assistant`：agent runtime流式输出的增量内容。
- `tool`：agent runtime流式输出的工具事件。

Gateway会把生命周期事件和工具的起始/终止事件，投影进一份有边界限制、只含元数据的[审计台账（audit ledger）](/cli/audit)。这份投影只记录来源和结果码，**不会**把prompt、消息内容、工具参数、工具结果或原始报错信息，从transcript/runtime这条路径里复制出来。

## 聊天渠道处理

Assistant的增量内容会被缓冲进聊天的`delta`消息里。**生命周期结束/报错事件**触发时，会发出一条聊天的`final`消息。

## 超时机制

| 超时项 | 默认值 | 备注 |
| --- | --- | --- |
| `agent.wait` | 30秒 | 仅仅是"等待"性质的超时，`timeoutMs`参数可以覆盖；不会真正停止底层正在跑的运行 |
| Agent runtime（`agents.defaults.timeoutSeconds`） | 172800秒（48小时） | 由`runEmbeddedAgent`的中止计时器强制执行；设成`0`表示不限制运行预算，但模型流的存活监控（liveness watchdog）依然生效 |
| CLI后端"无输出"监控 | 按每次全新/恢复的CLI运行单独计算 | 跟agent runtime本身是独立的，归注册的backend插件管理；CLI内部的后台任务和父子进程共用生命周期，不会活得比整体agent超时更久 |
| Cron隔离的agent回合 | 由cron自己管理 | 调度器在执行开始时启动自己的计时器，到配置的截止时间就中止运行，然后先做一次有边界的清理，最后才记录超时——防止一个过期的子session把整条通道卡死 |
| 模型空闲超时 | 云端120秒；自托管300秒 | 如果模型请求在这个空闲窗口内没有任何响应分片返回，OpenClaw就会中止这次请求；`models.providers.<id>.timeoutSeconds`可以为速度慢的本地/自托管provider延长这个空闲监控窗口，但仍然受限于`agents.defaults.timeoutSeconds`或本次运行专属超时里更小的那个有限值——因为这两者管的是整次agent运行；不限制的运行预算依然保留provider级别的空闲监控。Cron触发的云端模型运行，如果没有显式配置模型/agent超时，用的是同一个默认值；如果配置了显式的cron运行超时，云端模型流卡顿的上限会封顶在60秒，好让配置好的模型兜底/降级方案还能在外层cron截止时间之前跑起来。Cron触发、且跑在真正本地端点（loopback/私网baseUrl）上的运行，保留本地空闲豁免；跑在网络baseUrl上的自托管provider，会有隐式的300秒监控。如果配置了显式的cron运行超时，本地/自托管的卡顿上限就封顶在这个超时值。速度慢的本地provider建议设置`models.providers.<id>.timeoutSeconds` |
| Provider的HTTP请求超时 | `models.providers.<id>.timeoutSeconds` | 覆盖连接、header、body、SDK请求超时、有防护的fetch中止处理，以及该provider的模型流空闲监控。建议先给速度慢的本地/自托管provider（比如Ollama）单独调这个值，而不是一上来就调高整个agent runtime的超时；如果模型请求本身就需要跑更久，记得把agent/runtime超时也调到至少一样高 |

### 卡住的Session诊断

诊断功能开启后，有一个内置的两分钟阈值，用来分类那些长时间处于`processing`状态、但没有观察到任何回复/工具/状态/内容块/ACP进度的session：

- 正在活跃运行的内嵌运行、模型调用、工具调用，会被上报为`session.long_running`。有归属的、静默的模型调用会一直保持`session.long_running`状态直到达到中止阈值，这样速度慢或者不支持流式的provider就不会过早被误判成"卡住了"。
- 没有最近进度的活跃工作，会被上报为`session.stalled`。有归属的模型调用在达到或超过中止阈值时，会切换成`session.stalled`；没有归属的、过期的模型/工具活动，不会被隐藏成"长时间运行"。
- `session.stuck`专门留给可恢复的、过期的session记账场景，包括那些空闲排队、但带有过期的、没有归属的模型/工具活动的session。

**中止阈值至少是5分钟，并且是警告阈值的3倍**。过期session的记账，在恢复检查通过之后会立刻释放对应的session通道；卡住的内嵌运行只有到达中止阈值之后才会被"中止排空"，这样排队中的其他工作还能继续，不会因为一个只是"慢"的运行被误伤中断。恢复过程会发出结构化的"已请求/已完成"结果；诊断状态只有在同一个processing世代（generation）仍然是当前世代时，才会被标记为idle；如果session状态一直没变化，重复出现的`session.stuck`诊断会自动退避降频。

## 哪些情况会提前结束

- Agent超时（中止）
- AbortSignal（取消）
- Gateway断开连接，或RPC超时
- `agent.wait`超时（仅仅是"等待"超时，不会真正停止agent本身）

## 深挖：Session Transcript的存储结构（非原文翻译，用`gh search code`/`gh api`核实OpenClaw源码后补充）

上面"排队与并发""Session与工作区准备"两节提到的"transcript目标和写入方声明"，原文只是一笔带过。这里往下挖了一层：**每条记录到底长什么样、一共有几种、最后怎么落进SQLite**。

### 1. 每条记录的通用信封：`SessionEntryBase`

源码：`src/agents/sessions/session-manager-types.ts`

```typescript
export interface SessionEntryBase {
  type: string;
  id: string;
  parentId: string | null;   // 指向上一条记录，串成一棵树，不是简单的数组
  timestamp: string;
  appendMode?: "side";       // 走"侧路"游标而不是主线的可见叶子节点
}
```

**`parentId`是最关键的一点**——每条记录都指向自己的父节点，整个session的历史结构上是一棵**树**，不是一个平铺数组，为分支/侧路（`appendMode: "side"`）预留了结构空间。

每种具体类型通过`extends`在这个基础信封之上叠加专属字段，并把`type`从宽泛的`string`收窄成一个字面量——这是TypeScript的**判别联合（discriminated union）**写法：所有类型合并成一个`SessionEntry`联合类型，读取代码靠检查`entry.type === "message"`这一个字段，就能让TypeScript自动推断出这条记录带着哪些专属字段，不需要每次都做完整的类型断言。

### 2. 实际记录的10种类型

源码里`grep "type: \""`出来的完整列表：

| 类型 | 专属字段 | 作用 |
| --- | --- | --- |
| `message` | `message: AgentMessage` | 真正的一条对话消息 |
| `thinking_level_change` | `thinkingLevel` | 思考等级变更 |
| `model_change` | `provider`, `modelId` | 切换了模型 |
| `compaction` | `summary`, `firstKeptEntryId`, `tokensBefore`, `details?`, `fromHook?` | 压缩事件本身 |
| `reset` | `reason`（`"new"｜"reset"｜"idle"｜"daily"｜"cron-stale"`） | 会话被重置，附带原因 |
| `session_info` | `name?` | session元信息 |
| `custom_message` | `customType`, `content`, `details?`, `display` | 插件生成、参与模型上下文的自定义消息 |
| `custom` / `label` / `branch_summary` | （未逐一深挖字段） | 自定义事件/标签/分支摘要 |

**`message`类型存的内容，直接复用了`ToolCalling.md`学过的Anthropic Messages API消息格式**——`message`字段的类型是：

```typescript
export type AgentMessage = Message | CustomAgentMessages[keyof CustomAgentMessages];
```

这里的`Message`基础类型（`role: "assistant"`/`role: "user"`、`content`数组）就是Anthropic Messages API的消息对象本身，**OpenClaw没有自己发明一套消息schema，直接把厂商API的消息对象原样存进transcript**。

### 3. SQLite落地格式：JSON列 + 二级索引表，不是把10种类型拆成10套列

源码：`src/state/openclaw-agent-schema.sql`

真正落盘每一条记录的核心表`transcript_events`：

```sql
CREATE TABLE IF NOT EXISTS transcript_events (
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, seq),
  FOREIGN KEY (session_id) REFERENCES "session_windows"(session_id) ON DELETE CASCADE
) STRICT;
```

只有4个字段，**`event_json`这一列直接把整条`SessionEntry`（不管是哪种类型）序列化成JSON字符串塞进去**——SQL表结构对"10种类型各自专属字段"完全无感，`seq`负责排序，`session_id`+`seq`做联合主键。

这样存的问题是没法直接用SQL按具体字段查询，所以配了第二张表专门做索引：

```sql
CREATE TABLE IF NOT EXISTS transcript_event_identities (
  session_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT,
  parent_id TEXT,
  message_idempotency_key TEXT,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (session_id, event_id),
  FOREIGN KEY (session_id, seq) REFERENCES transcript_events(session_id, seq) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ... ON transcript_event_identities(session_id, message_idempotency_key)
  WHERE message_idempotency_key IS NOT NULL;
CREATE INDEX ... ON transcript_event_identities(session_id, parent_id) WHERE parent_id IS NOT NULL;
```

**这张表只把`SessionEntryBase`那几个"每种类型都有"的通用字段单独拎出来做成真正可查询的列**——`event_id`对应`id`、`event_type`对应`type`、`parent_id`对应`parentId`。至于每种类型各自专属的字段（`message`、`thinkingLevel`、`provider`/`modelId`……），永远待在`event_json`这个blob里，SQL层面查不到，只能整行取出来在应用代码里`JSON.parse`。

**这套模式的通用叫法是"JSON列 + 二级索引表"**，是事件溯源（event sourcing）系统应对"事件类型会不断增加、形状还不统一"这类场景的常见做法——好处是加一种新的entry类型完全不需要改表结构、不需要数据库迁移；代价是绝大部分字段没法被SQL直接检索，只有提前想好"这几个字段可能需要查询"才会被拎出来单独建索引列。

**一个顺带的发现**：`message_idempotency_key`这一列配了允许`NULL`的`UNIQUE`索引——这正是`ToolDesign.md`讨论过的"幂等键"模式的真实实现，靠数据库唯一约束防止同一条消息被重复写入，不是靠代码逻辑自己判断。

## 相关链接

- [Tools](/tools) - 可用的agent工具
- [Hooks](/automation/hooks) - 由agent生命周期事件驱动的脚本
- [Compaction](/concepts/compaction) - 长对话是怎么被摘要压缩的
- [Exec Approvals](/tools/exec-approvals) - shell命令的审批关卡
- [Thinking](/tools/thinking) - 思考/推理等级的配置
