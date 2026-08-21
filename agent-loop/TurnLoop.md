# Turn Loop 设计

Layer 3第一个话题，也是Agent架构里最核心的一块。跟Layer 2不同，这里没有一篇单一的权威规范可以当骨架，资料分散在几家厂商的产品文档、一篇理念层文章、和开源框架的实现文档里，先把这几篇定下来，逐篇精读。

## 目录

- [1 Agent Loop是什么](#1-agent-loop是什么)
- [2 Agent Loop的开源实现](#2-agent-loop的开源实现)
  - [2.1 两张流程图对照：OpenClaw vs. `create_agent`](#21-两张流程图对照openclaw-vs-create_agent)
  - [2.2 Loop设计对比：跳转机制、循环单元、暂停恢复、终止条件](#22-loop设计对比跳转机制循环单元暂停恢复终止条件)
  - [2.3 Hook位置逐一对照：哪些是两边都有、哪些是各自独有](#23-hook位置逐一对照哪些是两边都有哪些是各自独有)
- [3 Agent Loop and Agent Team的设计](#3-agent-loop-and-agent-team的设计)
  - [3.1 OpenAI Agents SDK：Handoff——三分支循环里"驱动身份中途切换"的机制](#31-openai-agents-sdkhandoff三分支循环里驱动身份中途切换的机制)
  - [3.2 "子agent当工具"内部还有一个分歧：结果是同步塞回`tool_result`，还是异步等通知？](#32-子agent当工具内部还有一个分歧结果是同步塞回tool_result还是异步等通知)
- [4 参考资料](#4-参考资料)

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

## 3 Agent Loop and Agent Team的设计

单个Loop之外，还有"一个Loop结束后把控制权交给谁"这个更高层的问题——这一节看OpenAI Agents SDK怎么处理"团队协作"这个维度，跟纯粹的单Loop设计放在一起对比，为后面Layer 3的Multi-Agent编排/子Agent生命周期打个底。

### 3.1 OpenAI Agents SDK：Handoff——三分支循环里"驱动身份中途切换"的机制

Anthropic/Copilot/OpenClaw三家的Loop描述里，一轮结束后只有两种去处：产出最终文本、或者发起工具调用继续循环。OpenAI Agents SDK多了第三种——**Handoff（转交）**，原文对这一点讲得很浅（`running_agents.md`只有一句"If the LLM requests a handoff, we update the current agent and input, and re-run the loop"），去查了专门的`handoffs.md`才搞清楚具体机制。

**核心结论：Handoff在协议层面根本不是独立的动作类型，就是模型调用了一个名字叫`transfer_to_<agent_name>`的普通工具**——跟调用别的工具走的是同一套`tool_use`机制，没有专属的语法/掩码保证。真正的区别发生在Runner这一层的**解释方式**上：Runner认出这个工具名对应一次handoff，不会把结果当`tool_result`喂回去，而是直接把循环里`current_agent`这个状态变量替换成新agent（不同的instructions/tools/model），**在同一个循环里换个驾驶员继续跑**，不是开一个嵌套调用。

![OpenAI Agents SDK Runner循环三分支流程图：Runner.run(starting_agent, input)启动后进入一个循环，current_agent状态变量第一次迭代等于starting_agent，调用LLM(current_agent, current_input)后判断这一轮产出了什么，分三条分支——左边文本输出且无工具调用判定为最终输出，循环结束返回RunResult，是唯一离开循环的出口；中间产出常规tool_use，执行工具、结果append进input、current_agent不变，绕回循环顶部；右边产出的tool_use命中transfer_to_<agent>这个handoff专属工具名，Runner识别为一次handoff，构建HandoffInputData（含input_history/pre_handoff_items/new_items）、可选经过input_filter或nest_handoff_history处理，然后current_agent状态框被整体替换成新agent、input默认变成完整历史，同样绕回循环顶部但驱动身份已经切换；循环外标注超过max_turns会抛MaxTurnsExceeded异常；底部对比表格从"谁驱动下一轮""是否离开当前循环""历史怎么处理""有没有自动返回路径"四个维度对比常规工具调用和handoff两条分支，结论是handoff没有自动返回路径，除非新agent自己又配一条handoff指回去](openai-handoff-vs-tool.svg)

**这个设计跟"子agent当工具"是两种根本不同的协作范式，值得带去后面学Multi-Agent编排/子Agent生命周期时对比**：

- **子agent当工具**（Claude Code的`Agent`工具、OpenClaw的`sessions_spawn`、OpenAI自己的`as_tool()`）——派人干活、干完汇报（`tool_result`），**原agent继续主导**，是"打电话"。
- **Handoff**——直接把主导权整个让出去，**没有自动返回路径**，是"把话筒递给下一个人，自己退场"，从协议/消息历史层面完全看不出中途换过人（新agent之后的每一句话都是正常的`assistant`轮次）。
- 场景动机也不同：`handoffs.md`原文明确是给"客服分诊"场景准备的——一个triage agent判断问题类型后转交给billing/refund等专门agent，用户感觉不到"被转接"发生过，就像打客服电话被转接、但通话没断。这跟"编程助手派个子任务、拿结果继续干"的需求形状完全不一样。

### 3.2 "子agent当工具"内部还有一个分歧：结果是同步塞回`tool_result`，还是异步等通知？

上面说"子agent当工具"是"打电话、原agent继续主导"，但这句话本身掩盖了一个关键实现分歧：**主agent的Turn Loop在等子agent这段时间里，到底是真的卡住不动，还是立刻往下走、子agent完成后再插一条通知进来？** 三家的答案不一样：

| 系统 | 默认是否阻塞主Loop | 结果怎么送回来 | 实锤证据来源 |
|---|---|---|---|
| **Claude Code**（Agent SDK v2.1.198+） | **否**，默认后台运行 | 作为**一条完成通知，在稍后的一轮里到达**，不是塞回原来那次`tool_result` | `code.claude.com/docs/en/agent-sdk/subagents`原文："Subagents run in the background by default. An Agent tool call that omits the `run_in_background` input launches a background subagent, and Claude sets `run_in_background: false` when it needs the result before continuing." + `code.claude.com/docs/en/sub-agents`原文："A background subagent's results reach Claude as a completion notification in a later turn." |
| **OpenClaw**（`sessions_spawn`） | 否，输出端本来就是异步投递 | 进一个持久化投递队列（`session-delivery-queue`），送达失败按代际重试，最多重试到`MAX_DELIVERY_GENERATION=10`代 | 源码：`agent-run-terminal-reply.ts`、`subagent-completion-delivery.ts`、`subagent-completion-result.ts`（`ContextWindow.md §2.3.4` Isolate表格里"OpenClaw — `sessions_spawn`"一行已详细记过这条源码路径） |
| **OpenAI Agents SDK**（`as_tool()`） | **是**，真同步阻塞 | 就是这次`tool_result`本身——因为语言层面`_run_agent_impl`内部直接`await Runner.run(agent, input=resolved_input, ...)`，`await`一个协程必然等它跑完才能往下走 | 源码：`agent.py:576-605`（docstring对比）、`agent.py:943-945`（`Runner.run`调用点），同样已记在`ContextWindow.md §2.3.4`的对比表里 |

**这条分歧对后面学Multi-Agent编排很关键**：默认异步（Claude Code、OpenClaw）意味着主agent需要一套"怎么知道子agent进度/完成"的通知或轮询机制；默认同步（OpenAI `as_tool()`）意味着主agent这一步就是纯粹的等待，没有"边等边干别的"这个选项——**"子agent当工具"这五个字本身不足以描述清楚协作模式，还要追问"这次调用会不会让主Loop卡住"这个更底层的问题**。另外Claude Code的例子还说明：这不是非黑即白的系统级设定，是**模型自己每次调用时可以选**（通过`run_in_background`参数），默认异步、但判断"这次必须先拿到结果"时会主动切成同步。

## 4 参考资料

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
