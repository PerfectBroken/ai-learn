# Track todos（Claude Code / Claude Agent SDK）

官方文档：[Track todos](https://code.claude.com/docs/en/agent-sdk/todo-tracking.md)（377行，`.md`源，全文精读）

**范围说明**：这篇讲的是Claude Agent SDK怎么把Claude内部维护的todo列表，以结构化工具调用的形式暴露给调用方的应用代码——是"单个agent自己怎么给自己的工作拆步骤"这条线（跟`TodoListMiddleware（LangChain）学习笔记.md`是同一个问题的Claude版本答案），"Examples"一节的两段代码只摘取关键设计点，不逐行翻译（代码本身是给开发者集成用的样板，不是概念性内容）。

## 1 一个前提：默认根本不需要这套机制

开篇原文：

> On the models listed under Model availability, Claude tracks multi-step work **without** a written todo list, and Claude Code leaves the task-tracking tools out of sessions by default. You don't need anything on this page for Claude to work through multi-step tasks on those models.

翻译：在"Model availability"一节列出的那些模型上，Claude**不用写一份todo列表**就能追踪多步骤工作，Claude Code默认**不会**把任务追踪工具放进session里——在这些模型上，想让Claude处理多步任务，这篇文档讲的东西你完全用不上。

**这句话是这篇文档存在的前提，也是理解下面所有内容的关键**：这套todo工具不是"Claude处理多步任务的必需品"，是一个**可选的、给应用开发者用来观测进度的接口**——只有当你的应用代码需要读取这些结构化工具调用（记日志，或者渲染自己的进度条）时，才有必要专门开启它。

## 2 Model availability——哪些模型默认给、哪些默认不给

原文（Note块）：

> On TypeScript Agent SDK 0.3.233 and later, or Python Agent SDK 0.2.139 and later, the following tools aren't available on Opus 4.8, Sonnet 5, Fable 5, Mythos 5, or later versions of those families unless you opt in: `TodoWrite`、`TaskCreate`、`TaskGet`、`TaskUpdate`、`TaskList`。On other models, Claude Code provides the Task tools by default and `TodoWrite` only when you set `CLAUDE_CODE_ENABLE_TASKS=0`.

翻译：在Opus 4.8、Sonnet 5、Fable 5、Mythos 5这几个模型家族（以及它们之后的版本）上，除非显式开启，否则`TodoWrite`/`TaskCreate`/`TaskGet`/`TaskUpdate`/`TaskList`这几个工具都不可用。**在其他模型上则正好相反**——Task工具默认就给，`TodoWrite`只有在你设了`CLAUDE_CODE_ENABLE_TASKS=0`时才会出现（也就是说旧模型默认拿到的是"Task工具组"，不是`TodoWrite`；只有关掉Task工具组，才会退回到`TodoWrite`这个更早的单一工具）。

**开启方式，三选一**：

1. 在`allowedTools`（TypeScript）/`allowed_tools`（Python）里点名其中一个工具
2. 在`tools`选项里列出这些工具（这会把session的内置工具收窄到列出的这些，要连同其他要用的内置工具一起列）
3. 在`env`里设`CLAUDE_CODE_ENABLE_TODO_TOOLS=1`（这篇文档的示例代码都用这种方式）

## 3 Todo lifecycle——四个状态，谁来推进

原文：

> 1. **Created**: Claude adds the todo as `pending` when it identifies a task
> 2. **Activated**: Claude sets the todo to `in_progress` when it starts the work
> 3. **Completed**: Claude marks it completed when the task finishes successfully
> 4. **Removed**: Claude deletes a todo it no longer needs by setting `status: "deleted"` in a `TaskUpdate` call

翻译：**创建**——Claude识别出一个任务时，把它加成`pending`状态；**激活**——开始干这件事时，改成`in_progress`；**完成**——任务成功结束时标记`completed`；**移除**——Claude判断某个todo不再需要了，通过一次`TaskUpdate`调用把它的`status`设成`"deleted"`来删掉。

**四个状态的推进者始终是Claude自己**，这套lifecycle没有给应用代码任何"直接改状态"的接口——应用代码只能**观察**这些状态变化（通过监听工具调用流），不能反过来干预。

## 4 When Claude creates todos——跟LangChain几乎一致的判断标准

原文：

> * **Complex multi-step tasks** requiring three or more distinct actions
> * **User-provided task lists** when multiple items are mentioned
> * **Longer operations** that benefit from progress tracking
> * **Explicit requests** when users ask for todo organization
>
> Claude may skip todos for very short or single-step requests.

翻译：**复杂多步任务**（需要三个或更多不同的动作）；**用户直接给的任务清单**（提到了多个条目）；**更长的操作**（能从进度追踪里获益）；**用户明确要求**（直接要求做todo组织）。对于非常短或者单步的请求，Claude可能会跳过todo。

这四条标准和阈值数字，跟`To-do List Middleware（LangChain）学习笔记.md`里`WRITE_TODOS_TOOL_DESCRIPTION`的"3步阈值"、"何时该用/何时不该用"几乎是同一套判断逻辑，只是这篇文档没有给出模型侧看到的确切prompt原文（这是给应用开发者看的产品文档，不是给模型看的工具描述）——**两家的措辞不完全一样，但判断标准的实质内容高度一致**。

## 5 Examples——两段代码，只摘关键设计点

原文给了两个递进的例子，第一个只打印任务活动日志，第二个维护一份实时更新的进度展示。两个例子共享同一个技术细节，值得单独记：

**新建任务的ID，不在`TaskCreate`这次工具调用的输入里，要从配对的工具结果里读**。原文：

> The assigned task ID isn't in the `TaskCreate` input. Claude Code delivers each tool's structured output on the user message that carries its `tool_result` block, in the `tool_use_result` field... The tracker pairs each `tool_result` block with its `tool_use` call by `tool_use_id` and reads `task.id` from the paired message's `tool_use_result`.

翻译：`TaskCreate`调用本身的输入参数里没有任务ID——真正分配出来的ID，要等对应的`tool_result`消息回来，从这条消息的`tool_use_result`字段里读（`TaskCreateOutput`是`{ task: { id, subject } }`这个形状）。要把"创建"和"分配到的ID"关联起来，得靠`tool_use_id`把发起调用的`tool_use`块和返回结果的`tool_result`块配对。

**第一个例子（Monitor todo changes）**——只是监听流里的`TaskCreate`/`TaskUpdate`，打印一行`+`（新任务）或一行状态变化，原文特别提醒："The `+` lines don't include the assigned IDs, so this log can't match updates back to their creates."——这个最简单的日志版本，**没法**把某次状态更新对应到具体是哪个任务创建的（因为打印`+`那一刻，真正的ID还没读到）。想要这层关联，就要用第二个例子的做法。

**第二个例子（Display progress in real time）**——多维护了一个`pendingCreates`映射：`TaskCreate`调用发起时先记一份"待确认"的创建信息（用发起调用的`tool_use_id`当key），等对应的`tool_result`真正带着分配到的`task.id`回来后，再正式挪进`tasks`这份状态表——这是为了解决上一段说的"创建时还不知道ID"这个时序问题。**这个设计模式（先按调用ID暂存、结果回来后再按真正的资源ID归档）在处理任何"调用发起和资源分配不是同一时刻"的异步工具接口时都用得上**，不是todo追踪独有的技巧。

**另一个值得记的实现细节——键名修复**，原文：

> Claude Code repairs some close-but-incorrect key names before execution, mapping `id` or `task_id` to `taskId` and `active_form` to `activeForm`, but that repair is not reflected in the stream. Read `TaskUpdate` input fields defensively.

翻译：Claude Code在真正执行工具调用之前，会把一些"写得很接近但不完全对"的键名修正过来（`id`或`task_id`→`taskId`，`active_form`→`activeForm`），**但这个修复过程不会反映在流里**——也就是说你在消息流里看到的原始输入，可能还是模型最初写的那个（不完全规范的）键名。两个示例代码都对此做了防御性处理（`taskId ?? id ?? task_id`这种兜底取值），而不是假设标准键名一定存在。这条细节说明：**模型自己产出的原始工具调用参数，跟"最终真正生效执行的参数"之间可能有一层host侧的静默纠错**，读取时不能想当然认为两者一致。

## 值得记的点

- **"默认不需要这套机制"是这篇文档最重要的前提**——新模型能不写todo也追踪多步工作，这套结构化todo系统的定位从"必需的执行机制"退化成了"给应用层做可观测性用的可选接口"，这个变化跟`Dynamic Workflows（Claude Code）学习笔记.md`§7记的那条趋势是同一件事，这篇文档是那条趋势更详细的技术出处。
- **应用代码只能观察，不能干预todo状态**——四个生命周期状态全部由Claude自己推进，这跟LangChain`TodoListMiddleware`的`write_todos`工具（也是模型自己整份替换列表）是同一个设计取向：todo列表是agent自己管理自己进度的工具，不是外部系统拿来控制agent的接口。
- **"创建时不知道ID，要等结果回来才知道"这个时序细节**，是这篇文档比LangChain那篇更具体的地方——LangChain的`write_todos`是同步返回`Command`直接更新state，没有这层"先发起、再等分配"的异步性；Claude这边引入了这一层，是因为它把"创建"和"更新"拆成了`TaskCreate`/`TaskUpdate`两个独立工具（而不是LangChain那种"一个工具、整份替换"的设计），拆分带来了这层原本不需要处理的时序复杂度。
