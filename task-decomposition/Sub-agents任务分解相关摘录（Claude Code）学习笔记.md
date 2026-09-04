# Sub-agents任务分解相关摘录（Claude Code）

官方文档：[Sub-agents](https://code.claude.com/docs/en/sub-agents.md)（全文1316行）

**范围说明**：这篇文档的URL之前已经被摸过两次——`multi-agent-orchestration/Subagents in the SDK（Claude Code）学习笔记.md`整篇译过SDK参考页（不是同一篇），`subagent-termination/Sub-agents终止相关摘录（Claude Code）学习笔记.md`按"终止条件"这个窄范围摘过这篇文档。这次只挑跟"任务分解策略"直接相关、之前两篇都没覆盖的部分：自动委派怎么判断、"Common patterns"三种模式（隔离高噪音操作/并行调研/链式委派）、"要不要用subagent"的决策清单。其余内容（怎么配置、工具权限、hooks、fork机制等）跳过。

## 1 自动委派怎么判断——匹配任务描述，不是复杂度打分

原文：

> Claude automatically delegates tasks based on the task description in your request, the `description` field in subagent configurations, and current context. To encourage proactive delegation, include phrases like "use proactively" in your subagent's description field.

翻译：Claude自动委派任务，靠的是**你请求里的任务描述**、**subagent配置里的`description`字段**、以及**当前上下文**这三者的匹配——不是像Anthropic研究博客那样嵌一套"简单查询1个agent+3-10次调用"式的复杂度阈值。想让某个subagent更容易被主动选中，在它的`description`字段里加"use proactively"这类措辞。

**这跟本章前面几家的"要不要拆"判据是不同的机制类型**：Anthropic/LangChain/OpenAI给的是**复杂度门槛**（多少步、多少工具、多少条件分支才该拆）；这里描述的是**语义匹配**（这次任务的描述，跟哪个已定义好的subagent的`description`更贴合，就委派给它）——前提是已经存在预先配置好的专职subagent，判断的不是"要不要拆"，是"这次任务该不该交给某个现成的专家"，这是委派决策的另一个维度，值得跟前面几家的量化门槛区分开看。

## 2 Common patterns——三种模式，对应三种不同的拆分动机

原文给了三个具体模式，每个动机都不一样：

**Isolate high-volume operations（隔离高噪音操作）**：

> One of the most effective uses for subagents is isolating operations that produce large amounts of output. Running tests, fetching documentation, or processing log files can consume significant context. By delegating these to a subagent, the verbose output stays in the subagent's context while only the relevant summary returns to your main conversation.

翻译：subagent最有效的用法之一，是隔离那些会产生大量输出的操作。跑测试、抓文档、处理日志文件都会大量消耗上下文——委派给subagent后，冗长的输出留在subagent自己的上下文里，只有相关摘要回传给主对话。**这条拆分动机是"上下文体积"，不是"任务步骤多少"或"逻辑复杂度"**，是本章目前几家判据里没出现过的一个独立维度。

**Run parallel research（并行调研）**：

> For independent investigations, spawn multiple subagents to work simultaneously... Each subagent explores its area independently, then Claude synthesizes the findings. This works best when the research paths don't depend on each other.

翻译：对于互相独立的调研，同时派生多个subagent并行工作，每个subagent各自独立探索自己的方向，最后Claude综合所有发现——**这个模式最适合"调研路径互相不依赖"的场景**。原文附了一条警告：subagent完成后结果都要返回主对话，如果每个subagent都返回详细结果，会大量消耗主上下文；如果工作需要长期并行跑，或者装不进一个上下文窗口，应该用[独立session](/docs/en/agents)配合[跨session消息传递](/docs/en/cross-session-messaging)，不是硬塞进同一个对话里的多个subagent。

**Chain subagents（链式委派）**：

> For multi-step workflows, ask Claude to use subagents in sequence. Each subagent completes its task and returns results to Claude, which then passes relevant context to the next subagent.

翻译：对多步骤的工作流，让Claude依次使用多个subagent——每个subagent完成任务后把结果返回给Claude，Claude再把相关上下文传给下一个subagent。原文给的例子是"先用code-reviewer subagent找性能问题，再用optimizer subagent去修"——**这是本章目前查到的、最直接对应"分解出有先后依赖的步骤序列"这个具体模式的一句官方表述**，跟"并行调研"（互相独立）正好是相对的两种拆分形状。

**这个例句本身要单独核对一下，它踩在本章边界线上**：例句里用户已经点名了具体是哪两个subagent、按什么先后顺序，Claude只是照做，"拆成几步、每步派给谁"这个决策不是Claude现场推理出来的。但"Chain subagents"这个模式**本身**是中性的——标题那句"ask Claude to use subagents in sequence"只是一个笼统指示，不强制用户必须把话说满；用户完全可以只给一个笼统指令（"这是个多步流程，拆成subagent依次处理"），把"具体拆几步、每步谁来做"这个决策留给Claude自己判断。**更准确的定位是：这是一种"用户的prompt辅助/引导agent完善任务流程"的中间形态**——用户负责点出"这里需要链式分解"这个大方向和边界（"多步工作流""依次处理"），具体怎么拆、拆成几步、每步的细节，可以是用户说清楚，也可以留给Claude自己判断，取决于用户这次prompt给到多细。文档选的这个具体例子刚好是"用户说得比较满"的那一端，不能代表整个模式都排除了模型自己决策的情况。

## 3 "要不要用subagent"的决策清单

原文给了一份对照清单，不是量化阈值，是场景列举：

> Use the **main conversation** when:
> * The task needs frequent back-and-forth or iterative refinement
> * Multiple phases share significant context, such as planning, implementation, and testing
> * You're making a quick, targeted change
> * Latency matters. A subagent that isn't a fork starts fresh and may need time to gather context
>
> Use **subagents** when:
> * The task produces verbose output you don't need in your main context
> * You want to enforce specific tool restrictions or permissions
> * The work is self-contained and can return a summary

翻译：**用主对话**：任务需要频繁来回迭代打磨；多个阶段（规划、实现、测试）共享大量上下文；只是想做一个快速、针对性的小改动；延迟敏感——非fork的subagent要从零开始收集上下文，需要时间。**用subagent**：任务会产出你不需要留在主上下文里的冗长输出；想强制限定特定的工具权限；这项工作本身是自包含的、能总结成一份摘要返回。

原文还顺带提了两个"看起来像但不是subagent"的选项：需要可复用的prompt/workflow、但想留在主对话上下文里跑，该用[Skills](/docs/en/skills)；针对对话里已经存在的内容提问，用[`/btw`](/docs/en/interactive-mode#side-questions-with-%2Fbtw)（能看到完整上下文但没有工具访问权限，答案也不进历史记录）。

## 值得记的点

- **这篇文档没有给出量化阈值**，跟Anthropic"3-10次调用"、LangChain"3步"、OpenAI"tool overload"这几条比，Claude Code这份文档给的是**场景清单式**的判断依据，不是数字门槛——同一个"要不要拆"的问题，各家给出判据的**形式**本身也不统一，有的量化、有的场景化。
- **"链式"和"并行"这组对照，是本章目前查到的、对"分解出的子任务之间到底有没有依赖关系"这一层最直接的两分法**——Anthropic/Magentic-One讲的更多是"怎么定计划"，这里直接给了两个具体的、可以直接套用的形状名字（chain vs parallel），跟Claude Code Dynamic Workflows笔记里那六种更细的分解模式（逐项审计+对抗验证、反复修复直到通过等）是同一个话题下不同颗粒度的两层表述。
- **自动委派靠语义匹配，不是复杂度打分**——这条提醒了一件容易被忽略的事：本章反复讨论的"要不要拆"，默认语境都是"运行时现场决定"（Anthropic/Magentic-One式），但Claude Code这边还有一条平行的机制——如果已经存在预先配置好的专职subagent，委派与否很大程度上取决于任务描述和subagent`description`字段的语义匹配程度，这也是一种"分解决策"，只是决策依据完全不同。
