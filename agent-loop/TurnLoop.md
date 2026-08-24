# Turn Loop 设计

Layer 3第一个话题，也是Agent架构里最核心的一块。跟Layer 2不同，这里没有一篇单一的权威规范可以当骨架，资料分散在几家厂商的产品文档、一篇理念层文章、和开源框架的实现文档里，先把这几篇定下来，逐篇精读。

## 目录

- [1 Agent Loop是什么](#1-agent-loop是什么)
- [2 Agent Loop的开源实现](#2-agent-loop的开源实现)
  - [2.1 两张流程图对照：OpenClaw vs. `create_agent`](#21-两张流程图对照openclaw-vs-create_agent)
  - [2.2 Loop设计对比：跳转机制、循环单元、暂停恢复、终止条件](#22-loop设计对比跳转机制循环单元暂停恢复终止条件)
  - [2.3 Hook位置逐一对照：哪些是两边都有、哪些是各自独有](#23-hook位置逐一对照哪些是两边都有哪些是各自独有)
- [3 Agent State](#3-agent-state)
  - [3.1 调研结论：四家都查过，没有一家把它当独立架构支柱](#31-调研结论四家都查过没有一家把它当独立架构支柱)
  - [3.2 OpenAI的`context`对象：本地、不发给LLM的业务状态](#32-openai的context对象本地不发给llm的业务状态)
- [4 Agent Loop and Agent Team的设计](#4-agent-loop-and-agent-team的设计)
  - [4.1 OpenAI Agents SDK：Handoff——三分支循环里"驱动身份中途切换"的机制](#41-openai-agents-sdkhandoff三分支循环里驱动身份中途切换的机制)
  - [4.2 "子agent当工具"内部还有一个分歧：结果是同步塞回`tool_result`，还是异步等通知？](#42-子agent当工具内部还有一个分歧结果是同步塞回tool_result还是异步等通知)
- [5 参考资料](#5-参考资料)

## 1 Agent Loop是什么

**结论先行：Agent Loop的核心定义——LLM在一个循环里，依据环境反馈（工具结果、代码运行输出）自主决定下一步做什么，直到判定任务完成或触碰终止条件。** 定义出自Anthropic《Building Effective AI Agents》，完整笔记见[Building Effective AI Agents学习笔记](Building%20Effective%20AI%20Agents学习笔记.md)。

原文（笔记译文）区分了"Workflow"和"Agent"两种架构，Loop只属于后者：

> 工作流是通过预设代码路径编排大语言模型与工具的系统。
> 与之相对，智能体是由大语言模型自主动态调度自身流程与工具调用、自主掌控任务完成方式的系统。

再落到执行细节上：

> 智能体能够处理复杂任务，但实现方式往往并不复杂。本质上大多只是大语言模型依据环境反馈循环调用工具。

**三个关键词划出了Loop的边界**：
- ①**自主**——路径不是预先硬编码的，由LLM自己决定下一步调用哪个工具；
- ②**环境反馈**——每一步都要拿到"真实信息"（工具结果、代码输出）才能判断进度，不是LLM自说自话；
- ③**终止条件**——任务完成会自动结束，但通常还要设最大迭代次数这类兜底条件防止失控。

下面第2、3节看到的所有具体实现（OpenClaw的七阶段循环、`create_agent`的`model`↔`tools`条件边循环、OpenAI的三分支循环），本质上都是在给这三个关键词找一套具体的工程落地方案。

## 2 Agent Loop的开源实现

这一节把OpenClaw和`create_agent`（LangGraph）两个开源实现的Loop设计放在一起看，拆成三个小节：先看两张流程图建立整体形状，再看loop本身的设计取舍，最后逐个对照hook挂载点。

### 2.1 两张流程图对照：OpenClaw vs. `create_agent`

**① OpenClaw的触发流程图**：

![OpenClaw Agent Loop触发流程图：从Gateway RPC或CLI入口开始，agent RPC立刻异步返回runId，agentCommand解析默认值并调用runEmbeddedAgent；runEmbeddedAgent是一个大容器，内部依次完成排队与写入方声明、解析model+auth profile（before_model_resolve hook挂在这里，已按源码核实）、构建session（workspace/skills/bootstrap）、Prompt组装（before_prompt_build/before_agent_reply）、核心工具使用小循环（模型推理-工具执行-压缩重试循环，四组hook挂在循环内部子动作上）、Reply整形，最后返回payload；runEmbeddedAgent返回后agentCommand收尾触发agent_end，桥接成lifecycle事件，三路分叉给agent.wait调用方、审计台账、聊天渠道；左侧标出运行超时覆盖整个runEmbeddedAgent容器，以及四种提前结束的异常路径](openclaw-loop-trigger-flow.svg)

**② `create_agent`的节点/边流程图**：

![create_agent真实节点/边流程图：以一个实现了before_agent/before_model/after_model/after_agent全部四个钩子的middleware M为例。节点从上到下是START、M.before_agent（entry_node）、M.before_model（loop_entry_node）、model、tools、M.after_model（loop_exit_node）、M.after_agent（exit_node）、END，其中四个M.xxx节点画成虚线框标出是middleware贡献的可选节点。边：START到M.before_agent固定边；M.before_agent到M.before_model、M.before_model到model都是条件边（默认走这条，也能跳到exit_node提前结束整个agent）；model到M.after_model是唯一一条纯固定边；M.after_model三选一条件边——有tool_calls去tools，没有去exit_node，HITL注入工具消息或需要重新生成结构化输出则跳回loop_entry_node；tools二选一条件边——正常回loop_entry_node，工具标了return_direct或有结构化输出工具则直接去exit_node；M.after_agent条件边——默认到END，也能跳回loop_entry_node重新进入循环。图下方额外说明了多个middleware时的串联规则：before_agent/before_model按注册顺序正序串联，after_model/after_agent按注册顺序反序串联，以及一个middleware都不注册时整张图退化成model与tools的两节点循环](create-agent-node-edge-flow.svg)

### 2.2 Loop设计对比：跳转机制、循环单元、暂停恢复、终止条件

> 这张表早先版本写成了两个"产品"的全面对比（并发调度、持久化schema、复用性…），跑题了——那些是agent这个"产品/框架"的能力，不是"loop"这个东西本身的设计。收窄回**loop**：一次迭代经过哪些阶段、循环内部怎么跳转/分支、能不能被暂停、靠什么信号结束。

| 维度 | OpenClaw | `create_agent`（LangGraph） | 证据来源 |
|---|---|---|---|
| **循环内部的跳转/控制流机制** | Hook主要返回值是`{block:true/false}`或`{cancel:true/false}`——**"终止性 vs 空操作"的二元判定**，只能阻止/放行"接下来默认要发生的动作"，不能指定改去某个具体的其他步骤；但`before_tool_call`还有第三种返回形态`requireApproval`（见下一行），不是纯粹的二元判定 | `can_jump_to`**声明式跳转**：中间件能明确指定跳到`loop_entry_node`或`exit_node`这样具体的目标节点，本质是图上真正的条件边 | OpenClaw笔记"针对出站消息/工具的拦截判定规则"一节（`before_tool_call`/`message_sending`的block/cancel语义）；`docs/plugins/plugin-permission-requests.md`（`requireApproval`）；`factory.py`的`can_jump_to`/`_add_middleware_edge`机制（上一章反复验证） |
| **循环的最小单元包含哪些阶段** | "模型推理→工具执行→压缩重试"是loop结构**自带**的三段式子循环——压缩（compaction）是loop明确列出的一个阶段，有专属的`before_compaction`/`after_compaction`挂载点 | loop结构层面只有"`model`→（有`tool_calls`就）`tools`→回`loop_entry_node`"这一个圈；**压缩不是loop的专属阶段**，要不要压缩、什么时候压缩完全下放给挂在`before_model`上的某个middleware（`SummarizationMiddleware`）自己判断，图本身不知道"压缩"这个概念存在 | `openclaw-loop-trigger-flow.svg`"核心工具使用小循环（模型推理-工具执行-压缩重试循环）"；`SummarizationMiddleware.before_model`源码（上一章读过） |
| **循环能否被外部暂停/恢复** | **证据确凿，但有限定范围**：`before_tool_call`钩子可以返回`{requireApproval:{...}}`，OpenClaw会挂起这次工具调用、广播一个待处理审批（`plugin:` ID），等外部人类给出`allow-once`/`allow-always`/`deny`（或超时/取消）后再继续或终止执行，走`plugin.approval.*`这套Gateway RPC；host级shell命令另有一套更窄的专属版本（`exec.approval.requested`/`exec.approval.resolve`）。**但没有通用的"任意钩子都能触发暂停"的核心原语**——官方issue`#19072`（"First-class Tool Execution Approvals: Pause, Interrupt, and Resume"）明确提议过这个通用能力，2026-03-30被关闭、`state_reason: "not_planned"`，源码里也搜不到该提案定义的`paused_for_approval`/`resume_token`类型 | **证据确凿**：有形式化的graph级`interrupt()`原语，`HumanInTheLoopMiddleware.after_model`直接调用`interrupt(hitl_request)`真正暂停整张图执行，等外部输入后恢复；且不绑定在某个特定钩子上，任何middleware理论上都能调用 | `docs/plugins/plugin-permission-requests.md`（"Decision behavior"表格）；`docs/tools/exec-approvals.md`（"Approval flow"节）；GitHub issue `openclaw/openclaw#19072`（`state: closed`，`state_reason: not_planned`）；`human_in_the_loop.py`第450行`interrupt(hitl_request)` |
| **循环的终止条件** | 这次查到的是**四种外部强制中止信号**：Agent超时、AbortSignal取消、Gateway断开连接/RPC超时、`agent.wait`超时（仅等待超时，不影响agent本身）——但没有查到"loop自己判断没活干了、正常收尾"具体靠什么信号触发，**这一点跟create_agent不对等，不能直接类比** | loop结构层面的正常终止条件很明确：最新一条`AIMessage`**没有`tool_calls`**就走向`exit_node`；此外中间件能主动用`jump_to:"end"`提前终止（比如超过调用次数上限） | `Agent loop（OpenClaw）学习笔记.md`"哪些情况会提前结束"一节（仅四种外部中止路径）；create_agent侧：`_make_tools_to_model_edge`（`factory.py`）+`ModelCallLimitMiddleware`的`jump_to`语义（上一章读过） |

### 2.3 Hook位置逐一对照：哪些是两边都有、哪些是各自独有

按**触发时机**（而不是按名字）对齐，能看出比"六个vs十几个，谁更多"更有用的结构性差异：

| OpenClaw hook | 触发时机 | create_agent对应 | 判定 |
|---|---|---|---|
| `before_model_resolve` + `before_prompt_build` + `before_agent_reply` | 整个run开始时，只跑一次（循环开始前） | `before_agent`（entry_node，整个agent只跑一次的入口） | **大致对应**，但OpenClaw拆成了3个更细分的hook（分别管provider/model选择、prompt注入、接管本回合），create_agent这边只有1个入口钩子，粒度上OpenClaw更细 |
| `agent_end` | 整个run结束时，只跑一次，带最终消息列表+元数据 | `after_agent`（exit_node，整个agent只跑一次的出口） | **对应**，时机、语义都对得上 |
| `before_tool_call` / `after_tool_call` | 循环内，每次工具调用前后（循环内四组hook之二） | `wrap_tool_call`（包裹式，围绕每次工具执行，可重试/短路/改写参数结果） | **对应**，但编程模型不同：OpenClaw是before/after两个独立回调，create_agent是一个包一层的函数；`before_tool_call`额外支持`requireApproval`挂起等待人类审批（见2.2"暂停/恢复"一行），这一点比单纯的block/cancel更接近create_agent的`interrupt()` |
| `before_compaction` / `after_compaction` | 循环内，每次压缩周期前后（循环内四组hook之二） | 无专属挂载点 | **仅OpenClaw独有**——create_agent没有"压缩"这个专属生命周期阶段，摘要压缩靠一个普通的`before_model`级middleware（`SummarizationMiddleware`）自己在每轮循环里判断"要不要压缩" |
| `tool_result_persist` | 工具结果写入自己的session transcript**之前** | 无 | **仅OpenClaw独有**——create_agent没有自建transcript持久化系统，这层交给可插拔的`checkpointer`/`store` |
| `message_received` / `message_sending` / `message_sent` | Gateway层，跟外部用户/聊天渠道的消息收发 | 无 | **仅OpenClaw独有**——create_agent是纯函数式的图，不管"跟外部用户怎么通信"这一层 |
| `session_start` / `session_end` | Session（可能横跨多次agent运行）生命周期起止 | 无 | **仅OpenClaw独有**——create_agent没有内建"session"概念，多轮对话的延续性由调用方用`checkpointer`+`thread_id`自己维护，不是图内部的一个生命周期阶段 |
| `gateway_start` / `gateway_stop` | 整个Gateway进程的生命周期 | 无 | **仅OpenClaw独有**——create_agent是一次函数调用，不是常驻进程 |
| `before_install` | skill/plugin安装策略相关 | 无 | **仅OpenClaw独有**——create_agent的middleware是普通Python对象、直接传参注册，没有"安装"这个概念 |
| 无对应 | — | `before_model` / `after_model`（loop_entry_node/loop_exit_node，**每一轮循环、每次真正调用模型之前/之后都触发**） | **仅create_agent独有**，见下方详细说明 |
| 无对应 | — | `wrap_model_call`（包裹式，围绕单次模型调用本身，可重试/短路真正的API请求） | **仅create_agent独有** |

**其中最关键的一条是`before_model`/`after_model`这一行**：OpenClaw虽然也有"模型推理"这个循环内子步骤，但我们验证过循环内挂的"四组hook"精确覆盖的是压缩（2个）和工具调用（2个），**没有一个hook是专门挂在"每一轮的模型推理"这个子步骤上的**——OpenClaw组装prompt、覆盖model选择的那几个hook（`before_model_resolve`/`before_prompt_build`/`before_agent_reply`）只在整个run刚开始时跑一次，不会随着循环的每一轮重新触发。也就是说：**如果你想在多轮工具调用循环的第3轮、第5轮分别对发给模型的请求做点手脚（比如动态裁剪消息、临时换一次system prompt），create_agent原生支持（`before_model`每轮都跑一次），OpenClaw原生不支持（对应的hook只在最开始跑一次，之后的每一轮模型调用它管不到）**。这是两边hook设计里唯一一处不是"粒度粗细"之分、而是"有没有这个挂载点"的真实能力差异。

## 3 Agent State

### 背景：Execution State vs Business State（这次调研借用的分析框架）

来源：[12-Factor Agents](https://github.com/humanlayer/12-factor-agents)（HumanLayer，Dex Horthy，风格上借鉴了经典的"12-factor app"方法论）Factor 5。**这份文档的分量核实过，不是泛泛的"认可度较高"**：GitHub `humanlayer/12-factor-agents`仓库**25,424 star、1,925 fork**（截至2026-08-23）；在Hacker News上的讨论帖**475 points**，进过首页；被AI Engineer大会官方账号称为"the fan favorite manifesto"；LlamaIndex专门做了一个页面（`12factors.llamaindex.ai`）复述/采纳这套原则。

原文给出的两个定义：

- **Execution state**："current step, next step, waiting status, retry counts, etc."——**当前跑到哪一步、下一步是什么、在不在等待、重试了几次**，这是"流程控制"层面的信息。
- **Business state**："What's happened in the agent workflow so far (e.g. list of OpenAI messages, list of tool calls and results, etc.)"——**消息列表、工具调用和结果**，这是"发生过什么事"这个层面的信息。

作者的核心论点是**反对把两者强行拆成两套独立的管理系统**：

> In reality, you can engineer your application so that you can infer all execution state from the context window. In many cases, execution state (current step, waiting status, etc.) is just metadata about what has happened so far.

翻译：现实中你完全可以把应用设计成——所有的execution state都能从context window（也就是那份消息/事件历史）里推断出来。很多情况下，"当前第几步""是否在等待"这类execution state，本质上只是"迄今为止发生了什么"这份历史的一层元数据而已，不需要单独维护。

**这个概念区分本身很有用，可以拿来当"审视一个具体agent实现"的检查清单，下面两节调研用的就是这套词汇**：

- LangGraph的`State`——默认把两者混在一起放（`messages`是business state，`jump_to`这类字段更接近execution state），符合12-Factor的建议。
- OpenClaw的SQLite——`transcript_events`表存的是business state（消息/事件），`subagent`/`background task`的运行状态表则是execution state，**这边是分开存的**，跟12-Factor"建议不要分开"的立场正好相反——是不是"过度设计"，取决于你怎么看待"debug时要不要能从一份日志里看全"这个诉求（12-Factor七条好处里第3条"调试：完整历史在一处可见"，正好点出了OpenClaw这种拆开存法的潜在代价）。

### 3.1 调研结论：按"背景"那套词汇重新核对五家的实际设计

**没有一家会直接写"execution state"/"business state"这两个词**，但每家为了让agent能正常执行、能中断恢复，实际设计里总会有类似的东西——下面按这套词汇去对照实际机制，而不是去搜字面匹配。

| 来源 | Business state管理机制 | Execution state管理机制 | 是否拆成两套独立系统 | 其他要点 |
|---|---|---|---|---|
| **LangGraph**（`create_agent`） | `AgentState`里的`messages`字段（`Annotated[list[AnyMessage], add_messages]`），靠`add_messages`归约器合并，整个`checkpointer`统一持久化 | 分两层看：**①你自己能碰到的一层**——比如`ModelCallLimitMiddleware`往`AgentState`里加的`thread_model_call_count`字段（记着调用了几次模型）、`jump_to`字段（记着要不要跳去别的节点），这些都是你自己定义、能读能改的普通state字段，存进`Checkpoint`的`channel_values`里（跟`messages`是平级的两个channel）。**②你碰不到的一层——这次专门去查了`Checkpoint`的实际源码**（`libs/checkpoint/langgraph/checkpoint/base/__init__.py`），`Checkpoint`这个`TypedDict`除了装你数据的`channel_values`，还有几个跟它平级、但你完全碰不到的字段：`versions_seen`（原文docstring："Map from node ID to map from channel name to version seen...**Used to determine which nodes to execute next**."）、`pending_writes`（`CheckpointTuple`里的字段，还没应用的写入）、`channel_versions`/`updated_channels`——这些就是"现在该跑哪个node了"这类调度信息，跟你的`AgentState`数据物理上是分开的字段，只是共享同一次checkpoint写入 | 分层看，两个答案：**①那层不拆**——你自己加的计数器、路由字段，跟`messages`都存在`channel_values`这同一个字段里，同一次存盘。**②那层结构上是分开的字段（`versions_seen`等），但不是"12-Factor意义上的拆分"**——因为它存的不是"消息列表/工具调用结果"这类业务数据，是图引擎自己的调度簿记，从设计上就不该跟用户的`AgentState`混在一起 | 举例说明②那层的作用：`interrupt()`触发人在回路暂停后，LangGraph之所以能正确恢复到暂停的地方，靠的就是`versions_seen`这类字段（docstring原话就是"determine which nodes to execute next"），不是靠你在①那层自己加一个"is_waiting"字段去手动追踪 |
| **Claude Agent SDK** | Session JSONL文件——"every prompt, tool call, tool result, response"全部当一份线性事件流写盘 | **对外暴露/文档化的部分：没有独立持久化的execution state对象**——一次`query()`内部要跑几轮，文档原文只说"the agent already takes as many turns as it needs...they don't end the call"，没有任何字段/接口把轮次计数、重试次数这类信息暴露给开发者或落盘。**但Claude Code CLI这个二进制本身是闭源的，没有源码访问权限**——它进程内部实际有没有维护execution state（哪怕只是内存里的临时循环变量），这次没查、也查不了，不能断言"完全没有"，只能说"没有对外暴露/持久化的" | 同样只能就"对外暴露的部分"下结论——**没有对外暴露的execution state系统**，`resume`一个session走的是"重新读完整transcript让模型看一遍"这条路径，不涉及读取某个"当前第几轮"的字段；内部实现层面是否另有一套，未知 | 后台运行的子agent/`run_in_background`这类跨轮次的"待完成任务"状态具体怎么持久化追踪，这次没有深挖，留白，不编 |
| **OpenAI Agents SDK** | 四种"conversation state"策略之一管理（`to_input_list`/`session`/`conversation_id`/`previous_response_id`） | **有明确独立的类`RunState`**，官方定义原文："Serializable snapshot of an agent run, including context, usage, and interruptions"，专门做"durable pause/resume boundary for human-in-the-loop flows"。关键字段：`_current_turn`（当前第几轮）、`_current_step`（当前可恢复步骤/终态）、`_max_turns`（轮次上限）、`_pending_input`（下次恢复前暂存的输入） | **`RunState`本身是统一的**——同一个对象里既有execution-state字段（`_current_turn`/`_current_step`/`_max_turns`）也有business-state字段（`_model_responses`/`_session_items`/`_generated_items`），符合12-Factor"别拆开"的建议；但`context`（`RunContextWrapper`，本地业务数据）是**完全独立的第三个概念**，不在`RunState`序列化范围内 | `RunState`是专门为HITL"暂停-恢复"设计的完整快照，平时普通对话流程走的是"conversation state"那四种策略，不会主动接触到`RunState` |
| **OpenClaw** | `transcript_events`表（SQLite，JSON blob每条一行）+ `transcript_event_identities`二级索引 | **有独立的表**——`restart-recovery.md`原文列了好几类：subagent运行registry、background task记录、delivery queue、cron store，都在"shared SQLite state database"里，但是跟transcript分开的表 | **明确拆开了**，跟12-Factor"不建议拆开"的立场相反（背景那节已经论证过） | 主session"当前这一轮是不是跑到一半被打断了"也有专门标记位（"Interrupted main-session turn \| Per-agent SQLite session row and transcript"），不是靠重放transcript反推的 |
| **DeepAgents** | `messages`字段，用`DeltaChannel`归约器优化了checkpoint增长（O(N²)→O(N)） | `TodoListMiddleware`加的`todos`字段——每个任务带`pending`/`in_progress`/`completed`状态，本质就是"当前执行到计划的第几步"这类execution state，只是用"待办列表"的形式表达出来 | **不拆开**——`todos`字段和`messages`字段是同一个`DeepAgentState`（继承`AgentState`）里的两个字段，同一次checkpoint写入，跟LangGraph本身的设计哲学一致 | `todos`长得像业务数据（一份任务清单），但记录的其实是"agent自己给自己规划的执行进度"，是"execution state借用business-state风格字段来存"的一个有趣例子 |
| **GitHub Copilot SDK** | 官方文档`session-persistence`给出的实际目录结构（原文示例）：`checkpoints/`目录下一份份JSON快照文件（`001.json`/`002.json`…），存"Full message thread"全量对话历史；`Tool call results`也会被缓存 | Copilot CLI闭源，只能查文档披露的部分：文档明确列了一个跟`checkpoints/`**平级、独立的文件`plan.md`**，说明是"Agent planning state"——这是目前查到的、Copilot唯一带execution-state色彩的持久化产物，性质更接近DeepAgents的`todos`字段（一份规划产出），不是OpenAI `RunState`那种`current_turn`/`max_turns`/重试次数式的正式字段清单——文档没有细说`plan.md`内部具体存了什么字段，没查到更细的schema | **物理上分开存**——`checkpoints/`和`plan.md`是同一个session目录下两个不同的文件，不是同一份对话记录的一部分；但轻量得多，是"一个文件 vs 一个文件"，不是OpenClaw那种"整套独立数据库表"级别的拆分 | 文档还提到"In-memory tool state"明确**不**持久化，工具被要求设计成无状态（"Tools should be stateless"）；这一行的所有结论都只基于官方文档披露信息，CLI二进制闭源，没有源码可查——跟Claude Agent SDK那一行同样的限定 |

**结论**：六源查完，不是简单的"一家违反、其他都遵守"，是三个阵营，外加一个"轻量拆分"的中间态。①**统一存**（符合12-Factor建议）：LangGraph用户层、OpenAI的`RunState`、DeepAgents。②**明确拆开存**（违反建议）：OpenClaw——整套独立的数据库表级别的拆分。③**对外没有暴露execution state这个概念**：Claude Agent SDK——但仅限于"公开文档/对外接口"这个范围内成立，CLI二进制闭源，内部实现未知，不断言"完全不维护"。④**轻量级的拆分**：GitHub Copilot SDK——`checkpoints/`和`plan.md`是两个独立文件，物理上分开，但规模和"整套独立表"完全不是一个量级，且同样受限于闭源、只能查文档披露的部分。

### 3.2 OpenAI的`context`对象：本地、不发给LLM的业务状态

这是之前在Handoff那节留了个尾巴的东西——"跨服务的协作方式我们会在后续的章节具体学习"，指的就是这个。OpenAI Agents SDK把"状态"拆成两个完全不相关的概念：

- **`context`（`RunContextWrapper`）**：纯本地对象，**永远不会发给LLM**，用来给工具做依赖注入（用户偏好、数据库连接、你自己代码要用的业务数据）。这跟"发给模型看的对话内容"是两个维度——**模型看不到`context`里的任何东西，除非你显式地把它写进prompt**。
- **"conversation state"**：这才是对话历史怎么在多轮之间延续的机制——`to_input_list()`（手动把上一轮的输出转成下一轮的输入）、`session`（SDK自动管理）、`conversation_id`/`previous_response_id`（服务端托管，靠OpenAI自己存历史）。这四种策略我们已经在Handoff那节的讨论里见过，是"消息历史怎么存"这个问题的四种答案。

**这个区分值得记住的点**：`context`解决的是"agent执行过程中，代码本身需要记住/用到的东西"（不是给模型看的），"conversation state"解决的是"模型需要看到的历史对话"（要发给模型）。两者共用"state"这个名字，但一个进API请求体的`tools`/`context`参数，一个进`messages`——协议层面完全是两条不同的路径，不要因为都叫"state"就以为是同一套机制的两种用法。

## 4 Agent Loop and Agent Team的设计

单个Loop之外，还有"一个Loop结束后把控制权交给谁"这个更高层的问题——这一节看OpenAI Agents SDK怎么处理"团队协作"这个维度，跟纯粹的单Loop设计放在一起对比，为后面Layer 3的Multi-Agent编排/子Agent生命周期打个底。

### 4.1 OpenAI Agents SDK：Handoff——三分支循环里"驱动身份中途切换"的机制

Anthropic/Copilot/OpenClaw三家的Loop描述里，一轮结束后只有两种去处：产出最终文本、或者发起工具调用继续循环。OpenAI Agents SDK多了第三种——**Handoff（转交）**，原文对这一点讲得很浅（`running_agents.md`只有一句"If the LLM requests a handoff, we update the current agent and input, and re-run the loop"），去查了专门的`handoffs.md`才搞清楚具体机制。

**核心结论：Handoff在协议层面根本不是独立的动作类型，就是模型调用了一个名字叫`transfer_to_<agent_name>`的普通工具**——跟调用别的工具走的是同一套`tool_use`机制，没有专属的语法/掩码保证。真正的区别发生在Runner这一层的**解释方式**上：Runner认出这个工具名对应一次handoff，不会把结果当`tool_result`喂回去，而是直接把循环里`current_agent`这个状态变量替换成新agent（不同的instructions/tools/model），**在同一个循环里换个驾驶员继续跑**，不是开一个嵌套调用。

![OpenAI Agents SDK Runner循环三分支流程图：Runner.run(starting_agent, input)启动后进入一个循环，current_agent状态变量第一次迭代等于starting_agent，调用LLM(current_agent, current_input)后判断这一轮产出了什么，分三条分支——左边文本输出且无工具调用判定为最终输出，循环结束返回RunResult，是唯一离开循环的出口；中间产出常规tool_use，执行工具、结果append进input、current_agent不变，绕回循环顶部；右边产出的tool_use命中transfer_to_<agent>这个handoff专属工具名，Runner识别为一次handoff，构建HandoffInputData（含input_history/pre_handoff_items/new_items）、可选经过input_filter或nest_handoff_history处理，然后current_agent状态框被整体替换成新agent、input默认变成完整历史，同样绕回循环顶部但驱动身份已经切换；循环外标注超过max_turns会抛MaxTurnsExceeded异常；底部对比表格从"谁驱动下一轮""是否离开当前循环""历史怎么处理""有没有自动返回路径"四个维度对比常规工具调用和handoff两条分支，结论是handoff没有自动返回路径，除非新agent自己又配一条handoff指回去](openai-handoff-vs-tool.svg)

**这个设计跟"子agent当工具"是两种根本不同的协作范式，值得带去后面学Multi-Agent编排/子Agent生命周期时对比**：

- **子agent当工具**（Claude Code的`Agent`工具、OpenClaw的`sessions_spawn`、OpenAI自己的`as_tool()`）——派人干活、干完汇报（`tool_result`），**原agent继续主导**，是"打电话"。
- **Handoff**——直接把主导权整个让出去，**没有自动返回路径**，是"把话筒递给下一个人，自己退场"，从协议/消息历史层面完全看不出中途换过人（新agent之后的每一句话都是正常的`assistant`轮次）。
- 场景动机也不同：`handoffs.md`原文明确是给"客服分诊"场景准备的——一个triage agent判断问题类型后转交给billing/refund等专门agent，用户感觉不到"被转接"发生过，就像打客服电话被转接、但通话没断。这跟"编程助手派个子任务、拿结果继续干"的需求形状完全不一样。

### 4.2 "子agent当工具"内部还有一个分歧：结果是同步塞回`tool_result`，还是异步等通知？

上面说"子agent当工具"是"打电话、原agent继续主导"，但这句话本身掩盖了一个关键实现分歧：**主agent的Turn Loop在等子agent这段时间里，到底是真的卡住不动，还是立刻往下走、子agent完成后再插一条通知进来？** 三家的答案不一样：

| 系统 | 默认是否阻塞主Loop | 结果怎么送回来 | 实锤证据来源 |
|---|---|---|---|
| **Claude Code**（Agent SDK v2.1.198+） | **否**，默认后台运行 | 作为**一条完成通知，在稍后的一轮里到达**，不是塞回原来那次`tool_result` | `code.claude.com/docs/en/agent-sdk/subagents`原文："Subagents run in the background by default. An Agent tool call that omits the `run_in_background` input launches a background subagent, and Claude sets `run_in_background: false` when it needs the result before continuing." + `code.claude.com/docs/en/sub-agents`原文："A background subagent's results reach Claude as a completion notification in a later turn." |
| **OpenClaw**（`sessions_spawn`） | 否，输出端本来就是异步投递 | 进一个持久化投递队列（`session-delivery-queue`），送达失败按代际重试，最多重试到`MAX_DELIVERY_GENERATION=10`代 | 源码：`agent-run-terminal-reply.ts`、`subagent-completion-delivery.ts`、`subagent-completion-result.ts`（`ContextWindow.md §2.3.4` Isolate表格里"OpenClaw — `sessions_spawn`"一行已详细记过这条源码路径） |
| **OpenAI Agents SDK**（`as_tool()`） | **是**，真同步阻塞 | 就是这次`tool_result`本身——因为语言层面`_run_agent_impl`内部直接`await Runner.run(agent, input=resolved_input, ...)`，`await`一个协程必然等它跑完才能往下走 | 源码：`agent.py:576-605`（docstring对比）、`agent.py:943-945`（`Runner.run`调用点），同样已记在`ContextWindow.md §2.3.4`的对比表里 |

**这条分歧对后面学Multi-Agent编排很关键**：默认异步（Claude Code、OpenClaw）意味着主agent需要一套"怎么知道子agent进度/完成"的通知或轮询机制；默认同步（OpenAI `as_tool()`）意味着主agent这一步就是纯粹的等待，没有"边等边干别的"这个选项——**"子agent当工具"这五个字本身不足以描述清楚协作模式，还要追问"这次调用会不会让主Loop卡住"这个更底层的问题**。另外Claude Code的例子还说明：这不是非黑即白的系统级设定，是**模型自己每次调用时可以选**（通过`run_in_background`参数），默认异步、但判断"这次必须先拿到结果"时会主动切成同步。

## 5 参考资料

**理念层——为什么Loop要这么设计**

- Anthropic，[Building Effective AI Agents](Building%20Effective%20AI%20Agents学习笔记.md)
- ——定义"Agent = LLM在循环里自主使用工具"，最小可行Loop的设计哲学：把方向盘交给LLM、靠环境反馈（工具结果/代码执行）判断进度、设终止条件防止失控。

**实现层——官方产品怎么具体做的**

- Claude Code Docs，[How the agent loop works](https://code.claude.com/docs/en/agent-sdk/agent-loop)——Claude Agent SDK的Loop具体实现：`think → act → observe → repeat`，消息生命周期、工具执行、Loop怎么消耗context window。关键细节：Loop不跑在调用方的应用进程里，跑在内嵌的Claude Code CLI二进制里，应用通过stdin/stdout的NDJSON跟它通信。
- GitHub Docs，[The agent loop](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/agent-loop)（Copilot CLI/SDK）——对"Turn"给出目前查到的最精确定义：一个Turn = 一次LLM API调用 + 它引发的后果（发送对话历史→LLM可能带工具请求返回→执行完工具才算这个Turn结束），每次迭代对应一对`assistant.turn_start`/`assistant.turn_end`事件，没有隐藏调用。

**开源框架——生产级实现要多考虑什么**

- OpenClaw，[Agent loop](https://docs.openclaw.ai/concepts/agent-loop) + [Agent runtime architecture](https://docs.openclaw.ai/agent-runtime-architecture)——七阶段Loop（校验入参→组装Prompt/context→模型推理+流式输出→工具执行→持久化→生命周期事件），额外做了per-session串行化和全局队列协调并发session，比理念层文章更贴近工程实现要考虑的细节。

**对比样本——不同的设计选择**

- OpenAI Agents SDK，[Running agents](https://openai.github.io/openai-agents-python/running_agents/)——Loop的终止条件多了"handoff"分支：模型可以把任务转交给另一个专门的sub-agent，Loop带着新agent继续跑，不是直接结束。这个概念在Anthropic/Copilot的Loop描述里没有对应物。

**通用框架——中小公司常用，跟前面几家不是一个量级的比较对象**

- LangChain官方博客，[How to think about agent frameworks](https://www.langchain.com/blog/how-to-think-about-agent-frameworks)（理念层）+ LangGraph官方文档，[Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)（执行机制层）+ [`create_agent`](https://reference.langchain.com/python/langchain/agents/create_agent)（具体loop实例，源码验证过，见[create_agent学习笔记](create_agent（LangChain）学习笔记.md)）——**关键定性：LangGraph不是"一个agent loop长什么样"，是一个通用的图执行引擎（借鉴Google的Pregel系统，State/Nodes/Edges + 消息传递 + 离散"超步"），agent loop只是在这套引擎上搭出来的一种拓扑（靠条件边指回之前的节点形成循环），不是引擎自带的唯一形态**。这跟前5家"一上来就讲Loop本身"的组织方式完全不同，要拆两层资料对着看。
