# Interrupts（LangGraph）

官方文档：[Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)（全文981行，`.md`源）

**范围说明**：全篇981行大部分是HITL（human-in-the-loop）业务模式的详细代码示例（审批/拒绝、审阅并编辑状态、在工具里挂interrupt、校验人类输入），这些是"怎么用interrupt设计审批流程"的应用层内容，不是"暂停恢复机制本身怎么运作"，只简要提一句、不整篇译。正文精读三块：核心机制（Pause/Resume）、Rules of interrupts（几条容易踩的坑，直接决定了resume之后代码怎么跑）、subgraph场景（LangGraph里最接近"子agent"的概念，pause/resume在嵌套场景下具体怎么表现）。

**范围扩展说明（第4-5节）**：只读这一篇文档得出"LangGraph没有超时/取消机制"是不准确的——那只是`interrupt()`这一个具体原语的行为，不代表LangGraph核心库和搭在它上面的官方SDK整体没有这类机制。第4-5节补充了`langgraph`核心库的`recursion_limit`/`GraphRecursionError`（源码`errors.py`/`pregel/main.py`/`_internal/_config.py`）和DeepAgents官方SDK的subagent系统（官方文档`openwiki/concepts/subagents-skills.md` + 源码`middleware/subagents.py`/`middleware/async_subagents.py`），这两块内容来源已经超出`interrupts.md`这一篇文档本身，文件名保留是因为翻译工作是从这篇文档起步的。

## 1 核心机制——`interrupt()`暂停，`Command(resume=...)`恢复

在node函数里调用`interrupt(payload)`（payload必须是JSON可序列化的），会发生五件事：

1. **执行在调用`interrupt()`的确切位置被挂起**
2. **状态被checkpointer存下来**，之后可以恢复（生产环境要用持久化的checkpointer，比如接数据库）
3. **payload值被返回给调用方**——用事件流（`stream_events(..., version="v3")`）时出现在`stream.interrupts`；用默认的`invoke()`时出现在`result["__interrupt__"]`
4. **图无限期等待**，直到你用一个响应恢复执行（原文原话："waits indefinitely until you resume execution with a response"）
5. **恢复时响应被传回node**，成为`interrupt()`调用本身的返回值

恢复靠`Command(resume=<value>)`重新调用图，这个值会变成node内部`interrupt()`调用的返回值。**必须用触发interrupt时同一个`thread_id`**——`thread_id`是"持久化游标"，配的是`config={"configurable": {"thread_id": ...}}`；换一个新值等于开一条全新的、状态为空的线程。

## 2 Rules of interrupts——恢复时到底重新跑了什么

`interrupt()`的实现方式是**抛出一个特殊异常**来挂起执行，这个异常沿调用栈往上传，被runtime捕获后触发保存状态+等待。**恢复时，runtime重新跑整个node，从头开始**——不是从调用`interrupt()`那一行继续，这意味着interrupt之前跑过的代码会**再跑一遍**。三条直接从这个机制推出来的硬规则：

- **不能用裸`try/except`包住`interrupt()`调用**——因为`interrupt()`靠抛异常实现，裸`except`会把这个异常也一起吃掉，导致interrupt根本传不回图。只能用具体的异常类型兜底，或者把`interrupt()`和容易出错的代码分开写。
- **同一个node里多个`interrupt()`调用，顺序不能变**——LangGraph按**任务专属的、严格按索引对齐**的方式管理一份resume值列表：每次恢复都从node开头重新跑，遇到一次`interrupt()`就去这份列表里按顺序取值匹配。所以**不能根据条件跳过某次`interrupt()`调用，也不能用非确定性的循环去调用`interrupt()`**（比如`while True`校验循环、遍历一个运行间可能变化的列表）——这些都会导致重新执行时的调用顺序跟第一次不一致，值和位置对不上。
- **`interrupt()`之前的副作用必须是幂等的**——因为node会重新跑，`interrupt()`之前的任何非幂等操作（比如"创建一条新记录"、"往列表追加一条"）在每次恢复时都会重新执行一次，产生重复记录。推荐做法：用`upsert`这类幂等操作、把副作用放到`interrupt()`之后、或者把有副作用的代码拆到另一个单独的node里。

## 3 Subgraph场景——LangGraph里最接近"子agent"的概念，父子两层都会重新执行

一个node里调用subgraph（`subgraph.invoke(...)`），如果subgraph内部触发了`interrupt()`：**父图会从"调用subgraph"这个node的开头重新执行，subgraph自己也会从它触发`interrupt()`的那个node的开头重新执行**——两层都遵循"整个node重新跑"这条规则，不是只有外层或只有内层。原文示例明确标注了`node_in_parent_graph`里"`some_code()`会在恢复时重新执行"，`node_in_subgraph`里"`some_other_code()`也会重新执行"。

