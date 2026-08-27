# Sub-agents终止相关摘录（Claude Code）

官方文档：[Sub-agents](https://code.claude.com/docs/en/sub-agents)（用`.md`后缀取的官方markdown源，比HTML渲染页准确）

**范围说明**：这篇整篇是subagent配置指南（怎么定义、怎么控制工具权限、上下文怎么组装、嵌套/并发限制——嵌套深度和并发上限已经在`MultiAgentOrchestration.md`学过，这里不重复），跟终止条件相关的内容集中在"Run subagents in foreground or background"、"API errors in subagents"、"Resume subagents"三节，只译这几节相关内容。安全相关的"Subagent output scanning"节不属于本章主题（属于Multi-Agent编排章节的安全考虑），跳过。

## 1 正常完成 vs 失败/被停止——UI层面就是两种不同的终态

Claude Code在"subagent面板"（prompt输入框下方那一栏）里，按subagent怎么结束，用两种不同方式清掉它的行：

- **正常完成**：Claude Code**立即**移除这一行，并且（除非在屏幕阅读器模式下）在底部footer显示"`/tasks` to see subagents"提示，持续30秒——这30秒内可以跑`/tasks`、在这个subagent上按`Enter`打开它的transcript。（v2.1.232之前的旧行为：完成后也跟失败一样保留这行30秒，且不显示footer提示。）
- **失败或被你手动停止**：Claude Code把这一行**保留30秒**。想提前清掉，选中它按`x`。

`/tasks`列表里的表现一致：完成的subagent会继续留在列表里（标记为done，排在运行中的任务下方），保留时间跟上面footer提示的窗口一样；它的详情视图在完成后依然打开。**失败或被你停止的subagent会直接离开列表**（不是标记failed后继续显示，是直接消失）。（v2.1.208之前：完成的subagent一结束就立刻离开列表，详情视图也跟着关闭。）

Fork（`/subtask`分叉出来的那种特殊subagent）遵循同一套规则：正常完成immediately移除，失败或被停止保留30秒——跟普通subagent没有区别对待。

## 2 API错误导致的异常终止——前台/后台两种不同的"能拿回多少"

从v2.1.199起，subagent因为API错误（用量限制、过载、连续的服务端错误）而中途结束时，这个失败会**作为失败报告给Claude**，而不是把错误文本原样当成subagent的"研究发现"喂回去。具体拿到什么，看这个subagent是前台还是后台跑的：

- **前台**：如果限流/过载/服务端错误打断了一个**已经产出过文本输出**的subagent，`Agent`工具会把那部分**已产出的输出**连同"subagent被中断、没跑完任务"的提示一起返回；如果subagent什么都没产出（或者只有工具调用、没有文本输出），就直接失败，报`Agent terminated early due to an API error`加错误详情。（v2.1.199版本里，后一种"只有工具调用"的情况会返回一个只带中断提示、不带任何内容的空结果——这是当时的一个过渡期行为。）
- **后台**：subagent被标记为失败，Claude收到的消息里点名是哪种API错误，**并且包含这个subagent最后的输出**，"所以已经做的部分工作不会丢失"（原文明确这句）。

这条跟上一篇OpenAI笔记里`RunErrorDetails`是同一个主题的另一家答案：**运行被强制中断时，系统愿意保留多少"已经做到哪一步"的信息**——Claude Code这边的答案是"前台看有没有文本输出决定给不给部分结果，后台一律给最后输出"，跟OpenAI"异常自带一份`RunErrorDetails`快照"的思路不同，Claude Code是按"前台/后台"这个维度分别定义了两条不同的规则，不是一个统一的对象。

## 3 三种"停止"来源，决定了停下来之后能不能被悄悄恢复——这篇最关键的发现

Claude Code里让一个subagent停下来，有三条不同的路径，而且**停下来之后能不能被自动恢复，取决于是谁下的手**：

| 停止方式 | 触发者 | 停下来之后`SendMessage`能不能自动恢复它 |
|---|---|---|
| `/tasks`面板里选中后按`x` | 你自己（人） | **不能**——`SendMessage`调用会返回一个拒绝，告诉Claude这个agent已经被取消了 |
| SDK的`stop_task`请求 | 你的应用代码 | **不能**——同上，也是拒绝 |
| Claude自己调用`TaskStop`工具 | Claude自己 | **能**——跟"正常完成"的subagent一样，收到`SendMessage`会在后台自动恢复，不需要重新发一次`Agent`调用 |

原文原话（v2.1.191起生效）：

> a subagent you stopped yourself, with `x` in `/tasks` or an SDK `stop_task` request, doesn't auto-resume. The `SendMessage` call returns a refusal telling Claude the agent was cancelled.

**为什么这个区分重要**：Claude自己用`TaskStop`喊停的subagent，被当成"这次先不需要了，但没准以后还要接着用"，所以留了自动恢复的口子；但人类主动伸手停掉的（不管是在UI上按`x`还是在应用代码里调`stop_task`），系统认为这是一个**明确的、不希望被绕过的决定**——Claude不能靠"假装没看见、直接发消息唤醒它"的方式绕开人类的停止指令。

不过人类停掉的subagent不是彻底死掉：只要它那一行还留在subagent面板里（也就是还在上面第1节说的"停止后保留的30秒"窗口内），**你自己**可以直接在它的transcript里输入内容来手动恢复它——这个操作会清掉"已停止"标记，清掉之后后续的`SendMessage`调用才能重新自动恢复它。

## 4 Resume机制的几个细节

- **每次调用subagent都是一个新实例**，不是延续上一次——要接着某个subagent之前的工作，需要显式"resume"它。
- Resume靠的是`SendMessage`工具，把subagent的**agent ID或name**填进`to`字段。`SendMessage`本身不需要开启agent teams（只有`shutdown_request`/`plan_approval_response`这类结构化团队协议消息才需要）。
- **内置的Explore和Plan这两个agent是一次性的**——它们不返回agent ID，所以没法被resume；需要接续工作时得用`general-purpose`或自定义subagent。
- Resume之后，subagent**沿用同一个ID**继续跑，状态会重新显示为"running"——哪怕它resume前的状态是"failed"或"completed"。（v2.1.205之前的旧行为：resume期间任务列表和Agent SDK的task事件里，仍然显示着resume前那个旧状态，容易误导。）
- subagent的transcript独立于主对话持久化：主对话压缩（compaction）不影响它；session持久化让你可以在重启Claude Code、恢复同一个session之后继续resume某个subagent；transcript文件默认30天后按清理策略自动删除（`cleanupPeriodDays`）。transcript文件路径：`~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`。

## 值得记的点

- **"谁下令停止的"决定了"能不能被悄悄恢复"，是这次翻到的最有价值的一条**——Claude Code在"agent自己收手"和"人类下令终止"之间做了明确的权限区分，前者留了自动恢复的后门，后者没有，而且这条规则是显式写进产品行为里的，不是靠提示词约定。
- **前台/后台两种"部分结果保留"策略**，是回答"运行被打断能拿回多少"这个问题的Claude Code式答案，可以跟OpenAI的`RunErrorDetails`（统一对象、任何`AgentsException`都带）放在一起对比：一个是"按运行位置分两条规则"，一个是"所有异常共享一份标准快照结构"。
- Fork遵循跟普通subagent一样的终止UI规则，这点上没有特殊待遇。
