# Exceptions参考（OpenAI Agents SDK）

官方文档：[Exceptions](https://openai.github.io/openai-agents-python/ref/exceptions/)（mkdocstrings从源码docstring自动渲染，直接读源码`src/agents/exceptions.py`更准确）

**范围说明**：源码里前一大段（`_discard_exception_graph`等）是内部的异常数据脱敏/跨边界安全机制（防止敏感payload泄漏出异常对象），是通用安全机制不是subagent终止条件，跳过不译。正文只保留会指向"子agent运行终止"这件事本身的部分：`RunErrorDetails`（失败时收集到的运行快照）、`MaxTurnsExceeded`、`ModelTimeoutError`、`ModelBehaviorError`、`ModelRefusalError`、`ToolTimeoutError`、`MCPToolCancellationError`。`UserError`（开发者自己代码写错，不是运行时终止）和四个Guardrail Tripwire异常（内容审核类，不是终止条件）只提一句，不展开。

## 1 `RunErrorDetails`——run失败时，到底能拿到多少"已经跑完的部分"

所有`AgentsException`（SDK异常的公共基类）实例都带一个`run_data: RunErrorDetails | None`属性——**只要是这个家族的异常，理论上都可以携带一份运行快照**。`RunErrorDetails`是一个dataclass，字段：

```python
@dataclass
class RunErrorDetails:
    input: str | list[TResponseInputItem]
    new_items: list[RunItem]
    raw_responses: list[ModelResponse]
    last_agent: Agent[Any]
    context_wrapper: RunContextWrapper[Any]
    input_guardrail_results: list[InputGuardrailResult]
    output_guardrail_results: list[OutputGuardrailResult]
    tool_input_guardrail_results: list[ToolInputGuardrailResult] = field(default_factory=list)
    tool_output_guardrail_results: list[ToolOutputGuardrailResult] = field(default_factory=list)
```

这是"正常完成判定"的反面——run**没能**正常完成时，你手上有的东西：原始input、失败前已经产出的所有item（`new_items`）、所有已经拿到的模型响应（`raw_responses`）、失败时正跑在哪个agent（`last_agent`，异常发生前可能已经经历过handoff）、以及各层guardrail已经跑完的结果。跟上一篇笔记里`as_tool()`的`failure_error_function`连起来看：子agent嵌套run失败时抛出的异常带着这份`run_data`，理论上写自定义`failure_error_function`时可以从`error.run_data`里取出`new_items`/`last_agent`，把"失败前子agent已经做到哪一步了"这个信息也喂给父agent，而不是只喂一句"出错了"。

## 2 跟终止条件直接相关的异常类，逐个过一遍

| 异常 | 携带的字段 | 触发条件（源码docstring原文+翻译） |
|---|---|---|
| `AgentsException` | `run_data: RunErrorDetails \| None` | 基类，"Base class for all exceptions in the Agents SDK." |
| `MaxTurnsExceeded` | `message: str` | "Exception raised when the maximum number of turns is exceeded." |
| `ModelTimeoutError` | `timeout_seconds: float` | "Exception raised when a model-call attempt exceeds its configured timeout."——message自动格式化成`"Model call timed out after {timeout_seconds:g} seconds."` |
| `ModelBehaviorError` | `message: str` | "Exception raised when the model does something unexpected, e.g. calling a tool that doesn't exist, or providing malformed JSON." |
| `ModelRefusalError` | `refusal: str`（模型返回的拒答原文） | "Exception raised when the model refuses to produce the requested output."——**这个之前一直没查到定义，这次确认了**：它是`ModelBehaviorError`的平级兄弟类，不是"final output判定失败"的子情况，也不是tool_calls的一种；源码里没有任何地方说明它在Loop三分支判定的哪个环节被识别出来，这一点依然没有查到，如实标注不确定 |
| `ToolTimeoutError` | `tool_name: str`、`timeout_seconds: float` | "Exception raised when a function tool invocation exceeds its timeout."——只在`timeout_behavior="raise_exception"`时才会真的抛这个，另一种`timeout_behavior="error_as_result"`不会抛异常（上一篇笔记已经source确认过这两个取值） |
| `MCPToolCancellationError` | `message: str` | "Exception raised when an MCP tool call is internally cancelled."——这是目前查到的、`agents.exceptions`里唯一一个名字直接带"cancellation"的异常，属于"主动取消"这一块，但只覆盖MCP工具调用被取消的情况，不是subagent本身被取消的通用异常（子agent本身被取消对应的是上一篇笔记里`failure_error_function`那条路径，不是靠这个异常） |

**不展开的部分**：`UserError`（开发者用SDK时自己写错代码/配置错误，例如`call_model_input_filter`返回了错误的类型，不是运行时的"终止"）；`InputGuardrailTripwireTriggered`/`OutputGuardrailTripwireTriggered`/`ToolInputGuardrailTripwireTriggered`/`ToolOutputGuardrailTripwireTriggered`——四个都是"guardrail被触发"，属于内容审核/合规类异常，检查的是输入消息、最终回复、工具输入、工具输出，都不算"子agent运行终止条件"这个主题下的机制。

## 值得记的点

- **`RunErrorDetails`是这次最有价值的发现**——它把"failure"这件事的粒度从"抛了个异常"细化到"给你一份完整的失败现场快照"，这跟Claude Code的失速看门狗"把部分结果连同错误一起交给父agent"、以及待会要学的OpenClaw"四种终态+status字段"是同一个主题下的不同实现，可以放在一起对比：**运行终止时，系统愿意给调用方保留多少"已经做到哪一步了"的信息**，是这几家在"终止条件"这个主题下都要回答的同一个问题。
- **`ModelRefusalError`定义找到了，但它在Loop里的确切触发位置依然没查到**——不因为找到了类定义就假装问题解决了，这一点保持之前答复用户时的诚实标注。
- **`MCPToolCancellationError`的"取消"范围很窄**——只管MCP工具调用被取消，不是"子agent被取消"的通用异常，学"主动取消"这一块时不要把它当成OpenAI侧"取消子agent"的答案，真正对应的是`as_tool()`那条`failure_error_function`路径（上一篇笔记）。
