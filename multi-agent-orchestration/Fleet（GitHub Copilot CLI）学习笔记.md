# 使用`/fleet`并行运行任务（GitHub Copilot CLI）

官方文档：[Run tasks in parallel with the `/fleet` command](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet)

## 1 是什么

**`/fleet`是一个斜杠命令，专门用来拿一份实现计划、把它拆解成更小的独立任务，交给子agent并行执行。** 这是Copilot CLI层面的产品功能，不是SDK的编程接口——跟前一篇`Custom agents and sub-agent orchestration`（面向开发者写代码调用SDK）不是同一个使用场景，`/fleet`是给CLI交互用户直接用的命令。

## 2 怎么运作

主Copilot agent先分析这次提示词，判断能不能拆解成子任务；如果决定拆，主agent就变成一个**协调者**角色，负责管理整个工作流和子任务之间的依赖关系。

## 3 机制补充：Fleet和"子agent当工具"其实是同一套底层机制

**这一节内容来自第三方逆向实测笔记（`darthmolen/vscode-extension-copilot-cli`仓库的`FINDINGS.md`），不是官方文档，但是基于真实抓包实验得出的，可信度比纯猜测高——标注清楚来源，不当作官方结论。**

这份笔记对着SDK/CLI做了一组对照实验：同样并发3个任务，一组用显式的`task`工具调用触发，一组用`rpc.fleet.start()`（Fleet的SDK层入口）触发，结果两条路径产生的事件结构**完全一致**——同样的`agentId`归因方式（子agent所有事件都带着跟它自己`toolCallId`相同的`agentId`）、同样的`subagent.started`/`subagent.completed`生命周期、同样支持乱序完成。原文结论："Fleet和ad-hoc子agent发出的是同一套归因契约……两者唯一的区别是触发方式（`task`工具 vs `rpc.fleet.start`）和编排器默认选择的agent类型。"

**这说明`/fleet`不是一个独立的"并行引擎"，本质上就是"子agent当工具"这套机制的一层封装**——`/fleet`帮用户省掉了自己手写多个`task`调用的麻烦，编排决策依然是同一个主agent在做，只是触发方式从"模型自己决定调用`task`工具"换成了"一个专门的RPC入口"。这跟`Custom agents and sub-agent orchestration（GitHub Copilot）学习笔记.md`里记录的子agent委托机制（意图匹配→agent选择→隔离执行→事件流→结果整合）是同一条底层链路，不是另起了一套系统。

## 4 三个好处

- **速度**：并行跑子任务，加快完成大型多部分任务的速度——原文举的例子是"给一个新功能创建测试套件"这类天然适合并行化的任务。
- **专业化**：子任务可以指定用特定的模型或自定义agent去做，原文示例——"Use GPT-5.3-Codex..."（指定模型）、"Use @test-writer to create..."（指定自定义agent，这里的`@test-writer`就是前一篇学过的`customAgents`里定义的那种agent）。
- **独立的context window**：每个子agent有自己独立的上下文窗口，能让每个agent专注在自己那一小块任务上。

## 5 什么时候该用

三个场景：**大型/复杂任务**（有多个独立步骤）；**可并行化的工作**（子任务之间没有相互依赖）；**追求最快完成速度的自动化工作流**。

## 6 要考虑的两件事

- **GitHub AI Credits消耗**：每个子agent都要独立跟LLM交互，比单agent处理同一件事会产生更多次LLM交互——用`/fleet`大概率比不用消耗更多credits。
- **任务本身的构成**：`/fleet`最适合能拆成**互相独立**的子任务的工作；**顺序性**任务（后一步依赖前一步结果）用`/fleet`效果不明显，甚至可能没用。

## 7 `/fleet`和Autopilot模式的关系——两个独立功能，可以分开用也可以叠加用

- **Autopilot模式**：让agent自主持续工作，不需要每一步都等用户确认。
- **`/fleet`**：用子agent并行执行任务。

**典型工作流**：Shift+Tab进入plan模式→识别出这份计划里有多个可拆分的元素→选择"Accept plan and build on autopilot + /fleet"这个选项，**把两个功能叠在一起用**——一份计划经过`/fleet`拆解成并行子任务，同时整个过程用Autopilot模式自主推进、不需要逐步确认。

## 值得记的点

- **这篇文档篇幅很短，是这几家里对"多agent并行"讲得最轻量、最产品化的一次**——没有像LangChain那样给出量化的调用次数/token对比表，也没有像Copilot SDK那篇`custom-agents`那样给出详细的事件系统和`excludedTools`这种架构级机制，`/fleet`定位就是一个给终端用户直接用的便捷命令，工程细节都被产品封装掉了。
- **"独立context window"这个好处，跟前一篇`custom-agents`笔记里`defaultAgent.excludedTools`背后的Isolate动机是同一件事**——这次官方直接把"context window隔离"列为`/fleet`的三大好处之一，跟`Multi-agent overview（LangChain）学习笔记.md`里"上下文管理"这个诉求是同一个概念在不同产品层面的复现。
- **"顺序性任务用`/fleet`没有效果"这条警告，直接呼应了`Multi-agent overview（LangChain）学习笔记.md`"多领域场景"里Handoffs因为只能顺序执行而效率低下的结论**——不管是哪一家产品，"能不能并行"这件事本质上取决于任务本身的依赖结构，不是靠换个模式/命令就能绕过去的硬约束。
- **`/fleet` + Autopilot的组合用法，是目前查到的、唯一一个把"自主持续工作"和"任务并行拆解"当成两个可以独立叠加的正交能力来设计的产品**——其他几家的"并行"和"自主推进"通常是绑在同一套机制里讨论的，Copilot CLI这里把它们拆成了两个可以分别开关、组合使用的功能。
