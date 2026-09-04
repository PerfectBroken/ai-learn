# Run agents in parallel（Claude Code）

官方文档：[Run agents in parallel](https://code.claude.com/docs/en/agents.md)（67行，`.md`源，全文精读）

**范围说明**：这篇是Claude Code"多agent并行方式怎么选"的总览页，四种方式（subagents/agent view/agent teams/dynamic workflows）逐一列出。其中"Choose an approach"一节的三问框架，之前在`Dynamic Workflows（Claude Code）学习笔记.md`§6已经摘录过，这次是把整篇补全，包括之前没读的部分：四种方式的对比表、三个"辅助工具但本身不是运行方式"的功能、两个"看起来像并行但其实是另一回事"的功能、"怎么查看运行中的任务"这几节。

## 1 四种并行方式——一张对比表

原文一句话点题："The right one depends on whether you want to stay in each conversation yourself, hand tasks off and check back later, or have Claude coordinate a group of workers for you."——选哪种，取决于你想不想亲自守着每个对话、还是想甩出去过会儿再看、还是想让Claude替你管一群worker。

| 方式 | 给你的能力 | 什么时候用 |
|---|---|---|
| **Subagents** | 同一个session里派生的worker，在自己的上下文里做一个side task，回来只交一份摘要 | 一个side task会把大量搜索结果/日志/文件内容灌进主对话，而这些东西你之后不会再用到 |
| **Agent view**（研究预览版） | 用`claude agents`打开的一屏，集中派发和监控跑在后台的session | 有几个互相独立的任务，想甩出去、扫一眼状态、只在真正需要你时才介入 |
| **Agent teams**（实验性，默认关闭） | 多个协调好的session，共享一份任务列表，能互相发消息，由一个lead管理 | 想让Claude把一个项目拆成几块、分配下去、让几个worker保持同步 |
| **Dynamic workflows** | 一段脚本跑很多subagent、互相交叉核对结果，适合大到一轮对话协调不过来、或者需要不止一遍校验的工作 | 任务规模超出几个subagent能扛的量，或者想让发现互相验证：全代码库审计、500个文件的迁移、交叉核对的调研、从几个角度起草再比较的方案 |

**一句话背景说明**：这四种方式里，干活的都是Claude session本身；想接入别的工具，得通过[MCP server](/docs/en/mcp)把它暴露给Claude，不是这四种方式自己的能力范围。

## 2 三个"辅助但不是独立运行方式"的功能

原文明确把这三个跟上面四种并列的方式区分开——"support this work without being a way to run agents themselves"：

- **Worktrees**——给每个session一份独立的git checkout，让并行的session不会同时改同一批文件。自己起的session可以各用一个；agent view派发出去的session会**自动**挪进独立worktree；派生的subagent也可以各拿一个。
- **Cross-session messaging**——让Claude能列出、给你其他的Claude Code session发消息（同一台机器上的、另一台机器上的、或者Claude Code网页版上的），让你自己起的那些session之间能互相传递发现和状态。
- **`/batch`**——一个skill，让Claude把一次大改动拆成5到30个worktree隔离的subagent，每个各自开一个PR。原文特别点明这**不是一种独立的协调方式**，只是"subagent+worktree"这套已有能力的一次打包封装。

## 3 两个"看起来像并行但解决的是另一个问题"的功能

原文标题就是"A few other features run Claude without you driving each step, but they solve a different problem than splitting work across agents"——运行时不需要你逐步驱动，但解决的不是"怎么把工作拆给多个agent"这个问题：

- **后台bash命令**——只是跑一条shell命令、不阻塞对话，**不会**派生出一个agent。
- **forked subagent**——继承你完整对话上下文的一种特殊subagent，不是重新起一份上下文。原文强调"It's a way to spawn a subagent, not a separate surface"——它只是派生subagent的**一种方式**，不是一个独立的运行面。用`/subtask`启动；开启fork mode时Claude自己也会派生它；想把整个session复制成一个新的后台session（并行运行、不是替代），用`/fork`。（关掉agent view时，命令名字会反过来：`/fork`变成派生forked subagent的命令，`/subtask`不可用——版本/开关状态会影响命令名字对应的具体行为，这一点容易搞混）。
- **Routine**——按计划在云端跑一个session，不是在你本机并行跑，是完全不同的执行位置。

## 4 Choose an approach——三问决策框架（之前摘录过，这次是完整上下文）

原文：三个问题——谁负责协调工作、worker之间需不需要互相说话、任务会不会碰到同一批文件。

**"谁协调"这一条，四种方式对应四种不同的协调主体**：

- Claude在一次对话里委派、收结果 → subagents
- 你自己交接独立任务、之后再回来看 → agent view
- Claude规划、分配、监督一组worker → agent teams（实验性，默认关闭）
- **脚本掌握plan，不是Claude逐轮判断** → dynamic workflows

**"要不要互相说话"这一条，比之前摘录的版本多了一句**：原文完整版提到，你自己起的session之间（包括从agent view派发出去的）能靠cross-session messaging传消息；subagent只向派生它的对话汇报；agent view的session只向你汇报；agent team的teammate之间能直接互发消息，而且**有Task工具时**还共享一份任务列表——这个"有Task工具时"的限定词，是完整版才有的细节，之前摘录时被省略了。

**"会不会碰同一批文件"**：用worktree隔离。subagent和你自己起的session都能各用一个；agent team**不**隔离teammate的worktree，所以要自己划分好每个teammate负责的文件范围。

## 5 怎么查看运行中的任务——四条命令对应四种方式

| 方式 | 查看命令 |
|---|---|
| 后台session（agent view派发的） | `claude agents`——一屏看到每个session、状态、哪些需要你处理 |
| 当前session里的subagent | 命名过的后台subagent会出现在@-提及的自动补全列表里，带状态。v2.1.198起`/agents`不再打开面板，只打印一条指向subagent文件位置的提示——**注意`/agents`和`claude agents`是两个不同的命令**，虽然名字很像 |
| 当前session后台运行的任何东西 | `/tasks`列出每一项，能查看、接入、或停止；这个列表也包括已经跑完的subagent |
| Dynamic workflows | `/workflows`列出运行中和已完成的run、每个处在哪个phase、有多少agent跑完了 |

（desktop app里还有一个统一查看所有session的界面，原文链接到[desktop#work-in-parallel-with-sessions](/docs/en/desktop#work-in-parallel-with-sessions)，这次没有展开读。）

## 值得记的点

- **"`/agents`跟`claude agents`是两个不同命令"、"关闭agent view后`/fork`和`/subtask`的职责会互换"**——这两条都是容易被文档使用者搞混的具体细节，原文专门用一句话点出来提醒，属于"读文档时最容易漏掉、但真正用起来最容易踩坑"的那类信息。
- **`/batch`被明确排除在"独立协调方式"之外**——即便它看起来像是第五种并行方式，官方原文强调它只是subagent+worktree的一次打包封装，不是新的协调范式；这跟forked subagent"不是独立运行面，只是派生subagent的一种方式"是同一种"看起来像新东西、其实是已有机制的封装/变体"的表述模式。
- 这篇文档整体是一篇"决策导航页"，没有深入任何一种方式的具体机制——四种方式各自的详细设计，分别在`sub-agents`/`agent-view`/`agent-teams`/`workflows`各自的专门文档里，这篇的价值在于把"选哪个"这个决策本身讲清楚，跟本章"任务分解策略"的关系主要体现在"谁协调工作"这一条对应的正是"分解出来的任务派给谁执行、由谁决定怎么派"这个问题。
