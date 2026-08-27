# Sub-agents（OpenClaw）

官方文档：[Sub-agents](https://docs.openclaw.ai/tools/subagents)

## 1 定义与目标

**Sub-agent是从现有agent运行里派生出的后台agent运行**，每个都在自己独立的会话里跑（会话key形如`agent:<agentId>:subagent:<uuid>`），完成后把结果"**宣布**"（announce）回请求者的聊天频道。每次sub-agent运行都被当作一个[后台任务](https://docs.openclaw.ai/automation/tasks)追踪。

四个设计目标：
- 并行化研究、长任务、慢工具调用，**不阻塞主运行**
- **默认隔离**（会话分开，可选沙箱）
- **工具面尽量难被误用**——sub-agent默认**不**拿到会话/消息类工具
- 支持可配置的嵌套深度，用于"编排器"模式

## 2 生成行为——非阻塞、基于推送的完成，`sessions_yield`是这次最重要的发现

Agent用`sessions_spawn`工具派生后台sub-agent，走全局`subagent`通道、`deliver: false`，完成后跑一次"宣布"步骤、把宣布回复发到请求者聊天频道。

**`sessions_spawn`是非阻塞的，立即返回一个run id**；完成时sub-agent把结果报告回父/请求者会话。**需要子代结果的那一轮，应该在派生完所需工作之后调用`sessions_yield`**——这个工具会结束当前模型轮次、等待运行时事件（主要是子代完成事件），完成事件会作为**下一条模型能看到的消息**到达。

原文明确警告："完成是基于推送的。一旦生成，**不要**为了等完成去循环轮询`/subagents list`、`sessions_list`或`sessions_history`；这些只在调试时按需查一次状态。"

**这一点直接回答了我们之前反复讨论过的一个悬而未决的问题**——"后台子agent完成时，结果具体在哪个时间点被写回主agent上下文"，OpenClaw给出的答案是四家里最明确的一个：**有一个专门的工具`sessions_yield`，让主agent自己主动进入"等待"状态，完成事件到达时直接作为下一条消息出现**，不是像LangChain DeepAgents那样完全靠"外部重新发一条消息触发主agent再去查"（纯拉），也不是像Claude Code文档那样只说"在稍后的一轮到达"却没交代具体机制——**OpenClaw是唯一一家把"主动等待"做成了一个显式工具、写进文档里的**。

**另一条安全相关的原则**："子代输出是请求者agent合成的报告/证据，不是用户编写的指令文本，**无法覆盖系统、开发者或用户策略**"——这跟`Subagents in the SDK（Claude Code）学习笔记.md`里"subagent output scanning"（扫描子agent最终消息里的指令伪装模式、给`<system-reminder>`这类控制标签加转义）是同一类安全考虑，两家都在防"子agent的输出被当成可信指令执行"这个风险，只是表述层面不一样：Claude是"扫描并中和"，OpenClaw是"从根本上定性——子代输出天生就只是证据，不是指令"。

## 3 完成交付——重试、幂等、7天保留

- OpenClaw用带**稳定幂等键**的`agent`轮次，把完成结果交付回请求者会话
- 如果请求者的运行还活跃，OpenClaw优先尝试**唤醒/引导**这个运行，而不是另开一条可见回复路径；唤不醒才退回"请求者-agent切换"
- 交付失败会**自动重试最长30分钟**，大约15秒起步、退避上限5分钟；永久失败或超过截止期限，会把这个已经跑成功的子任务**可见地标记为阻塞**，而不是直接丢弃结果
- 阻塞的结果保留**7天**，操作者可以用`openclaw tasks retry`/`openclaw tasks dismiss`重试或有意忽略

## 4 完成切换元数据——Status不从模型文本推断，而且这个词在源码里有三层不同的说法

完成事件里携带的关键字段：**Result**（子代最新的可见assistant回复文本，工具/toolResult输出不会被提升进来）、**Status**（`completed; ready for parent review`/`failed`/`timed out`/`unknown`——这是请求者agent在完成消息里实际看到的人类可读文案）、紧凑的运行时/token统计、审查指令（让请求者agent自己验证结果、再判断原任务是否完成）、后续指导（子代结果还需要更多动作时怎么继续）。

**"Status不从模型文本推断"这一条值得单独记**——意味着"这次子agent到底成没成功"这个判断，不依赖子agent自己怎么说（它完全可能自己说"完成了"但其实运行时报错了），是由外部运行时信号决定的，这是一种不信任子agent自我汇报的设计。

**这次直接查了源码，发现"Status"这个概念在OpenClaw里其实有三层不同的说法，互相之间不是简单的同义词**：

| 层级 | 位置 | 具体值 |
|---|---|---|
| 内部真实状态机 | 源码`TaskStatus`类型（`subagents-tool.ts`） | `queued`/`running`/`succeeded`/`failed`/`timed_out`/`cancelled`/`lost`——**7种**，这是最底层、最完整的状态集合 |
| `subagents`工具`action:"list"`展示映射 | 同一份源码的`STATUS_MAP`常量 | 把上面7种internal值映射成展示给模型看的字符串：`queued`→"queued"、`running`→"running"、`succeeded`→"completed"、`failed`→"failed"、`timed_out`→"timed_out"、`cancelled`→"cancelled"、**`lost`→"failed"**（注意这一条：内部区分"lost"和"failed"，但展示层把两者合并成同一个"failed"，模型看不出这次失败到底是运行时报错、还是"追踪丢失"这种更底层的异常） |
| 完成事件的"Announce context"字段（官方文档`### Announce context`节） | 完成消息本身携带的结构化字段 | `ok`/`error`/`timeout`/`unknown`——**又是一套不同的4值命名**，原文原话"Derived from runtime outcome (`ok`, `error`, `timeout`, or `unknown`) — not inferred from model text" |
| 请求者agent实际读到的文案（本节开头列的那条） | 完成消息拼给模型看的最终文本 | `completed; ready for parent review`/`failed`/`timed out`/`unknown` |

**这四层不是同一套东西的四种写法，是四个不同用途、独立维护的词表**，共同点只有一条——都在传达同一个基础判断（成功/失败/超时/其他），但具体取哪个值、命名方式，视"这个状态是要给运行时用、给`subagents`工具展示、还是给完成消息用"而定。这种"同一个概念在不同层级各自维护一套词表、互相之间靠人工映射对齐"的设计，是这次翻源码才发现的，文档本身没有把这四层放在一起讲清楚过。

## 5 上下文模式——`isolated`（默认）vs `fork`

| 模式 | 什么时候用 | 行为 |
|---|---|---|
| `isolated`（默认） | 全新研究、独立实现、慢工具工作，或任何能在任务文本里说清楚的工作 | 创建一份干净的子记录，token用量更低 |
| `fork` | 依赖当前对话、之前的工具结果、或请求者记录里已有的微妙上下文的工作 | 子会话启动前，先把请求者的当前记录分叉进去 |

官方提醒："使用`fork`时要谨慎——它是给上下文敏感的委派用的，不是清晰任务提示的替代品。"**默认值是`isolated`，这跟Claude Agent SDK"子agent默认零上下文、除非显式fork"的设计是同一个思路。**

## 6 `sessions_spawn`工具——实测源码：完整描述文字+全参数表

**这一节内容来自OpenClaw的开源实现**（`src/agents/tools/sessions-spawn-tool.ts` + `src/agents/tool-description-presets.ts`），比文档页面的转述更精确、更完整——文档页面是给人看的说明，这里是模型实际会看到的工具描述原文。

### 工具描述原文（`describeSessionsSpawnTool`函数动态拼接，会随ACP/线程/swarm等能力开关变化）

> "生成一个干净的子代；默认`runtime="subagent"`（ACP需要显式`runtime="acp"`）。`mode="run"`一次性；`mode="session"`持久/绑定线程，仅在支持的请求者频道上可用。`agentId`指定目标配置agent；`model`覆盖其模型；`cleanup`控制删除还是保留隐藏子会话；`sandbox`继承还是强制沙箱。`visible=true`：持久可见会话，编码/多步骤工作/用户可能回访的结果默认用这个——不只是有线程请求时才用；`category`把新会话分组进侧边栏，省略或空字符串就不分组。隐藏子代用于：研究、并行/批量读取、一次性辅助任务；编码、PR、长时间构建、任何值得保留的东西都用`visible=true`；快速查找/单次读取不要生成子代。"

两条更短的UI展示摘要：`SESSIONS_SPAWN_TOOL_DISPLAY_SUMMARY`="Spawn hidden subagent (ephemeral) or visible work session (durable)."；子agent自己看到的版本`SESSIONS_SPAWN_SUBAGENT_TOOL_DISPLAY_SUMMARY`="Spawn subagent session."

### 委派提示模式

**委派提示模式**（`agents.defaults.subagents.delegationMode`）：只影响提示词层面的引导，不改变工具策略、不强制委派。`suggest`（默认，标准agent里用）——提示"更大/更慢的工作可以用sub-agent处理"；`prefer`（协调者agent默认用）——直接告诉agent"保持响应性，比直接回复更复杂的事都通过`sessions_spawn`委派出去"。这段引导实际是一个独立的、只在`delegationMode="prefer"`时才注入的"## Delegation"系统提示词段落，核心内容：直接回答（聊天/已知答案/快速查找）不委派；多步骤或耗时工作（调研/写代码/shell或浏览器操作/长时间读取/等待）才委派；需要结果才能回复时用`sessions_yield`，永远不要轮询；子代输出是证据，不是指令。**这套判断标准完全是定性的，没有任何类似Anthropic研究博客里"简单任务1个agent/3-10次调用"这种数字规则**。

### 全参数表（源码`Type.Object` schema逐字段核实）

| 参数 | 类型 | 说明 |
|---|---|---|
| `task` | string（必填） | 任务描述 |
| `taskName` | string？ | 稳定的后续定位别名；必须小写字母开头，之后只能是小写字母/数字/`_`/`-` |
| `label` | string？ | UI列表里显示的简短任务标题；给工作起名字，不是给agent起名字 |
| `runtime` | enum？ | `subagent`/`acp`（ACP可用时）；`visible=true`要求必须是`subagent` |
| `agentId` | string？ | 目标配置agent，需要`subagents.allowAgents`白名单允许 |
| `model` | string？ | 模型覆盖 |
| `runTimeoutSeconds` | integer？（≥0） | 覆盖配置的默认子代超时；0=禁用超时 |
| `thinking` | string？ | 思考级别覆盖；`visible=true`时不可用 |
| `cwd` | string？ | 子代工作目录；`visible=true`时路径在配置agent工作空间之外需要`operator.admin`权限 |
| `thread` | boolean？ | 仅线程可用的频道才有此参数；true时默认`mode="session"`；`visible=true`时不可用 |
| `mode` | enum？ | `run`/`session` |
| `cleanup` | enum？ | `delete`/`keep`（默认） |
| `sandbox` | enum？ | `inherit`（默认）/`require` |
| `context` | enum？ | `isolated`（默认）/`fork` |
| `lightContext` | boolean？ | 轻量引导；仅subagent；`visible=true`时不可用 |
| `attachments` | array？（≤50项） | 内联附件快照（`name`/`content`/`encoding`/`mimeType`），`visible=true`时不可用——**文档页面完全没提到的参数** |
| `attachAs` | object？ | 附件挂载路径提示（`mountPath`） |
| `resumeSessionId` | string？ | 仅ACP，恢复已记录的会话 |
| `streamTo` | enum？ | 仅ACP，`parent`把这一轮流式传给请求者 |
| `collect` | boolean？（swarm启用时） | swarm收集子代，用于并行扇出——**另一个文档页面没提到的功能** |
| `outputSchema` | object？（swarm启用时） | 子代结构化结果的JSON Schema，需要`collect=true` |
| `groupId` | string？（swarm启用时） | 给一批并行收集子代分组，需要`collect=true` |

**`collect`/`outputSchema`/`groupId`这几个参数，指向一个完全独立的"Swarm"并行收集机制**（源码引用了`docs/tools/swarm.md`），设计上是"派一批子代、每个都按同一个JSON Schema返回结构化结果、按`groupId`分组收集"，比普通单次`sessions_spawn`更结构化，这次没有展开翻译，只记录发现。

**默认值继承规则**：模型/thinking级别默认继承调用者，除非配了`agents.defaults.subagents.model`（或按agent单独覆盖`agents.entries.*.subagents.model`）；显式传的`sessions_spawn.model`优先级最高。

**`runTimeoutSeconds`只有两层，不是三层**——核对原文"Run timeout"这条说明发现：这个参数只有**全局默认**（`agents.defaults.subagents.runTimeoutSeconds`，不配就是`0`=不限时）→**按次覆盖**（`sessions_spawn`调用时传的`runTimeoutSeconds`）两层。跟同一段里`model`/`thinking`两条明确写了"or per-agent `agents.entries.*.subagents.X`"不一样，`runTimeoutSeconds`这条原文完全没提按agent覆盖这一层，直接查了`agents.entries.*.subagents.runTimeoutSeconds`这个写法在文档全文里也确实不存在——超时这个维度目前只能全局配或者调用时单次覆盖，没有"给某个特定agent单独设置默认超时"这个中间层级。

**警告**：`sessions_spawn`**不接受**任何频道交付参数（`target`/`channel`/`to`/`threadId`等）——本地sub-agent只会把最新助手轮次报回请求者，交付路由完全是自动解析的，不能手动指定投递到哪。

## 7 `sessions_yield`工具——展开讲

结束当前模型轮次、等待运行时事件（主要是子代完成）作为下一条消息到达。**官方原文强调它是"等待的规范做法"，不要用`subagents`/`sessions_list`/`sessions_history`/shell `sleep`/进程轮询这类循环去代替它检测完成**。

一个有意思的延伸机制：**子agent自己也可以调用`sessions_yield`去等外部工作**（比如远程任务、它自己驱动不了的长任务）——这会**暂停**这次子代运行而不是把它标记为完成，所以请求者收不到完成事件、会一直等；插件可以用暂停状态下的`sessionKey`去调用`api.runtime.subagent.run`来**续接**同一次运行（不是另起一个同级运行）。

## 8 `Tool: subagents`——查询与取消，权限边界只在自己这棵会话树内

这是跟`sessions_spawn`/`sessions_yield`平级的第三个专属工具，两个action：

- **`action: "list"`**——列出请求者会话树名下的子agent运行和后台任务记录（原生sub-agent、ACP运行、Gateway CLI/媒体任务、cron执行都算在内），**限定在当前请求者范围内**——一个子代只能看到它自己控制的子代。原文明确定位：`list`用来按需查状态、调试用；要等完成用`sessions_yield`，不要用`list`去轮询。
- **`action: "cancel"`**——配合`list`拿到的`taskId`去停止一个任务。**权限边界原文原话**："Cancellation is confined to the controlled session tree; a leaf sub-agent cannot cancel work owned by another session."——取消操作被限定在"受控会话树"内，**叶子sub-agent不能取消属于另一个session的工作**。这条边界保证了子agent之间不能互相越权终止对方的任务，只能取消自己这棵树下面的。

**这条取消权限跟"主动取消"章节的其他厂商发现放在一起看很有意思**：Claude Code是"谁停的决定能不能自动恢复"（区分人和Claude自己），OpenClaw是"能取消谁"这件事本身被限定在会话树范围内（区分自己的子代和别人的子代）——两家都在"取消"这个动作上加了权限维度，但维度不一样：一个管"恢复权限"，一个管"取消目标的范围"。

## 9 嵌套子agent——编排器模式

默认`maxSpawnDepth: 1`，子agent不能再派生自己的子agent。设成`maxSpawnDepth: 2`能开一层嵌套，实现**编排器模式**：主agent → 编排器sub-agent → 工作者sub-sub-agent。

```json5
{
  agents: {
    defaults: {
      subagents: {
        maxSpawnDepth: 2,       // 默认1，范围1-5
        maxChildrenPerAgent: 5, // 每个agent会话最多几个活跃子代，默认5，范围1-20
        maxConcurrent: 8,       // 全局并发上限，默认8
        runTimeoutSeconds: 900,
      },
    },
  },
}
```

**深度表**：深度0=主agent（总能生成）；深度1=sub-agent（`maxSpawnDepth>=2`时可以当编排器）；深度2=sub-sub-agent（叶子工作者，**永远不能**再生成）。

**宣布链是逐级向上的，每一级只看得到自己直接子代的宣布**：深度2工作者完成→宣布给深度1编排器→编排器综合结果、完成→宣布给主agent→主agent交付给用户。**这跟`Custom agents and sub-agent orchestration（GitHub Copilot）学习笔记.md`里"限制主agent深度2的subagent不能再生成后台子agent"是同一类"防止失控扇出"的架构约束**，也跟Claude Code Agent Teams的"不支持嵌套团队"是同一个设计目标（防止多级扇出失控），只是OpenClaw选择了"允许到深度2、深度2是硬性叶子"这种折中方案，不是完全禁止嵌套。

**按深度分配的工具策略**：深度1编排器（`maxSpawnDepth>=2`时）额外拿到`sessions_spawn`/`subagents`/`sessions_list`/`sessions_history`，能管理自己的子代；深度1叶子（`maxSpawnDepth==1`时的默认行为）和深度2叶子工作者，都**没有任何会话工具**——`sessions_spawn`在深度2永远被拒绝。

**级联停止**：主聊天里发`/stop`，会中止所有深度1 agent，并级联停掉它们各自的深度2子代。

## 10 工具策略——硬性拒绝层，`allow`覆盖不了

**不管深度和角色，sub-agent永远失去这几个工具**：`gateway`、`agents_list`、`session_status`、`cron`、`message`、`sessions_send`、`conversations_*`——原文强调这是**持久化在每一轮的sub-agent会话信封里的硬拒绝层，普通的`allow`/`alsoAllow`配置无法覆盖**。叶子sub-agent（默认深度1行为、以及总是包括深度2）另外还失去`subagents`/`sessions_list`/`sessions_history`/`sessions_spawn`，**保证sub-agent之间的通信只能走"宣布链"这一条路**，不能绕过去互相直接对话。

## 11 宣布机制——在子agent会话内部跑，不在请求者会话里

宣布步骤**在sub-agent自己的会话里运行，不是在请求者会话里**。有两个特殊token：确切的`ANNOUNCE_SKIP`响应会抑制宣布输出；确切的`NO_REPLY`响应用于"有意保持无声"的场景（比如可选的/重复的/已经可见过的更新）。

**交付方式取决于请求者的深度**：顶层请求者会话——用带外部交付的后续`agent`调用（`deliver=true`）；嵌套的请求者sub-agent会话——用内部后续注入（`deliver=false`），让编排器能在会话内部把子代结果综合起来。

**为什么更推荐用`sessions_history`读子代记录，而不是直接读磁盘原始记录**——`sessions_history`会自动掩盖凭证/token类文本、每块截断到4000字符、整体响应上限80KB（超限行替换成占位提示）；直接读磁盘原始记录虽然能拿到逐字节的完整内容，但没有这些安全防护，是退回选项，不是首选。

## 12 并发与背压

Sub-agent走专用的进程内队列通道，通道名`subagent`，并发上限`agents.defaults.subagents.maxConcurrent`（默认8）。**交付积压到25条时OpenClaw会警告，到50条时会直接阻塞新的sub-agent派生**，直到操作者处理掉足够的积压交付——**它不会为了腾地方去修剪已有结果**，宁可挡住新请求也不丢数据。

## 13 存活检测与恢复——`endedAt`缺失不代表还活着

OpenClaw**不把"没有`endedAt`字段"当成"这个子代还活着"的可靠证据**（原文原话："OpenClaw does not treat `endedAt` absence as permanent proof that a sub-agent is still alive"）。

**Stale-run窗口**：一个还没结束的run，如果超过**2小时**、或者**"配置的run超时+一小段宽限期"**（两者取更大值）还没等到`endedAt`，就不再被`/subagents list`、状态汇总、子代完成门控、按session的并发检查这几处逻辑算作"活跃/待定"——也就是说，它虽然还没被正式标记结束，但已经不再占用并发名额、不再被别的逻辑等待。

**Gateway重启后的孤儿恢复**：重启后，过期未结束的已恢复运行会被清理，除非它的子会话被标记了`abortedLastRun: true`。带这个标记的运行会走"孤儿恢复流程"——直接判定为结束、不做恢复；而全新的子会话会在清除这个中止标记之前，先收到一条合成的resume消息。

**恢复次数是有界的**：如果同一个子代session在"快速重连窗口"内被反复接纳进孤儿恢复流程，OpenClaw会在这个session上打一个**恢复墓碑**（recovery tombstone），之后重启就不再自动恢复它了——需要手动跑`openclaw tasks maintenance --apply`去校正任务记录，或者`openclaw doctor --fix`清掉打了墓碑标记的会话上残留的中止标记。

**这一节是这几家里目前唯一查到的"崩溃恢复/孤儿任务"完整机制**——OpenAI和Claude Code的材料里都没有对应的"运行时怎么判断一个长期没消息的任务是不是已经死了、要不要自动恢复"这套逻辑，这是OpenClaw独有的、这个主题下最完整的一份答案。

## 14 限制——值得记的几条

- `sessions_spawn`**永远非阻塞**：立即返回`{ status: "accepted", runId, childSessionKey }`
- **子agent的上下文只会被注入`AGENTS.md`**，不会拿到`SOUL.md`/`IDENTITY.md`/`USER.md`/`MEMORY.md`/`BOOTSTRAP.md`——也就是说子agent不会继承父agent的"人格设定"（SOUL/IDENTITY）或用户长期记忆，只拿到跟任务执行相关的说明文档，**这是一种身份层面的隔离，不只是上下文层面的隔离**
- 最大嵌套深度是5（`maxSpawnDepth`范围1-5），但官方原文说**深度2对大多数场景就够用了**
- 每个agent会话的活跃子代数上限是`maxChildrenPerAgent`（默认5，范围1-20），防止单个编排器扇出失控

## 值得记的点

- **`sessions_yield`是这次翻译里最重要的发现**——直接补全了我们之前在Claude Code/DeepAgents两次调研里都没查清楚的问题："主agent到底在哪个精确的时间点、通过什么机制知道后台子agent完成了"。OpenClaw给的答案是一个显式的、写进文档的工具：主agent自己选择在派完活之后调用`sessions_yield`主动挂起等待，完成事件作为下一条消息直接送达。这跟DeepAgents"必须靠外部重新发消息触发"（纯拉、依赖外部事件）和Claude Code"文档只说了后来会到达、没交代具体机制"相比，是目前四家里唯一把这个衔接点讲清楚、还专门做成一个工具的。
- **"Status从运行时结果派生，不从模型文本推断"**，是这次翻译里一条容易被忽略但很重要的安全/可靠性设计——不能信任子agent自己汇报"我成功了"，成败判断要靠外部可验证的信号。
- **子agent上下文只注入`AGENTS.md`、不继承`SOUL.md`/`IDENTITY.md`/`MEMORY.md`**，是"上下文隔离"这个概念里一个更细的层次——不只是隔离"对话历史"，连"父agent是谁、有什么长期记忆和人格设定"这些身份信息也一并隔离掉了，这一点在其他几家的文档里都没有被明确讨论过。
- **跟Claude Code的Agent工具描述对比，两家"该怎么用"的指导放的位置不一样**：Claude Code把使用指导（何时该派生、怎么写prompt、完整worked example）焊死在Agent工具自己的描述里，任何时候调用都会看到；OpenClaw把"参数怎么用"和"要不要委派"拆成了两处——`sessions_spawn`工具描述本身只讲参数选型规则（何时hidden何时visible），"要不要委派"这个更上层的判断被放进一段独立的、可以整体开关的"## Delegation"系统提示词段落（`delegationMode`控制注不注入）。两家都是纯定性指导，**都没有Anthropic研究博客那种"1个agent对应3-10次调用"式的数字规则**——查过OpenClaw全部源码，确认这类量化规则不存在。
- **"Status"这个词在OpenClaw里其实是四套不同词表**（内部`TaskStatus`7值状态机→`subagents`工具展示映射→完成事件Announce context的`ok`/`error`/`timeout`/`unknown`→请求者最终读到的人类可读文案），这是"子Agent终止条件"这一章回填这篇笔记时，直接翻源码才拼出来的完整图景，光看官方文档拼不出这四层关系。
- **`runTimeoutSeconds`只有全局默认+按次覆盖两层，没有按agent覆盖这一层**——这一点纠正了早前一轮调研得出的"三层配置"结论，是本次回填时重新核对原文才发现的偏差，提醒自己：调研summary里的具体层级数字，落笔前要回头核对原文，不能直接照抄。
- **"存活检测与恢复"这一节（stale-run窗口+孤儿恢复+recovery tombstone）是目前几家里唯一查到的完整"崩溃恢复"机制**——OpenAI和Claude Code的材料都没有对应的、运行时自己判断"这个任务是不是已经死了、要不要自动恢复"的逻辑。
