# Subagents in the SDK（Claude Agent SDK）

官方文档：[Subagents in the SDK](https://code.claude.com/docs/en/agent-sdk/subagents)

## 1 子agent的三种定义方式

- **编程式（推荐）**：在`query()`的`agents`参数里用`AgentDefinition`对象定义，这是**Claude Agent SDK专属**的机制——开发者写代码时预先注册好，不是运行时现场生成的。
- **文件系统式**：markdown文件放在`.claude/agents/`目录下，这是**日常用Claude Code CLI**（交互式产品）时的主要方式。
- **内置`general-purpose`**：不用定义任何东西，Claude随时可以调用这个内置的通用子agent。

**这三种方式，"谁来触发调用、调用参数谁来填"这件事完全一样**——不管子agent的静态配置（身份/系统提示词/工具/模型）来自代码对象还是markdown文件，实际发起调用的永远是Claude通过`Agent`工具发起的`tool_use`，调用时的`input`参数永远是LLM自己动态填的。原文原话："Claude invokes subagents through the `Agent` tool"。

`AgentDefinition`里有两个跟"提示词"相关、但完全不同的字段，容易搞混：

| 字段 | 内容 | 谁写的 |
|---|---|---|
| `AgentDefinition.prompt` | 子agent的**系统提示词**，定义身份/专长/行为规范 | 开发者预先写死 |
| Agent工具调用的`prompt`参数（不在`AgentDefinition`里，是工具调用本身的input） | 这次具体要办的**任务指令** | 父agent的LLM在调用那一刻动态生成 |

原文："The only content you pass from parent to subagent is the Agent tool's prompt string, so include any file paths, error messages, or decisions the subagent needs directly in that prompt."——**子agent除了fork之外是完全空白的开局，这个动态生成的`prompt`是父子之间唯一的信息通道**，这一点是后面"怎么写prompt"那套规范的根本出发点。

## 2 Agent工具——描述与参数（对照两个来源）

### 2.1 官方文档描述的输入参数

`AgentDefinition`配置表里跟运行时行为直接相关的几个字段：`tools`（工具白名单）、`model`（模型覆盖）、`background`（强制后台运行）、`maxTurns`（最大轮数）。调用层面，官方文档提到的Agent工具input参数包括：`subagent_type`、`prompt`、`run_in_background`（v2.1.198起默认后台，Claude在需要立刻拿到结果时会主动设成`false`）、`name`（v2.1.178起，给队友/子agent起名字，方便`SendMessage`寻址）。

### 2.2 实测数据——这个session自己的Agent工具真实schema

这次额外做了一件事：**直接查看了当前这个Claude Code session自己的`Agent`工具定义**，这是比任何文档都更硬的第一手数据（虽然是这个特定部署环境的版本，不一定跟公开SDK文档完全一致）。

**工具描述文字（模型实际看到的说明，节选）**：

> "Launch a new agent to handle complex, multi-step tasks. Each agent type has specific capabilities and tools available to it."

后面跟着一大段使用规范：什么时候不该调用（"Do not spawn agents unless the user asks"）、`fork`类型的特殊行为（继承调用者完整上下文、模型固定跟随父agent）、并行调用要求（多个Agent调用放在同一条消息里）、以及第3节要展开的"怎么写prompt"部分。

**实测参数表**：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `description` | string | **是** | 3-5个词的任务简述 |
| `prompt` | string | **是** | 要agent执行的具体任务 |
| `subagent_type` | string | 否 | 用哪种专门agent类型来做这次任务 |
| `model` | enum: `sonnet`/`opus`/`haiku`/`fable` | 否 | 覆盖agent定义里默认的模型 |
| `isolation` | enum: `worktree`/`remote` | 否 | `worktree`=用临时git worktree隔离工作；`remote`=远程云环境跑（**永远后台运行**，可用性受限） |

`additionalProperties: false`，这五个是全部声明过的参数。

下方是 claude code中Agent tool的description
```markdown
启动一个新智能体来处理复杂的多步骤任务。每种智能体类型都有其特定的能力和可用工具。

可用的智能体类型列在对话中的 `<system-reminder>` 消息里。

除非用户要求，否则不要生成智能体。每次生成都是冷启动，会重新推导你已经拥有的上下文 —— 在这个计划中这是昂贵的路径。带有 "多个角度"、"彻底" 或几个部分的任务并不是生成请求；用你自己的工具内联处理。只有当用户明确说要使用子智能体，或命名了某个可用的智能体类型时，才使用此工具。

使用 Agent 工具时，指定 `subagent_type` 来选择智能体：`"fork"` 分叉你自己（分叉继承你的完整对话上下文，并且始终在你的模型上运行 —— 模型覆盖会被忽略）；任何其他类型都会启动一个全新的智能体（默认为通用型）。

## 使用说明

- 始终包含一个简短描述，总结该智能体要做什么。
- 当智能体完成时，它的最终报告对用户不可见。要向用户展示结果，你应该向用户发送一条文本消息，附上结果的简明摘要。
- 信任但验证：智能体的摘要描述的是它打算做什么，不一定是它实际做了什么。当智能体编写或编辑代码时，在报告工作完成之前，检查实际的更改。
- 要继续之前生成的智能体，使用 `SendMessage`，将智能体的 ID 或名称作为 `to` 字段 —— 这会以完整上下文恢复它。新的 Agent 调用会启动一个全新的智能体，没有之前运行的记忆（分叉除外），因此提示词必须是自包含的。
- 每种智能体类型的模型、推理努力和工具访问都在其定义中设置（`.claude/agents/*.md` frontmatter，或 SDK agents 选项）；这里的 `model` 参数会覆盖本次调用的定义。
- 明确告诉智能体你期望它写代码还是只做研究（搜索、文件读取、网页获取等），因为全新的智能体不知道用户的意图。
- 如果智能体描述提到应该主动使用它，那么你应该尽力在用户没有首先要求的情况下使用它。
- 如果用户指定希望你 "并行" 运行智能体，你必须发送一条包含多个 Agent 工具使用内容块的消息。例如，如果你需要同时启动一个 build-validator 智能体和另一个智能体，发送一条包含两个工具调用的消息。
- 使用 `isolation: "worktree"` 时，如果智能体没有进行任何更改，worktree 会自动清理；否则路径和分支会在结果中返回。

## 何时分叉

当中间输出不值得保留在你的上下文中时，分叉你自己（传入 `subagent_type: "fork"`）。判断标准是定性的 ——"我以后还会需要这个输出吗"—— 而不是任务大小。分叉开放性问题。如果研究可以分解为独立的问题，在一条消息中启动并行分叉。分叉在这方面优于全新的子智能体 —— 它继承了上下文。

分叉很便宜，因为它们共享你的提示词缓存。

**不要偷看。** 工具结果包含一个 `output_file` 路径 —— 不要读取它，那是一个完成通知；信任它。在运行中读取转录会把分叉的工具噪音拉入你的上下文，这就违背了分叉的目的。

**不要竞速。** 启动后，你对分叉发现了什么一无所知。永远不要以任何格式编造或预测分叉结果 —— 不是散文、摘要，也不是结构化输出。通知以用户角色消息到达，永远不是你自己写的东西。如果用户在通知到达之前提出后续问题，告诉他们分叉仍在运行 —— 给出状态，而不是猜测。

**编写分叉提示词。** 由于分叉继承了你的上下文，提示词是一个指令 —— 做什么，而不是情况是什么。明确范围：什么在内，什么在外，另一个智能体在处理什么。不要重复。

## 编写提示词

除分叉之外的任何智能体都从零上下文开始。像对待刚走进房间的同事一样向它简报 —— 它没有看过这段对话，不知道你尝试过什么，不理解为什么这个任务很重要。

- 解释你想要完成什么以及为什么。
- 描述你已经了解或排除了什么。
- 给出足够的关于周围问题的上下文，以便智能体可以做出判断，而不仅仅是遵循狭隘的指令。
- 如果你需要简短的回复，就说明（"用 200 字以内报告"）。
- 查找：交出确切的命令。调查：交出问题 —— 当前提错误时，规定的步骤会成为负担。

对于全新的智能体，简洁的命令式提示词会产生肤浅、通用的工作。

**永远不要委派理解。** 不要写 "根据你的发现，修复 bug" 或 "根据研究，实现它"。这些短语把综合推给了智能体，而不是你自己做。编写包含文件路径、行号、具体要更改什么的提示词。

## 示例用法：

<example>
user: "What's left on this branch before we can ship?"
assistant: <thinking>Forking this — it's a survey question. I we git output in my context.</thinking>
Agent({
  subagent_type: "fork",
  name: "ship-audit",
  description: "Branch ship-readiness audit",
  prompt: "Audit what's left before this branch can ship. Check: uncommitted changes, commits ahead of main, whether tests exist, whether the GrowthBook
gate is wired up, whether CI-relevant files changed. Report a png. Under 200 words."
})
assistant: Ship-readiness audit running.
<commentary>
Turn ends here. The coordinator knows nothing about the findingEPARATE turn — the notification arrives from outside, as auser-role message. It is not something the coordinator writes.
</commentary>
[later turn — notification arrives as user message]
assistant: Audit's back. Three blockers: no tests for the new pe wired but not in build_flags.yaml, and one uncommitted file.
</example>

<example>
user: "so is the gate wired up or not"
<commentary>
User asks mid-wait. The audit fork was launched to answer exacturned. The coordinator does not have this answer. Give status,not a fabricated result.
</commentary>
assistant: Still waiting on the audit — that's one of the things it's checking. Should land shortly.
</example>

<example>
user: "Can you get a second opinion on whether this migration is safe?"
assistant: <thinking>I'll ask the code-reviewer agent — it won'an give an independent read.</thinking>
<commentary>
A non-fork subagent_type is specified, so the agent starts fresn the prompt. The briefing explains what to assess and why.
</commentary>
Agent({
  name: "migration-review",
  description: "Independent migration review",
  subagent_type: "code-reviewer",
  prompt: "Review migration 0042_user_schema.sql for safety. CoNULL column to a 50M-row table. Existing rows get a backfilldefault. I want a second opinion on whether the backfill approach is safe under concurrent writes — I've checked locking behavior but want independent verification. Report: is this safe, and if not, what specifical
})
</example>
```
**跟官方文档对照，几处不一致**：

1. 官方文档的`run_in_background`参数，**这份schema里没有**，后台/前台的控制方式换成了`isolation: "remote"`自带"永远后台"的语义，两边机制不一样。
2. 官方文档`model`接受`'inherit'`，**这份schema没有`inherit`**，多了一个`fable`。
3. **`name`参数**——官方Agent Teams文档明确写了"Claude launches a teammate when it calls the Agent tool with a `name`"（v2.1.178/v2.1.206起），是真实存在、有版本号的官方参数；但description文字末尾的示例代码虽然用了`name: "ship-audit"`，**这份schema的`properties`里确认没有声明`name`这个字段**（`additionalProperties: false`，只声明了上面那五个）。

**这三处不一致的真正原因，其实很简单——这次一开始想复杂了**：`code.claude.com/docs/en/agent-sdk/subagents`这篇讲的是**Claude Agent SDK**，跟当前这个session跑的**Claude Code**，是Anthropic并列的两个官方产品，不是同一个产品的两份文档：

- **Claude Code**：官方已经开发好、可以直接用的智能体产品（这个session本身跑的就是它）。
- **Claude Agent SDK**：官方提供的**软件开发包**，给开发者用来**自己搭建**一个定制智能体——`AgentDefinition`、`agents`参数这些，都是SDK暴露给开发者的通用配置接口。

`agent-loop`那篇文档里其实已经有过线索："Both the TypeScript and Python SDKs bundle a native Claude Code binary"——**SDK是把Claude Code这套执行引擎包起来，再对外暴露一套自己的、更通用/可配置的接口**；Claude Code自己的Agent工具（`fork`这个subagent类型、`isolation:worktree/remote`这些）是这个成品产品自己的设计决策，本来就不需要跟SDK暴露出去的接口长一样。**这三处参数不一致（`run_in_background`、`model`枚举值、`name`），不是"哪个写错了"，就是两个并列产品各自的正常差异**，不需要用"内部环境""历史模板分叉"这类复杂假设去解释。

## 3 怎么给子agent写prompt——五条具体建议

**核心比喻，原文**："Brief the agent like a smart colleague who just walked into the room — it hasn't seen this conversation, doesn't know what you've tried, doesn't understand why this task matters."——子agent很聪明，但零背景，所以prompt不能写得又短又干（那是对熟悉背景的自己人说话的方式），但也不用当傻子写，给够背景信息，它自己能做判断。

原文列的五条：

**① 说清楚"要做什么"和"为什么"**（"Explain what you're trying to accomplish and why"）——不只是任务本身，还要交代目的。反例："修复这个bug"；好写法："这个bug导致用户在XX场景下登录失败，我们要保证修完之后不影响其他登录路径"。有了"为什么"，子agent遇到边界情况时能自己判断"这样改符不符合目的"，而不是死抠字面指令。

**② 说清楚"你已经排除了什么"**（"Describe what you've already learned or ruled out"）——避免子agent把已经走过的弯路再走一遍，浪费token。比如已经确认不是网络问题，就得写进prompt，不然子agent大概率从头开始怀疑网络。

**③ 给够背景，让它能"做判断"而不是"照抄步骤"**（"Give enough context about the surrounding problem that the agent can make judgment calls rather than just following a narrow instruction"）——目的不是让它省事，是让它在**你预设的前提是错的**这种情况下，有能力自己调整方向，而不是死板执行一条已经不成立的指令。

**④ 需要短答案就明说**（"If you need a short response, say so"）——比如"report in under 200 words"，直接约束输出格式和长度，不给就默认会写一份完整报告。

**⑤ 区分"查找型任务"和"探索型任务"，写法完全不同**——原文："Lookups: hand over the exact command. Investigations: hand over the question — prescribed steps become dead weight when the premise is wrong."
- **查找型（Lookups）**：已经知道怎么查，只是要子agent替你跑一遍——直接把具体命令交给它（"运行`grep -rn xxx`"）。
- **探索型（Investigations）**：自己都不确定该怎么查——这时候应该交给它的是**问题本身**，不是猜的步骤。如果前提假设是错的，一份写死的步骤清单会变成"死重"——子agent会机械地照着错误步骤走下去，不会主动质疑"这个前提本身是不是有问题"；反过来只给问题，它至少有空间自己判断"这条路走不通，换个方向"。

**最重要的一条，原文加粗单独强调："Never delegate understanding"**

反例原文直接给了两句典型的坏prompt："based on your findings, fix the bug"、"based on the research, implement it."——这两句话看起来是在委派任务，但实际上把"理解问题、想清楚该怎么改"这件事本身也一起丢给了子agent，**父agent自己没有先想明白**。

好的prompt应该"证明你自己已经想清楚了"——具体做法是**带上文件路径、行号、要改成什么样**，而不是让子agent自己去发现问题在哪、该怎么改。

**这条规则是"先想清楚再委派"原则的具体落地**，跟Anthropic那篇多agent研究系统博客里"lead agent用扩展思维先规划、再决定分配几个子agent"是同一个逻辑的延伸——**"理解"和"判断该怎么做"这件事，应该在委派动作发生之前就由发起调用的那一方完成，而不是随着委派动作一起甩给下游**。子agent该接的是一份"已经消化过的、带着具体坐标的任务书"，不是一份"发起者自己都没想明白、指望它替你想明白"的模糊需求。
