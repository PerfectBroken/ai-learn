# Running agents（OpenAI Agents SDK）

官方文档：[Running agents](https://openai.github.io/openai-agents-python/running_agents/)

**范围说明**：官方"Running agents"页面讲的`max_turns`/`error_handlers`/"final output"判定，本质是**任意一次`Runner.run()`调用**的通用循环终止机制，不是专门写给subagent看的——跟`TurnLoop.md` §4.1已经画过的Runner三分支循环图是同一套东西，重复了。但subagent-as-tool（`agent.as_tool()`）内部就是靠这套机制跑的，所以真正"跟subagent终止条件一致"的，是`as_tool()`自己对这套通用机制做的**覆盖/收窄**——这部分官方文档没细讲，是直接读`openai-agents-python`源码（`src/agents/agent.py`）验证出来的。下面只保留这部分。

## 1 `as_tool(max_turns=...)`——子agent自己的轮次上限，跟父agent的相互独立

`as_tool()`签名里有一个独立的`max_turns: int | None = None`参数（`agent.py:594`）。源码里的处理（`agent.py:717`）：

```python
resolved_max_turns = max_turns if max_turns is not None else DEFAULT_MAX_TURNS
```

这个值被传进**专属于这个子agent的嵌套`Runner.run()`调用**，不是父agent那次`Runner.run()`的`max_turns`。也就是说：**父agent和被当工具调用的子agent，各自的轮次上限是独立配置的两个数字，不共享同一个计数器**，默认都是`DEFAULT_MAX_TURNS`（10），可以分别覆盖。

子agent这次嵌套循环内部，判断"正常结束"用的还是原来那条通用规则（"final output"=产出符合期望类型的文本、且没有tool calls），只是现在这条规则管的是子agent自己的这次嵌套run，不是父agent的run。

## 2 `failure_error_function`——子agent嵌套run失败后，怎么喂回父agent

`as_tool()`的另一个参数（`agent.py:599`，默认值`default_tool_error_function`），官方docstring原话：

> If provided, generate an error message when the tool (agent) run fails. The message is sent to the LLM. If None, the exception is raised instead.
>
> 如果提供了这个函数，子agent这次运行失败时会用它生成一条错误消息发给（父agent的）LLM；如果传`None`，则直接把异常抛出来（炸掉父agent的run）。

源码确认这个函数被原样传进了这个工具的`FunctionTool`定义（`agent.py:1025`）。默认的`default_tool_error_function`实现（`tool.py:1863`）很简单：

```python
def default_tool_error_function(ctx: RunContextWrapper[Any], error: Exception) -> str:
    """The default tool error function, which just returns a generic error message."""
    json_decode_error = _extract_tool_argument_json_error(error)
    if json_decode_error is not None:
        return (
            "An error occurred while parsing tool arguments. "
            "Please try again with valid JSON. "
            f"Error: {json_decode_error}"
        )
    return f"An error occurred while running the tool. Please try again. Error: {str(error)}"
```

**这才是真正意义上"子agent终止条件"该关心的机制**：子agent那次嵌套`Runner.run()`不管是撞到自己的`max_turns`上限（抛`MaxTurnsExceeded`）还是别的异常，默认都不会让父agent的run跟着崩——会被`failure_error_function`转成一条错误消息，当作这次工具调用的结果喂给父agent的LLM，父agent自己决定要不要重试/换个方式。跟"Running agents"页面讲的`error_handlers`是两条不同的路：`error_handlers`只能配在顶层`Runner.run()`入口（`as_tool()`的参数列表里没有这个选项），管的是主agent自己的run；`failure_error_function`才是`as_tool()`专属、管子agent这次嵌套run失败之后怎么处理的旋钮。

## 3 一个顺带解开的疑点：`ToolTimeoutError`的`timeout_behavior`到底有几种取值

上一版笔记留了个疑点——`ToolTimeoutError`触发条件里提到`timeout_behavior="raise_exception"`，暗示还有别的取值。这次翻源码顺带确认了（`tool.py:1875`）：

```python
_FUNCTION_TOOL_TIMEOUT_BEHAVIORS: tuple[ToolTimeoutBehavior, ...] = (
    "error_as_result",
    "raise_exception",
)
```

只有两种：`"error_as_result"`（超时当成一个普通的工具结果返回，不抛异常）和`"raise_exception"`（抛`ToolTimeoutError`）。跟上面`failure_error_function`是同一层设计哲学——OpenAI这边"子任务失败了怎么办"，默认倾向于"转成一条消息喂给模型自己处理"，而不是让异常直接往上炸。

## 值得记的点

- **`as_tool()`的`max_turns`和`failure_error_function`，是这次在源码里挖到的、真正意义上"subagent专属"的终止条件旋钮**——官方"Running agents"文档完全没提这两个参数，只有翻`as_tool()`的源码才能看到。这也说明OpenAI官方文档对"子agent终止条件"这个主题本身没有专门写过独立小节，得靠代码反推。
- **`error_as_result`/`raise_exception`这个二选一模式，在OpenAI这边反复出现**（工具超时是这样，子agent运行失败也是这样）——默认都倾向于"转成消息喂给模型"而不是"直接抛异常终止整条链路"，这是OpenAI Agents SDK一个比较一致的设计取向，值得记住，后面看别家（Claude Code/OpenClaw）子agent失败后怎么处理时可以拿来对照。