这是LangGraph官方材料里**唯一**明确讨论"嵌套的子执行单元暂停恢复时具体怎么表现"的地方——虽然LangGraph没有"subagent"这个专门概念，subgraph是它架构上最接近的对应物，这条规则直接回答了"子agent暂停恢复，父agent那边要不要也跟着重跑"这个问题：**要，而且是各自独立地从各自的node开头重跑，不是只重跑最内层**。

## 4 更正：`recursion_limit`——LangGraph确实有轮次/步数上限，只是不在这篇文档里

**这是一处需要更正的错误**：上一版笔记说"LangGraph明确没有超时/取消机制"，这个结论只对了一半——`interrupts.md`这篇文档确实没提超时/取消，但那只代表`interrupt()`这一个具体机制没有；**LangGraph的图执行本身另有一套完全独立的、步数层面的强制上限**，只是记在别的地方（`langgraph`核心包的`errors.py`/`pregel/main.py`），不属于"interrupts"这个主题，之前只读了这一篇文档所以漏掉了。直接查了`langchain-ai/langgraph`和`langchain-ai/deepagents`两个仓库的源码：

**`recursion_limit`**——`graph.invoke(input, config={"recursion_limit": N})`，管的是**这次图执行总共能跑多少步**，默认值`DEFAULT_RECURSION_LIMIT = 10007`（`_internal/_config.py`，可以用环境变量`LANGGRAPH_DEFAULT_RECURSION_LIMIT`整体调）。超过这个步数、图还没走到停止条件，会抛`GraphRecursionError`（`RecursionError`的子类），官方docstring原话：

> Raised when the graph has exhausted the maximum number of steps. This prevents infinite loops. To increase the maximum number of steps, run your graph with a config specifying a higher `recursion_limit`.

这就是LangGraph版本的`max_turns`——名字不一样（"步数"不是"轮次"，因为LangGraph按图的node/edge走，一次"步"不一定对应一次模型调用），触发条件是同一类东西：跑太久还没完事，强制掐断防止死循环。

**DeepAgents（跟subagent直接相关的确凿证据）**：`create_deep_agent()`在编译出的图上用`.with_config(recursion_limit=9_999)`，把默认的10007改成一个更大但仍然有限的值，官方说明是"避免长的多步骤运行被LangGraph默认的步数预算切断"——**不是不设上限，是设了一个更宽松的上限**。更关键的是子agent场景：`deepagents/middleware/subagents.py`里工具执行的注释原文——

