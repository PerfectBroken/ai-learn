# 环境变量参考（Claude Code）

官方文档：[Environment variables](https://code.claude.com/docs/en/env-vars)（`.md`源，全文513行，逐条核对了所有带`timeout`/`idle`/`background`/`stall`字样的变量）

**范围说明**：纯变量清单，条目式。这次逐条核对后确认真正subagent专属、跟终止条件相关的只有三条——`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`、`CLAUDE_AUTO_BACKGROUND_TASKS`、`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`。全文另有二十多个带timeout字样的变量（`API_TIMEOUT_MS`/`BASH_*_TIMEOUT_MS`/`MCP_TOOL_TIMEOUT`/`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`/`API_FORCE_IDLE_TIMEOUT`/`CLAUDE_STREAM_IDLE_TIMEOUT_MS`/各种hook和插件安装超时等），逐一核对后确认全部是**网络连接层/单次工具调用层/插件安装层**的通用超时，不是"subagent这次运行整体"的超时，排除。`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`/`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`已经在`MultiAgentOrchestration.md`学过，不重复。

## 1 `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`——失速检测，不是总时长超时

原文：

> Stall timeout in milliseconds for background subagents. Default `600000` (10 minutes). The timer resets on each streaming progress event; if no progress arrives within the window, the subagent is aborted and the task is marked failed, surfacing any partial result to the parent

翻译：**只对后台subagent生效**，默认600000ms（10分钟）。计时器随**每一次流式进度事件**重置——不是"从subagent开始跑算起10分钟就砍掉"，而是"连续10分钟没有任何新进展就砍掉"。窗口内没有新进度，subagent被abort，任务标记失败，**把已有的部分结果连同错误一起交给父agent**。

**这条要跟"总时长超时"（比如OpenAI的`max_turns`）分开理解**：`max_turns`管的是"跑了多少轮"，`STALL_TIMEOUT`管的是"卡住不动多久"——一个跑了100轮但每轮都很快、总耗时不长的subagent不会触发失速检测；一个只跑了2轮但第2轮的工具调用挂住不返回、卡了11分钟的subagent会被失速检测掐掉，跟它总共跑了几轮无关。

## 2 `CLAUDE_AUTO_BACKGROUND_TASKS`——强制自动后台化

原文：

> Set to `1` to force-enable automatic backgrounding of long-running agent tasks. When enabled, subagents are moved to the background after running for approximately two minutes. Also enables automatic backgrounding of long MCP tool calls in non-interactive mode on Claude Code v2.1.212 or later

翻译：设为`1`可以强制开启"长时间运行的agent任务自动转后台"。开启后，subagent跑了大约2分钟还没结束，会被自动挪到后台去跑（不是终止，是切换运行模式）。v2.1.212起，非交互模式下运行时间过长的MCP工具调用也会被自动后台化。

**这条不是"终止"机制，是"要不要终止"这个判断之前的一个前置转换**——只有subagent在后台跑，`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`这条失速检测才会生效（第1节原文明确写的是"for background subagents"）。如果一个subagent一直在前台跑（阻塞主对话），失速检测这条规则管不到它。

## 3 `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`——一键关掉整套后台机制

原文：

> Set to `1` to disable all background task functionality, including the `run_in_background` parameter on Bash and subagent tools, auto-backgrounding, and the Ctrl+B shortcut

翻译：设为`1`会禁用**所有**后台任务功能——包括`Bash`和subagent工具上的`run_in_background`参数、自动后台化、以及`Ctrl+B`这个手动转后台的快捷键。

**这条是理解上面两条的前提开关**：一旦设了这个，subagent只能在前台跑，`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`（只管后台subagent）和`CLAUDE_AUTO_BACKGROUND_TASKS`（把subagent转后台）这两条都失去了作用对象——三条变量放在一起看，是一套"要不要允许后台运行→多久自动转后台→后台跑的subagent失速多久算卡死"的完整链条，不是三个孤立的开关。

## 值得记的点

- **"失速"和"总时长超时"是两个不同的维度，Claude Code这边用专属变量把它们分开了**——上一篇OpenAI笔记里只有`max_turns`这一种"总轮次超限"，没有对应"卡住不动"的检测机制（`ModelTimeoutError`管的是单次模型调用超时，颗粒度更细，也不是"整个subagent失速"这个层面）。Claude Code在"subagent整体失速多久算卡死"这个问题上，是目前几家里查到的唯一一个给出专属机制的。
- **三条变量是一套前后依赖的链条，不是各自独立的开关**——`DISABLE_BACKGROUND_TASKS`决定后台模式存不存在，`AUTO_BACKGROUND_TASKS`决定subagent多久自动转后台，`ASYNC_AGENT_STALL_TIMEOUT_MS`决定转后台之后卡多久算失速——理解这三条时要按依赖顺序看，不能孤立记忆。
- 翻查全文511行，另外发现一个可能跟本章主题相关但**范围有歧义**的变量——`CLAUDE_CODE_TEAM_TEARDOWN_PARK_TIMEOUT_MS`（非交互session退出时等agent team拆卸完成的超时，默认10秒）。这条管的是**Agent Teams**（对等协作的teammate）而不是"subagent当工具"，跟本章目前学的机制不是同一套；`MultiAgentOrchestration.md`把Agent Teams当成跟Subagent当工具平级的独立模式处理，这条变量该不该收进本章，需要跟用户确认范围，这里先不收录。
