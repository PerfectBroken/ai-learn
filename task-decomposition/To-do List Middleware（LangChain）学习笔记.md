# To-do List Middleware（LangChain）

官方文档：[Prebuilt middleware — To-do list](https://docs.langchain.com/oss/python/langchain/middleware/built-in#to-do-list)
源码：`langchain_v1/langchain/agents/middleware/todo.py`（`langchain-ai/langchain`仓库，357行，全文精读——文档页面只给了配置项摘要，真正的prompt原文和执行逻辑都在这份源码里）

**范围说明**：这是LangChain官方现在推的任务分解主推方案——不是"分给子agent"，是**单agent自己拆步骤、用`write_todos`工具维护一份任务列表**。核心内容是这个中间件默认注入的tool description + system prompt，篇幅不算短但信息密度很高，逐字精读；另外附带一个代码级的强制约束机制（禁止并行调用），不只是提示词层面的建议。

## 1 机制概览——一个工具+一段system prompt+一条硬性约束

`TodoListMiddleware`挂载后做三件事：

1. **注入一个`write_todos`工具**——模型调用它来创建/更新任务列表，参数就是一份`Todo`列表，每个`Todo`只有`content`（描述）和`status`（`pending`/`in_progress`/`completed`三态）两个字段
2. **在每次模型调用前，把一段固定的`WRITE_TODOS_SYSTEM_PROMPT`追加进system message**（`wrap_model_call`钩子，源码里写的是"追加"不是"替换"，跟原有system prompt共存）
3. **`after_model`钩子做一个代码级检查**：如果模型在同一轮里并行调用了多次`write_todos`，直接返回报错的`ToolMessage`拒绝执行——**这不是靠提示词"建议不要"，是靠代码强制拒绝**

`write_todos`工具调用本身的返回值也值得记一笔：`Command(update={"todos": todos, "messages": [ToolMessage(f"Updated todo list to {todos}", ...)]})`——每次调用是**整份替换**，不是增量patch，这也是为什么"不能并行调用"是硬约束：两个并行调用会产生"到底哪份列表生效"的歧义，必须靠代码层面挡掉，提示词层面的"请不要这样做"防不住这种情况。

## 2 `write_todos`工具描述原文（`WRITE_TODOS_TOOL_DESCRIPTION`）——本章"3步阈值"的确切出处

完整原文：

> Use this tool to create and manage a structured task list for your current work session. This helps you track progress and organize complex tasks.
>
> Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool and just do the task directly.
>
> ## When to Use This Tool
>
> Use this tool in these scenarios:
>
> 1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
> 2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
> 3. User explicitly requests todo list - When the user directly asks you to use the todo list
> 4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
> 5. The plan may need future revisions or updates based on results from the first few steps
>
> ## How to Use This Tool
>
> 1. When you start working on a task - Mark it as in_progress BEFORE beginning work.
> 2. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation.
> 3. You can also update future tasks, such as deleting them if they are no longer necessary, or adding new tasks that are necessary. Don't change previously completed tasks.
> 4. You can make several updates to the todo list at once. For example, when you complete a task, you can mark the next task you need to start as in_progress.
>
> ## When NOT to Use This Tool
>
> It is important to skip using this tool when:
> 1. There is only a single, straightforward task
> 2. The task is trivial and tracking it provides no benefit
> 3. The task can be completed in less than 3 trivial steps
> 4. The task is purely conversational or informational
>
> ## Task States and Management
>
> 1. **Task States**: Use these states to track progress:
>     - pending: Task not yet started
>     - in_progress: Currently working on (you can have multiple tasks in_progress at a time if they are not related to each other and can be run in parallel)
>     - completed: Task finished successfully
>
> 2. **Task Management**:
>     - Update task status in real-time as you work
>     - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
>     - Complete current tasks before starting new ones
>     - Remove tasks that are no longer relevant from the list entirely
>     - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!.
>     - IMPORTANT: Unless all tasks are completed, you should always have at least one task in_progress.
>
> 3. **Task Completion Requirements**:
>     - ONLY mark a task as completed when you have FULLY accomplished it
>     - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
>     - When blocked, create a new task describing what needs to be resolved
>     - Never mark a task as completed if:
>         - There are unresolved issues or errors
>         - Work is partial or incomplete
>         - You encountered blockers that prevent completion
>         - You couldn't find necessary resources or dependencies
>         - Quality standards haven't been met
>
> 4. **Task Breakdown**:
>     - Create specific, actionable items
>     - Break complex tasks into smaller, manageable steps
>     - Use clear, descriptive task names
>
> Being proactive with task management ensures you complete all requirements successfully
> Remember: If you only need to make a few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all.
>
> ## When You Finish
>
> `write_todos` tracks your work; it does not deliver the answer. Whatever the user asked for — computations, summaries, comparisons, data — must appear as text content in a message after your final `write_todos` call. Marking the last todo complete is not itself an answer to the user.

**几个值得单独拎出来的设计点**：

- **"3步阈值"在开头和结尾各强调了一次**——开头"less than 3 steps...NOT use this tool"，结尾又用大写"Remember"重复一遍类似的话。同一条规则用不同措辞在prompt的头尾各出现一次，是防止模型只读了开头或者被中间大段内容冲淡记忆的常见手法。
- **"多个in_progress"的并行判定条件写得很具体**——"if they are not related to each other and can be run in parallel"，不是简单说"可以有多个in_progress"，而是给了判据（互相不相关+能并行）。
- **"完成"的判定标准列了一份反向清单（什么情况下**不能**标完成）**，而不是只说"完成了才标完成"——五种具体情况（有未解决问题/工作只完成一部分/遇到阻塞/找不到必要资源/没达到质量标准）逐条列出，比一句笼统的"确实做完了才标完成"更难被模型钻空子。
- **"When You Finish"这一节是最容易被忽略但最实际的一条**——防的是一个具体的失败模式：模型把最后一个todo标记为completed，就以为这样已经算回答完用户了。原文明确要求"真正的答案必须出现在最后一次`write_todos`调用之后的一条消息里"，`write_todos`只是追踪工具，不是交付通道。这条本质上是一个跟"任务分解"关系不大、但跟"分解完之后别忘了真正干活"直接相关的工程经验。

## 3 追加进system message的固定文本（`WRITE_TODOS_SYSTEM_PROMPT`）

完整原文：

> ## `write_todos`
>
> You have access to the `write_todos` tool to help you manage and plan complex objectives.
> Use this tool for complex objectives to ensure that you are tracking each necessary step.
> This tool is very helpful for planning complex objectives, and for breaking down these larger complex objectives into smaller steps.
>
> It is critical that you mark todos as completed as soon as you are done with a step. Do not batch up multiple steps before marking them as completed.
> For simple objectives that only require a few steps, it is better to just complete the objective directly and NOT use this tool.
> Writing todos takes time and tokens, use it when it is helpful for managing complex many-step problems! But not for simple few-step requests.
>
> ## Important To-Do List Usage Notes to Remember
>
> - The `write_todos` tool should never be called multiple times in parallel.
> - Don't be afraid to revise the To-Do list as you go. New information may reveal new tasks that need to be done, or old tasks that are irrelevant.
>
> ## Finishing a task
>
> When you finish all work, write your final answer in the message AFTER your last `write_todos` call — not in the same turn as that call. Start the final message with the substantive content the user asked for — the data, computation, summary, or analysis. The user wants the result, not confirmation that the work is done.

**这段跟上面的工具描述内容高度重叠**（3步阈值、别批量标完成、答案要单独一条消息），但措辞更短。**"Writing todos takes time and tokens"这句话把成本意识直接写进了提示词**——不是让模型自己去权衡"要不要用这个工具"，是直接告诉它这个工具本身是有代价的，用多了会浪费token，这是一种把工程约束（成本）翻译成模型能理解的语言、直接摆到决策依据里的做法。

**"never be called multiple times in parallel"这条禁令，在system prompt里说了一遍，源码里`after_model`又用代码强制了一遍**——这是"双保险"设计：提示词层面告诉模型规则是什么，代码层面兜底防止模型没遵守规则时造成实际问题（并行写入导致状态歧义）。

## 值得记的点

- **"3步阈值"是这次真正查到源码原文的确切出处**，跟之前引用的Claude Code`TodoWrite`"三个以上不同动作"几乎一字不差地对应，两家独立收敛到同一个数字这件事因此更值得记——不太可能是巧合，更可能是"3步"这个粒度在实践中被反复验证过是一个合理的分界线。
- **这套机制回答的是"单agent怎么给自己的工作分解步骤"，不是"主agent怎么把任务分给别的agent"**——跟本章其他材料（Anthropic的委派子agent、Claude Code Dynamic Workflows的`agent()`/`pipeline()`分派、Magentic-One的Orchestrator指挥其他agent）是完全不同的一个维度。同一个"任务分解"话题下，"分给谁做"和"自己怎么拆步骤"是两个独立的问题，容易被混为一谈。
- **"写todo本身有成本，用多了浪费token"这条被直接写进提示词**，是这次材料里唯一一处把"要不要分解"这个决策的**代价（不只是收益）**明确讲给模型听的地方——Anthropic的复杂度规则、Claude Code的size guideline都在讲"该配多少资源"，但没有哪家像这里一样直接说"这个分解动作本身是要花钱的，别滥用"。
- **代码级强制（禁止并行调用）+提示词级约束，两者叠加**，是这次翻源码才发现的、比只读文档更完整的图景——文档页面完全没提这条并行调用检查逻辑。