> The parent's callbacks, tags and configurable reach the subagent automatically... the subagent's bound config still wins collisions (e.g. `lc_agent_name`, `recursion_limit`) and parent metadata propagates (deepagents#3634).

翻译：父agent的配置会自动传给子agent，但**发生冲突时子agent自己绑定的config优先**，`recursion_limit`就是被点名的一个例子——**子agent可以有自己独立的步数上限，跟父agent的不是同一个数字**，这跟OpenAI`as_tool(max_turns=...)`的设计几乎是同一个思路（父子各自独立配置、不共享同一个计数器），底层靠的是LangGraph的`ensure_config`按key合并配置的机制（`langgraph#7926`）。

## 5 DeepAgents的两种subagent模式——同步`task`工具 vs 异步远程subagent，只有后者有真正的取消机制

**这一节内容来自DeepAgents官方文档`openwiki/concepts/subagents-skills.md`**（不是LangGraph核心库，是搭在LangGraph之上的官方SDK），比只看`interrupts.md`一篇文档更接近"子agent"这个概念本身——LangGraph核心库没有"subagent"这个概念，DeepAgents才有。

**同步subagent**（`SubAgentMiddleware`加的`task`工具）：模型调用`task(description, subagent_type)`，**子agent必须跑到完成，返回恰好一份最终报告**，官方原话"Each subagent runs to completion and returns exactly one final report"。这条路径**没有专门的取消/超时机制**，实际受限于第4节讲的`recursion_limit`（子agent可以有自己独立绑定的`recursion_limit`，跟父agent的不共享）——这是纯阻塞式的，跟OpenAI`as_tool()`默认路径、Claude Code同步subagent是同一类设计。

**异步（远程）subagent**（`AsyncSubAgentMiddleware`）：面向长时间运行或远程的工作，**真正非阻塞**——`start_async_task`把任务丢到一个远程Agent Protocol服务器（LangGraph Platform或自建）上跑，立即返回一个`task_id`，主agent可以继续干别的。这套中间件一共暴露**五个工具**：`start_async_task`/`check_async_task`/`update_async_task`/`cancel_async_task`/`list_async_tasks`。

**`cancel_async_task`——这才是LangGraph生态里真正的"主动取消"机制**（源码`middleware/async_subagents.py`）：拿`task_id`找到对应的`thread_id`/`run_id`，调用`client.runs.cancel(thread_id=..., run_id=...)`——直接转发给远程LangGraph Platform SDK的run取消接口，同/异步两个版本都有。取消成功后，本地追踪的`AsyncTask`状态被直接写成`"cancelled"`，工具返回一句"Cancelled async subagent task: {task_id}"确认消息。

**任务的终态词表**（源码`_TERMINAL_STATUSES`常量）：

```python
_TERMINAL_STATUSES = frozenset({"cancelled", "success", "error", "timeout", "interrupted"})
```

**五种终态**，比之前查到的OpenAI（靠一堆不同异常类拼出来）、Claude Code（前台/后台两套规则）都更像一个统一的显式状态枚举——`success`/`error`是正常完成/失败，`cancelled`对应`cancel_async_task`主动取消，`timeout`确认了远程平台侧确实有超时概念（但`start_async_task`这次没看到暴露设超时的参数，具体超时值大概率是LangGraph Platform服务端自己的run级配置，这个中间件只是把服务端返回的状态原样透传，没有本地控制的旋钮，如实标注没查全），`interrupted`对应远程运行中触发了`interrupt()`被暂停（呼应第1-3节讲的暂停恢复机制，只是这次是在远程async任务的语境下）。

## 值得记的点

- **"无限期等待，直到有响应"只是`interrupt()`这一个具体机制的行为，不能代表"LangGraph整体没有轮次上限/取消机制"**——这是这次翻译暴露的一个方法论教训：只读了一篇范围很窄的文档（`interrupts.md`）就下"LangGraph没有X机制"这种全称判断是不严谨的。`recursion_limit`记在完全不同的源码文件里，`cancel_async_task`则要去DeepAgents（搭在LangGraph之上的SDK，不是LangGraph核心库本身）的专属subagent文档里才能找到——只有直接去查核心包和上层SDK的源码，而不是停留在这一篇interrupts文档的搜索结果里，才能拼出完整图景。
- **DeepAgents的"同步task工具 vs 异步远程subagent"，正好复现了OpenAI"同步as_tool() vs 需要on_stream的流式路径"、Claude Code"前台阻塞 vs 后台非阻塞"同一类的架构分野**——凡是"子agent当工具"这个模式，几乎每一家都会分裂成"阻塞等结果"和"扔出去自己接着干"两条路，而**取消/主动终止这类控制能力，几乎总是只挂在"非阻塞"那条路径上**（同步/阻塞路径靠"反正很快就跑完了、跑不完就撞轮次/步数上限"来兜底，本身不需要专门的取消API）。这是这几章比较下来一个相当一致的规律。
- **`recursion_limit`跟`interrupt()`是两套独立的机制，管的是完全不同的东西**：`recursion_limit`限制的是"图总共能走多少步"，是防止死循环的硬上限；`interrupt()`管的是"要不要主动暂停等外部输入"，是一个可选的、由业务逻辑决定要不要用的原语。两者不冲突——一个跑了很多轮`interrupt`/`resume`的图，图本身走的"步数"也会跟着累积，理论上也可能撞到`recursion_limit`。
- **DeepAgents子agent的`recursion_limit`独立配置**，是这次唯一直接跟"subagent"概念挂钩的确凿证据，跟OpenAI`as_tool(max_turns=...)`是同一类设计（父子各自独立的步数/轮次上限），值得在对比表里补一条。
- **"整个node重跑"这条规则，是理解LangGraph pause/resume跟其他几家差异的关键**——OpenAI的`RunState`/Claude Code的resume都是"从暂停的地方继续，不重新执行已经做过的部分"，LangGraph是唯一一家"恢复=重新跑整个node"的，这也是为什么官方要专门写一整节"Rules of interrupts"来约束副作用和调用顺序——这套心智模型（用异常挂起+重跑node）跟另外两家（保存/恢复一份精确的执行位置快照）是两种根本不同的实现思路。
- Subgraph场景的"两层都重跑"发现，是这次翻译里最直接跟"子agent"概念挂钩的一条，值得跟OpenAI `as_tool()`的嵌套审批恢复机制（`SubagentTermination.md` §2.4里还留着的那条待查项）放在一起对比。
