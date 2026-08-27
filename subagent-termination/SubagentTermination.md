# 子Agent终止条件

Layer 3继Multi-Agent编排之后的一章。原计划标题是"子Agent生命周期"，调研后判断范围要收窄：子agent"如何启动"已经在[Multi-Agent 编排](../multi-agent-orchestration/MultiAgentOrchestration.md)学过，"如何运行"（hook/middleware挂载点、Execution State/Business State）已经在[Turn Loop 设计](../agent-loop/TurnLoop.md)学过，唯一没被覆盖过的是**子agent运行的边界条件——正常完成之外，什么条件会让它提前停下来、以及能不能被主动叫停/暂停恢复**。子agent和主agent的关键区别：子agent有明确的终止时刻（完成父agent交付的任务），主agent没有这个问题，一轮loop结束后只是回到等待用户输入的状态，不会被销毁。

## 目录

- [1 背景](#1-背景)
- [2 学习笔记](#2-学习笔记)
  - [2.1 正常完成判定](#21-正常完成判定)
  - [2.2 超时与失速](#22-超时与失速)
  - [2.3 主动取消](#23-主动取消)
  - [2.4 暂停与恢复](#24-暂停与恢复)
- [3 参考资料](#3-参考资料)

## 1 背景

**结论先行**：四家的共性是——都有"正常完成"和"暂停/恢复"这两层基本机制，这是subagent运行模型的最小公约数；而且**每一家都会把subagent拆成"阻塞等结果"和"扔出去自己接着干"两条路径，取消这类主动控制能力几乎总是只挂在非阻塞那条路径上**——OpenAI的`as_tool()`默认同步/传`on_stream`才流式，Claude Code的前台/后台，DeepAgents的同步`task`工具/异步远程subagent，都是同一个分野。真正的差异在于**给"非正常退出"设置了多少层强制限制**：OpenAI（`max_turns`）、Claude Code（失速检测）、LangGraph/DeepAgents（`recursion_limit`）各自都有一层"防止失控"的兜底条件——**这一点最初的表格判断错了：以为LangGraph完全没有轮次/步数上限，实际上核心库自带`recursion_limit`（默认10007），只是这个机制记在跟`interrupt()`完全不同的源码文件里，第一轮只读了`interrupts.md`一篇文档没扫到**；OpenClaw把"限制"和"崩溃恢复"做成了最完整的一套（超时+存活检测+孤儿恢复三件套）。

| 维度 | OpenAI Agents SDK | Claude Code | OpenClaw | LangGraph / DeepAgents |
|---|---|---|---|---|
| **正常完成判定** | "final output"规则：产出期望类型文本+无tool calls，`as_tool()`嵌套run复用同一规则，不是子agent专属 | UI层面就区分两种终态：正常完成行立即消失，失败/被停留30秒；API错误按前台/后台两条不同规则决定给不给部分结果 | 四层不同的Status词表（内部7值状态机→展示映射→Announce的`ok/error/timeout/unknown`→人类可读文案），明确"不从模型文本推断" | 同步`task`工具：跑到完成、返回恰好一份最终报告；异步subagent：`AsyncTask.status`到达`success` |
| **总量/超时限制** | `as_tool(max_turns=...)`——子agent独立轮次上限，跟父agent的计数器不共享 | 无总轮次上限概念 | `runTimeoutSeconds`——全局默认+按次覆盖两层（无按agent覆盖） | **`recursion_limit`**（核心库默认10007，DeepAgents编译时设成9999），子agent可以有自己独立绑定的值、跟父agent的按key合并冲突时子agent的赢——是LangGraph版的`max_turns`，只是按"步数"不按"轮次" |
| **失速检测**（卡住不动，区别于"总量超限"） | 无专属机制（`ModelTimeoutError`管的是单次模型调用，颗粒度不同） | `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`——仅后台subagent，计时器随流式进度事件重置，同步subagent不适用 | 无独立"失速"概念，但"存活检测"（stale-run窗口，2小时或run超时+宽限期）解决的是同一类问题 | 未查到专属的"卡住不动"检测机制；异步subagent终态词表里有`timeout`，但触发这个状态的具体机制在这次读到的中间件源码里没暴露参数，可能是远程LangGraph Platform服务端自己的run级配置 |
| **主动取消** | 无子agent专属取消API；`failure_error_function`兜底把嵌套run的异常转成消息喂回父agent，不是"取消"本身 | 三种停止来源（人按`x`/SDK `stop_task`/Claude自己`TaskStop`），**谁停的决定停下来后能不能被`SendMessage`自动恢复** | `Tool: subagents`的`action:"cancel"`，权限限定在请求者自己的会话树内，叶子子agent不能取消别的session的任务 | **`cancel_async_task`工具**——只对异步远程subagent有效，转发给远程LangGraph Platform SDK的`client.runs.cancel(thread_id, run_id)`；同步`task`工具**没有**取消机制（跟其他三家一样，取消能力只长在非阻塞路径上） |
| **暂停与恢复** | 无确认的subagent专属机制（`Streaming.md`的`cancel()`/`interruptions`验证后排除，`as_tool()`嵌套审批恢复逻辑`_nested_approvals_status`留待后续查证） | `SendMessage`按agent ID/name恢复，续用同一个ID、状态重置为running，transcript独立于主对话持久化 | `sessions_yield`主动挂起等待完成事件；崩溃恢复最完整——存活检测+孤儿恢复流程+recovery tombstone防重复恢复 | `interrupt()`+`Command(resume=...)`，**恢复=整个node重新执行**（不是从暂停位置续接），subgraph场景父子两层各自独立重跑；异步subagent终态词表里也有`interrupted`，对应远程运行中触发了interrupt |

**看这张表最值得记的一点**：LangGraph核心库的`interrupt()`确实是一个不带超时/取消的纯暂停原语，这部分没错；**但这只是LangGraph整套机制里"暂停恢复"这一层，不能代表"LangGraph生态完全没有限制/取消能力"**——`recursion_limit`是核心库自带的、独立于`interrupt()`的另一套机制，`cancel_async_task`则是搭在LangGraph之上的DeepAgents SDK提供的、专门给异步subagent用的取消工具。这个教训本身值得记：**判断"某个框架有没有X机制"，不能只读一篇范围很窄的文档就下全称判断，要么扫核心库的错误/配置定义，要么去查搭在它上面的官方SDK**。

## 2 学习笔记

### 2.1 正常完成判定

**OpenAI Agents SDK**（详见[Running agents（OpenAI Agents SDK）学习笔记.md](Running%20agents（OpenAI%20Agents%20SDK）学习笔记.md) §1）：子agent（`as_tool()`）内部嵌套的`Runner.run()`跟父agent用的是同一条"final output"判定规则——产出符合期望类型的文本、且没有tool calls，就算正常结束。这条规则不是subagent专属的，是通用Runner循环规则，子agent的嵌套run只是复用了它。

**Claude Code**（详见[Sub-agents终止相关摘录（Claude Code）学习笔记.md](Sub-agents终止相关摘录（Claude%20Code）学习笔记.md) §1）：正常完成 vs 失败/被停止是两种UI层面就区分开的终态——正常完成的subagent行**立即**从面板消失（footer提示30秒可查transcript）；失败或被停止的行**保留30秒**（可按`x`提前清除）。`/tasks`列表同理：完成的继续留着（标记done），失败/被停止的直接离开列表。

**OpenClaw**（详见[Sub-agents（OpenClaw）学习笔记.md](../multi-agent-orchestration/Sub-agents（OpenClaw）学习笔记.md) §4，本章回填）：直接翻源码发现"Status"这个概念在OpenClaw里有四套不同词表——内部`TaskStatus`7值状态机（`queued`/`running`/`succeeded`/`failed`/`timed_out`/`cancelled`/`lost`）→`subagents`工具展示映射（`STATUS_MAP`，注意`lost`被合并展示成"failed"）→完成事件"Announce context"的`ok`/`error`/`timeout`/`unknown`→请求者最终读到的人类可读文案"completed; ready for parent review"/"failed"/"timed out"/"unknown"。跟Claude Code"Status不从模型文本推断"是同一类不信任子agent自我汇报的设计，但OpenClaw这边同一个概念在不同层级各自维护一套词表。

### 2.2 超时与失速

**OpenAI Agents SDK**（详见[Running agents（OpenAI Agents SDK）学习笔记.md](Running%20agents（OpenAI%20Agents%20SDK）学习笔记.md) §1-3）：

- `as_tool(max_turns=...)`——子agent自己的轮次上限，跟父agent的`max_turns`是两个独立的计数器，默认都是`DEFAULT_MAX_TURNS`（10），可分别覆盖（source: `agent.py:594/717`）。
- `failure_error_function`（默认`default_tool_error_function`）——子agent嵌套run撞到`MaxTurnsExceeded`或其他异常时，默认不会让父agent的run跟着崩，而是转成一条错误消息喂给父agent的LLM（source: `agent.py:599/1025`、`tool.py:1863`）。
- 工具级超时`ToolTimeoutError`的`timeout_behavior`只有两种取值：`"error_as_result"`（超时当普通结果返回）/`"raise_exception"`（抛异常）（source: `tool.py:1875`）——跟`failure_error_function`是同一种"默认倾向于喂消息给模型、而不是直接抛异常炸穿链路"的设计取向。

**OpenAI Agents SDK补充**（详见[Exceptions参考（OpenAI Agents SDK）学习笔记.md](Exceptions参考（OpenAI%20Agents%20SDK）学习笔记.md)）：`RunErrorDetails`——所有`AgentsException`家族异常都可携带的运行失败快照（`input`/`new_items`/`raw_responses`/`last_agent`/`context_wrapper`等），失败时到底能拿回多少"已经做到哪一步"的信息，是这个主题下几家都要回答的同一个问题（跟Claude Code失速看门狗"部分结果+错误一起交给父agent"、OpenClaw"四种终态"是同一类比较点）。`ModelTimeoutError`（模型调用超时）、`ModelBehaviorError`（模型行为异常，非结构化）也在这里。

**Claude Code**（详见[Sub-agents终止相关摘录（Claude Code）学习笔记.md](Sub-agents终止相关摘录（Claude%20Code）学习笔记.md) §2）：API错误（限流/过载/服务端错误）导致subagent中途结束时，前台/后台两种规则不同——前台看有没有已产出文本输出决定给不给部分结果；后台一律把最后输出连同错误一起交给Claude，"已经做的部分工作不会丢失"（原文明确这句）。是"运行被打断能拿回多少"这个问题的Claude Code式答案，跟OpenAI"统一异常快照"的思路不同，是"按运行位置分两条规则"。

**Claude Code补充**（详见[环境变量参考（Claude Code）学习笔记.md](环境变量参考（Claude%20Code）学习笔记.md)）：三条变量构成一套依赖链条——`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`（后台模式存不存在）→`CLAUDE_AUTO_BACKGROUND_TASKS`（跑多久自动转后台，约2分钟）→`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`（转后台后卡多久算失速，默认10分钟，计时器随每次流式进度事件重置，不是总时长超时）。"失速"（卡住不动）和"总时长超时"（如OpenAI的`max_turns`）是两个不同维度，Claude Code是目前查到的唯一一家给失速单独设了专属机制的。

**Claude Code再补充**（详见[TypeScript SDK参考（Claude Code）学习笔记.md](TypeScript%20SDK参考（Claude%20Code）学习笔记.md) §2）：`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`官方原文明确"Does not apply to synchronous subagents"——同步subagent没有流式进度事件可以重置计时器，失速看门狗这层保护天然用不上，呼应了OpenAI侧"同步subagent不涉及streaming"的结论，Claude Code这边更进一步：同步subagent连失速检测都没有。

**OpenClaw**（详见[Sub-agents（OpenClaw）学习笔记.md](../multi-agent-orchestration/Sub-agents（OpenClaw）学习笔记.md) §6，本章回填）：`runTimeoutSeconds`只有**全局默认**（`agents.defaults.subagents.runTimeoutSeconds`，不配=不限时）→**按次覆盖**（`sessions_spawn`调用时传参）两层，没有按agent覆盖这一中间层（纠正了早前一轮调研"三层配置"的结论，回头核对原文才发现的偏差）。

**LangGraph / DeepAgents**（详见[Interrupts（LangGraph）学习笔记.md](Interrupts（LangGraph）学习笔记.md) §4-5，含更正）：`interrupt()`本身"无限期等待"（原文原话）没错，但这只是暂停原语这一层——**LangGraph核心库另有`recursion_limit`**（`graph.invoke(config={"recursion_limit": N})`，默认`10007`，源码`_internal/_config.py`），超过步数还没停会抛`GraphRecursionError`，官方docstring明确这是"prevents infinite loops"。DeepAgents（搭在LangGraph上的官方SDK）编译agent时设成`9999`；子agent可以有自己**独立绑定**的`recursion_limit`，跟父agent冲突时子agent自己的赢（源码`middleware/subagents.py`注释，引用`langgraph#7926`的按key合并机制）——这是LangGraph版的`max_turns`，跟OpenAI`as_tool(max_turns=...)`是同一类"父子独立配置、不共享计数器"的设计。

### 2.3 主动取消

**OpenAI Agents SDK**（详见[Exceptions参考（OpenAI Agents SDK）学习笔记.md](Exceptions参考（OpenAI%20Agents%20SDK）学习笔记.md)）：`MCPToolCancellationError`——名字唯一直接带"cancellation"的异常，但范围很窄，只管MCP工具调用被取消，不是"子agent被取消"的通用机制；子agent本身的取消对应的还是§2.2里`as_tool()`的`failure_error_function`路径。

**Claude Code**（详见[Sub-agents终止相关摘录（Claude Code）学习笔记.md](Sub-agents终止相关摘录（Claude%20Code）学习笔记.md) §3，本章目前最有价值的发现）：三种停止来源——`/tasks`面板按`x`（人）、SDK的`stop_task`请求（应用代码）、Claude自己调`TaskStop`工具——**停下来之后能不能被`SendMessage`悄悄自动恢复，取决于是谁下的手**：人/应用代码主动停止的**不能**自动恢复（`SendMessage`返回拒绝，告知agent已取消），Claude自己用`TaskStop`停的**能**自动恢复（跟正常完成的subagent一样）。原文原话：`a subagent you stopped yourself, with x in /tasks or an SDK stop_task request, doesn't auto-resume`。人类停止的subagent不是彻底死掉——只要行还在面板里（30秒窗口内），可以直接在它的transcript里输入内容手动恢复，清掉停止标记。

**Claude Code补充**（详见[TypeScript SDK参考（Claude Code）学习笔记.md](TypeScript%20SDK参考（Claude%20Code）学习笔记.md) §1）：`Query.stopTask(taskId: string): Promise<void>`——上面SDK`stop_task`请求的确切API形态，按`taskId`精确指定要停哪一个子任务，不是笼统打断整个session。同一个`Query`对象上还有`interrupt()`/`close()`两个方法，但都不接受`taskId`参数，管的是整个主查询/底层进程本身，不是subagent专属，排除在外——判断一个"停止类"API是不是subagent粒度的，关键看它有没有一个"指定停哪一个"的参数。

**OpenClaw**（详见[Sub-agents（OpenClaw）学习笔记.md](../multi-agent-orchestration/Sub-agents（OpenClaw）学习笔记.md) §8，本章回填）：`Tool: subagents`的`action:"cancel"`配合`list`拿到的`taskId`停止任务，权限边界原文原话——"Cancellation is confined to the controlled session tree; a leaf sub-agent cannot cancel work owned by another session."——**叶子sub-agent不能取消属于另一个session的工作**，取消权限被限定在请求者自己这棵受控会话树内。跟Claude Code"谁停的决定能不能自动恢复"是不同维度的权限设计：一个管"恢复权限"，一个管"取消目标的范围"。

**LangGraph核心库——确认的空白**：`interrupts.md`全文搜索"cancel"字样的命中全部是用户自己在图里定义的业务节点名（比如审批被拒绝后路由到一个叫`cancel`的node），不是框架提供的取消API，核心库这一层没有对应机制。

**DeepAgents（修正——不是完全没有，只对异步subagent生效）**（详见[Interrupts（LangGraph）学习笔记.md](Interrupts（LangGraph）学习笔记.md) §5）：`AsyncSubAgentMiddleware`暴露`cancel_async_task`工具，源码直接调用远程LangGraph Platform SDK的`client.runs.cancel(thread_id=..., run_id=...)`，同/异步两个版本都有；取消后本地追踪的`AsyncTask.status`写成`"cancelled"`。**但这只对异步远程subagent生效**——同步的`task`工具（子agent跑到完成、返回一份最终报告）没有取消机制，只能靠`recursion_limit`兜底，这跟"取消能力只长在非阻塞路径上"这条本章反复出现的规律一致。

### 2.4 暂停与恢复

**Claude Code**（详见[Sub-agents终止相关摘录（Claude Code）学习笔记.md](Sub-agents终止相关摘录（Claude%20Code）学习笔记.md) §4）：resume靠`SendMessage`把subagent的agent ID或name填进`to`字段，不需要开启agent teams；内置Explore/Plan是一次性的，不返回agent ID，没法resume；resume后沿用同一个ID、状态重新显示为running；subagent transcript独立于主对话持久化（主对话compact不影响它），默认30天后按retention策略清理，路径`~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`。

**OpenClaw**（详见[Sub-agents（OpenClaw）学习笔记.md](../multi-agent-orchestration/Sub-agents（OpenClaw）学习笔记.md) §13，本章回填，目前几家里唯一查到的完整"崩溃恢复"机制）：OpenClaw不把"没有`endedAt`字段"当成"还活着"的可靠证据——**stale-run窗口**（2小时，或"配置的run超时+一小段宽限期"取更大值）之后，未结束的run不再被算作活跃/待定，不再占并发名额。Gateway重启后，标记`abortedLastRun: true`的子会话走**孤儿恢复流程**：直接判定结束（不恢复），全新子会话则先收到一条合成resume消息再清除中止标记。恢复次数**有界**——同一子代session在"快速重连窗口"内被反复接纳进恢复流程，会被打上**recovery tombstone**，之后重启不再自动恢复，需要人工`openclaw tasks maintenance --apply`/`openclaw doctor --fix`介入。

**LangGraph**（详见[Interrupts（LangGraph）学习笔记.md](Interrupts（LangGraph）学习笔记.md) §1-3）：`interrupt(payload)`挂起执行（靠抛异常实现）→checkpointer存状态、图"无限期等待"→`Command(resume=value)`带同一个`thread_id`恢复，value成为`interrupt()`的返回值。**关键机制差异**：恢复时是**从头重新执行整个node**，不是从暂停的位置继续——这是LangGraph官方专门写一整节"Rules of interrupts"来约束的根本原因：node不能用裸`try/except`包住`interrupt()`（会吞掉挂起用的异常）、同node内多个`interrupt()`顺序不能变（严格按索引匹配resume值）、`interrupt()`之前的副作用必须幂等（会被重跑）。**Subgraph场景**（LangGraph里最接近"子agent"的概念）：父图和subgraph两层**各自独立地**从各自触发/调用的node开头重新执行，不是只重跑最内层——直接回答了"子执行单元暂停恢复，外层要不要跟着重跑"这个问题：要。**跟OpenAI/Claude Code的核心差异**：后两家都是"从暂停的精确位置继续，不重跑已完成部分"，LangGraph是唯一一家"恢复=重新跑整个node"的，两种心智模型完全不同。

**DeepAgents补充**（详见[Interrupts（LangGraph）学习笔记.md](Interrupts（LangGraph）学习笔记.md) §5）：异步subagent的终态词表`_TERMINAL_STATUSES = {"cancelled", "success", "error", "timeout", "interrupted"}`里有`"interrupted"`一项，对应远程运行中触发了`interrupt()`被暂停——跟上面核心库的暂停机制是同一件事在异步远程场景下的体现。

（待补——`agent.py`里`as_tool()`嵌套调用的审批恢复逻辑（`_nested_approvals_status`/`resume_state`，约第850-880行），OpenAI侧对应的暂停恢复机制，留待后续专门查证，可以拿来跟LangGraph这里的subgraph重跑规则对比）

## 3 参考资料

**OpenAI Agents SDK**

- [Running agents](https://openai.github.io/openai-agents-python/running_agents/)——"The agent loop"/"Errors and recovery"两节，`max_turns`/`MaxTurnsExceeded`
- [Exceptions参考](https://openai.github.io/openai-agents-python/ref/exceptions/)——`ModelTimeoutError`/`ToolTimeoutError`/`MCPToolCancellationError`等终止相关异常类

**Claude Code**

- [Sub-agents](https://code.claude.com/docs/en/sub-agents)——失败/停止后行保留30秒等终态UI表现
- [环境变量参考](https://code.claude.com/docs/en/env-vars)——`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`、`CLAUDE_AUTO_BACKGROUND_TASKS`
- [TypeScript SDK参考](https://code.claude.com/docs/en/agent-sdk/typescript)——`Query.stopTask()`

**OpenClaw**

- [Sub-agents工具文档](https://docs.openclaw.ai/tools/subagents)——已在`multi-agent-orchestration/Sub-agents（OpenClaw）学习笔记.md`整篇译过，本章回填了终止相关细节（结合docs全文+`subagents-tool.ts`源码逐条核实）：Status在源码里其实是四套不同词表（内部7值状态机/list展示映射/Announce context 4值/人类可读文案）、`runTimeoutSeconds`实际只有全局默认+按次覆盖两层（不是三层）、`Tool: subagents`的cancel权限边界（叶子子agent不能取消别的session的任务）、"存活检测与恢复"完整机制（stale-run窗口/孤儿恢复/recovery tombstone）

**LangGraph / DeepAgents**

- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)——`interrupt()`+`Command(resume=...)`，恢复时整个node重跑（不是从暂停位置继续）、subgraph场景父子两层各自重跑；这篇文档本身确实没有超时/取消机制，但**不代表LangGraph/DeepAgents生态整体没有**，见下面两条源码级更正
- `langgraph`核心库`errors.py`/`pregel/main.py`/`_internal/_config.py`（源码，非文档）——`recursion_limit`（默认10007）/`GraphRecursionError`，是LangGraph版的`max_turns`
- DeepAgents官方文档[`openwiki/concepts/subagents-skills.md`](https://github.com/langchain-ai/deepagents/blob/main/openwiki/concepts/subagents-skills.md) + 源码`middleware/subagents.py`/`middleware/async_subagents.py`——同步`task`工具 vs 异步远程subagent两条路径，`cancel_async_task`真正的取消机制（只对异步生效），子agent可独立绑定`recursion_limit`

**GitHub Copilot——已确认的空白**

搜到的"59分钟超时"属于Copilot Cloud Agent（云端异步编码agent，GitHub Actions里跑，`timeout-minutes`配置），跟Custom agents/Fleet（CLI/SDK产品线）不是同一产品，不能混为一谈。CLI/SDK这条线没查到专属的子agent超时/取消机制文档，如实标注为空白，不编造。

**明确排除的范围**（不在本章学习）

- 生命周期可观测性钩子（OpenAI `RunHooks`/`AgentHooks`等）——跟`agent-loop/TurnLoop.md` §2.3的hook挂载点主题重复度太高
- AutoGen"官方承认没做paging in/out"的发现——是个趣闻，撑不起独立小节
- OpenAI Agents SDK的`Streaming`文档（`result.cancel()`/`RunResultStreaming.interruptions`）——source验证过`as_tool()`默认路径（不传`on_stream`）走`await Runner.run(...)`，压根不产生streaming对象；就算传了`on_stream`，内部的`run_result_streaming`也只在`_run_agent_impl`内部消费，从不对外暴露，应用代码拿不到可以调`.cancel()`的对象。`cancel()`只对顶层`Runner.run_streamed()`调用有意义，是主agent自己的循环终止方式，不是subagent专属机制
