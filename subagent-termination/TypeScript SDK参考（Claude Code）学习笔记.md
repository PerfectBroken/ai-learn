# TypeScript SDK参考（Claude Code）

官方文档：[TypeScript SDK reference](https://code.claude.com/docs/en/agent-sdk/typescript)（全文5023行的完整API参考，`.md`源）

**范围说明**：只有`Query`对象的方法列表这一小节相关，摘录即可，不整篇译。`Query`对象上有三个"能让某样东西停下来"的方法——`stopTask(taskId)`、`interrupt()`、`close()`——但只有`stopTask(taskId)`是真正**针对某个具体subagent/后台任务**的，另外两个管的是整个session/主查询本身，不是subagent专属，下面会说明为什么排除。

## 1 `stopTask(taskId)`——精确到某个子任务的停止方法

`Query`接口定义（`interface Query extends AsyncGenerator<SDKMessage, void>`）里：

```typescript
stopTask(taskId: string): Promise<void>;
```

方法表里的说明原文：`Stop a running background task by ID`。这是"主动取消"这块最直接的API级证据——**按`taskId`精确指定要停哪一个**后台任务/subagent，不是笼统地打断整个session。跟上一篇`Sub-agents`笔记里"三种停止来源"对应：这就是那张表里"SDK的`stop_task`请求"这一行的确切API形态，源码层面是`Query`对象上的一个方法，不是什么专门的REST端点或CLI命令。

## 2 顺带确认：`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`的适用范围有了更精确的原文

这篇SDK参考页里，恰好也提到了失速超时这条变量，措辞比`env-vars`那篇更精确了一步：

> `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`: stall watchdog for subagents launched with `run_in_background`. Default `600000`. Resets on each stream event; on stall it aborts the subagent, marks the task failed, and surfaces the error to the parent with any partial result. **Does not apply to synchronous subagents.**

加粗这句是新信息——**明确排除了同步subagent**，不只是笼统说"对后台subagent生效"，而是直接点名"不适用于同步subagent"。这条正好回答了你之前问的"同步的subagent是不是不涉及streaming"那类问题的Claude Code版本：**同步subagent不但不涉及streaming（这是OpenAI那边的结论），在Claude Code这边更进一步——同步subagent连失速看门狗这层保护都没有**，逻辑上也说得通：失速检测靠"流式进度事件"重置计时器，同步调用整个过程只有一次调用和一次返回，中间没有可以拿来重置计时器的流式事件，这套机制天然用不上。

同一处原文还确认了`API_TIMEOUT_MS`"Applies to the main loop and all subagents"——通用超时，不是subagent专属，跟之前的排除判断一致。

## 值得记的点：`interrupt()`/`close()`为什么不算subagent专属，被排除

- **`interrupt()`**——原文："Interrupts the query. Only available in streaming input mode." 这个方法**不接受`taskId`参数**，管的是整个`Query`对象代表的主查询本身（当前session），不是定向到某个具体的subagent。跟`stopTask(taskId)`刻意做了参数上的区分：一个要精确指定目标，一个默认作用于整体，这个设计差异本身就是最好的证据。
- **`close()`**——原文："Close the query and terminate the underlying process. Forcefully ends the query and cleans up all resources." 这是终止**整个底层进程**，比`interrupt()`还要更彻底，同样不是subagent粒度的操作。
- 这两个方法进一步印证了`Streaming.md`那次学到的教训：一份文档里出现的"停止/取消"类API，不能因为出现在同一份"跟subagent相关"的文档里就默认它是subagent专属的，必须看它的参数签名——**有没有一个东西能让你"指定停哪一个"，是判断它是不是subagent粒度机制的关键**。
