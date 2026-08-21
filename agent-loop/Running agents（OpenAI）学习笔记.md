# Running agents（OpenAI Agents SDK）

来源：[OpenAI Agents SDK Docs - Running agents](https://openai.github.io/openai-agents-python/running_agents/)（官方文档，从GitHub仓库`docs/running_agents.md`拉取的原始markdown源码翻译，避免网页版被摘要）

你可以通过[`Runner`]类来运行agent，有3种方式：

1. **`Runner.run()`**——异步方法，返回一个`RunResult`。
2. **`Runner.run_sync()`**——同步方法，底层就是跑`.run()`。
3. **`Runner.run_streamed()`**——异步方法，返回一个`RunResultStreaming`。它用流式模式调用LLM，边收到边把这些事件流给你。

```python
from agents import Agent, Runner

async def main():
    agent = Agent(name="Assistant", instructions="You are a helpful assistant")

    result = await Runner.run(agent, "Write a haiku about recursion in programming.")
    print(result.final_output)
    # Code within the code,
    # Functions calling themselves,
    # Infinite loop's dance
```

更多内容见[results guide](results.md)。

## Runner的生命周期与配置

### Agent循环

调用上面三个`Runner`方法中的任何一个时，你要传入一个起始agent和输入。输入可以是：

- 一个字符串（会被当成一条用户消息）；
- 一个OpenAI Responses API格式的input item列表；
- 或者一个[`RunState`]——用于恢复一次被暂停的运行，或者恢复一次以`cancel(mode="after_turn")`方式停止的运行。这个state还可以携带[恢复运行前预先塞好的输入](results.md#add-input-before-resuming)。

Runner接下来会跑一个循环：

1. 用当前的输入，为当前的agent调用一次LLM。
2. LLM产出输出：
   1. 如果Runner判定LLM的输出是"最终输出"，循环结束，返回结果。
   2. 如果LLM请求了一次handoff（转交），更新当前agent和输入，重新跑一遍循环。
   3. 如果LLM产出了工具调用，执行这些工具调用，把结果追加进去，重新跑一遍循环。
3. 如果超过了传入的`max_turns`，抛出一个[`MaxTurnsExceeded`]异常。传`max_turns=None`可以禁用这个回合数上限。

> **官方笔记**：判断LLM输出是不是"最终输出"的规则是——它产出了符合预期类型的文本输出，**并且没有工具调用**。

### 流式输出

流式输出能让你在LLM运行过程中额外收到流式事件。流跑完之后，`RunResultStreaming`会包含这次运行的完整信息，包括所有新产出的输出。你可以调用`.stream_events()`拿到这些流式事件。更多内容见[streaming guide](streaming.md)。

#### Responses WebSocket传输（可选的辅助工具）

如果你启用了OpenAI Responses的websocket传输，仍然可以照常用普通的`Runner` API。这个websocket session辅助工具推荐用来复用连接，但不是必须的。

这里指的是**Responses API走websocket传输**，不是[Realtime API](realtime/guide.md)。

关于传输方式的选择规则、以及针对具体model对象或自定义provider的注意事项，见[Models](models/index.md#responses-websocket-transport)。

**模式1：不用session辅助工具（能跑通）**——你只是想用websocket传输、不需要SDK帮你管理一个共享的provider/session时用这个。

```python
import asyncio

from agents import Agent, Runner, set_default_openai_responses_transport


async def main():
    set_default_openai_responses_transport("websocket")

    agent = Agent(name="Assistant", instructions="Be concise.")
    result = Runner.run_streamed(agent, "Summarize recursion in one sentence.")

    async for event in result.stream_events():
        if event.type == "raw_response_event":
            continue
        print(event.type)


asyncio.run(main())
```

这种模式适合单次运行。如果反复调用`Runner.run()`/`Runner.run_streamed()`，除非你手动复用同一个`RunConfig`/provider实例，否则每次运行都可能要重新连接。

**模式2：用`responses_websocket_session()`（推荐用于多轮复用）**——当你想在多次运行之间（包括继承同一个`run_config`的、agent当工具用的嵌套调用）共享一个支持websocket的provider和`RunConfig`时用这个。

```python
import asyncio

from agents import Agent, responses_websocket_session


async def main():
    agent = Agent(name="Assistant", instructions="Be concise.")

    async with responses_websocket_session(
        responses_websocket_options={"ping_interval": 20.0, "ping_timeout": 60.0},
    ) as ws:
        first = ws.run_streamed(agent, "Say hello in one short sentence.")
        async for _event in first.stream_events():
            pass

        second = ws.run_streamed(
            agent,
            "Now say goodbye.",
            previous_response_id=first.last_response_id,
        )
        async for _event in second.stream_events():
            pass


asyncio.run(main())
```

要在退出上下文之前把流式结果消费完。如果websocket请求还在进行时就退出上下文，可能会强制关闭共享连接。

这个服务每条websocket连接一次只处理一个response，并且把一条连接的时长限制在60分钟。这个辅助工具会复用连接，但不会解除这些限制。重连之后，`store=False`和ZDR（零数据保留）流程没法恢复一个没被缓存的`previous_response_id`——要么带着完整的输入上下文重新起一条链，要么从你自己本地管理的session状态里重建。完整的恢复行为见[Responses WebSocket transport notes](models/index.md#responses-websocket-transport)。

如果长时间的推理回合触发了websocket的keepalive超时，可以调大`ping_timeout`，或者设成`ping_timeout=None`来禁用心跳超时。对可靠性比websocket延迟更重要的运行，建议改用HTTP/SSE传输。

### Run config

`run_config`参数让你可以配置这次运行的一些全局设置：

#### Run config的常见分类

用`RunConfig`可以在不改动每个agent定义的前提下，覆盖单次运行的行为。

**模型、provider、session默认值**

- `model`：设置一个全局要用的LLM模型，不管每个Agent自己配的是什么`model`。
- `model_provider`：查找模型名称用的provider，默认是OpenAI。
- `model_settings`：覆盖agent自己的设置，比如可以设一个全局的`temperature`或`top_p`。
- `session_settings`：在运行中取历史记录时，覆盖session级别的默认值（比如`SessionSettings(limit=...)`）。
- `session_input_callback`：在用Sessions时，自定义每次`Runner`运行前新用户输入怎么跟session历史合并。这个回调可以是同步也可以是异步的。

**Guardrails、handoff、模型输入整形**

- `input_guardrails`、`output_guardrails`：应用到所有运行上的输入/输出guardrail列表。
- `handoff_input_filter`：应用到所有handoff上的全局输入过滤器（如果该handoff自己还没配一个的话）。这个过滤器能让你编辑发给新agent的输入内容，详见`Handoff.input_filter`的文档。
- `nest_handoff_history`：一个opt-in的beta功能，在调用下一个agent之前，把可摘要的历史压缩成有序的assistant摘要片段，同时把无损的消息条目保留在原来的位置。因为团队还在稳定嵌套handoff这个功能，默认是关闭的；设成`True`来开启，留`False`就是原样透传完整transcript。Sessions、`RunState`、`RunResult.to_input_list()`在SDK默认的嵌套历史已经包含某条消息时，不会重复追加同一条消息，但仍会保留真正不同的相同消息。所有`Runner`方法在你没传`RunConfig`时都会自动创建一个，所以quickstart和示例默认保持关闭；任何显式配置的`Handoff.input_filter`回调仍然会覆盖这个设置。单个handoff可以通过`Handoff.nest_handoff_history`覆盖这个设置。
- `handoff_history_mapper`：可选的回调函数，当你启用了`nest_handoff_history`时，它会收到标准化后的transcript（历史+handoff条目），必须返回要转发给下一个agent的确切input item列表，用它可以替换掉内置的有序摘要片段，不用自己写一整套handoff过滤器。
- `call_model_input_filter`：在模型调用**之前**编辑已经准备好的完整模型输入（instructions和input items）的钩子，比如可以用来裁剪历史或者注入一条系统提示词。
- `reasoning_item_id_policy`：控制Runner把之前的输出转换成下一回合的模型输入时，推理条目的ID要不要保留。

**追踪与可观测性**

- `tracing_disabled`：为整次运行禁用[追踪](tracing.md)。
- `tracing`：传一个`TracingConfig`来覆盖追踪导出的设置，比如单次运行专属的tracing API key。
- `trace_include_sensitive_data`：配置追踪数据里要不要包含可能敏感的信息，比如LLM和工具调用的输入/输出。
- `workflow_name`、`trace_id`、`group_id`：设置这次运行的追踪工作流名称、trace ID和trace group ID。至少建议设置`workflow_name`。`group_id`是可选字段，能把多次运行的trace关联起来。
- `trace_metadata`：附加到所有trace上的元数据。

**工具执行、审批、工具报错行为**

- `tool_execution`：配置SDK侧对本地工具调用的执行行为，比如限制同时能跑多少个本地function tool调用。
- `tool_not_found_behavior`：配置当模型发出的function tool调用名字，跟当前agent可用的任何function tool都对不上时，Runner该怎么处理。默认会抛出`ModelBehaviorError`；可以选择改成返回一条模型可见的报错输出。
- `tool_name_collision_policy`：配置当未加命名空间的function-tool和handoff名字发生冲突时，Runner该怎么处理。默认值`"warn"`会记一条可操作的警告日志，只暴露当前的分发胜出者；`"error"`会在调用模型之前直接抛出`UserError`。对带命名空间和延迟加载工具的严格校验不受影响。
- `tool_error_formatter`：自定义模型可见的工具报错信息，比如审批被拒绝、以及opt-in的"工具找不到"这类输出。

嵌套handoff目前是opt-in的beta功能。传`RunConfig(nest_handoff_history=True)`，或者对单个handoff设`handoff(..., nest_handoff_history=True)`，就能开启有序的transcript压缩。内置的mapper会把生成的assistant摘要片段放在无损消息条目周围，而不是把整段transcript压成一条消息。如果想保留原始transcript（默认行为），不设这个flag就行，或者提供一个按你需要转发对话内容的`handoff_input_filter`（或`handoff_history_mapper`）。想在不写自定义mapper的前提下修改生成摘要片段里用的包装文案，调用`set_conversation_history_wrappers`（以及用`reset_conversation_history_wrappers`恢复默认值）。

#### Run config细节

**`tool_execution`**——想配置SDK侧对本地function tool的行为时用，比如限制一次运行里本地function-tool的并发数：

```python
from agents import Agent, RunConfig, Runner, ToolExecutionConfig

agent = Agent(name="Assistant", tools=[...])

result = await Runner.run(
    agent,
    "Run the required tool calls.",
    run_config=RunConfig(
        tool_execution=ToolExecutionConfig(
            max_function_tool_concurrency=2,
            pre_approval_tool_input_guardrails=True,
        ),
    ),
)
```

`max_function_tool_concurrency=None`保留默认行为：模型在一个回合里发出多个function tool调用时，SDK会把所有发出的本地function tool调用全部启动。设一个整数值可以限制同时能跑多少个。

这跟provider侧的`ModelSettings.parallel_tool_calls`是两回事——`parallel_tool_calls`控制的是模型**允不允许**在一次响应里发出多个工具调用；`tool_execution.max_function_tool_concurrency`控制的是模型发出这些调用**之后**，SDK怎么执行这些本地function tool调用。

`pre_approval_tool_input_guardrails=False`保留默认的审批流程：如果一个function tool需要审批，运行会先暂停，工具输入guardrail只在审批通过后、真正执行前才会跑。设成`True`则会让function-tool的输入guardrail在"待审批中断"被发出**之前**就先跑一遍。通过这次预审批检查的调用，审批通过后仍然会再跑一遍同样的输入guardrail，这样时效性检查会在真正执行前被重新验证一遍。

**`tool_not_found_behavior`**——默认情况下，如果模型发出的function tool调用，跟当前agent可用的任何function tool都对不上，Runner会抛出`ModelBehaviorError`。

设`tool_not_found_behavior="return_error_to_model"`可以让运行保持可恢复。这种模式下，SDK会为这个没解析成功的工具调用追加一条`function_call_output`，然后重新跑一次模型，让模型可以选一个可用的工具，或者不用那个工具直接回答。

```python
from agents import Agent, RunConfig, Runner

agent = Agent(name="Assistant", tools=[...])

result = await Runner.run(
    agent,
    "Handle this request with the available tools.",
    run_config=RunConfig(tool_not_found_behavior="return_error_to_model"),
)
```

这个选项目前只适用于工具名查找失败的function tool调用。其他类型的非法工具payload，仍然走它们各自已有的报错行为。

**`tool_error_formatter`**——用来自定义SDK产出一条模型可见的工具报错信息时，返回给模型的具体文案。

这个formatter接收一个`ToolErrorFormatterArgs`对象，字段包括：

- `kind`：错误类别，比如`"approval_rejected"`或`"tool_not_found"`。
- `tool_type`：工具运行时类型（`"function"`、`"computer"`、`"shell"`、`"apply_patch"`或`"custom"`）。
- `tool_name`：工具名。
- `call_id`：这次工具调用的ID。
- `default_message`：SDK默认的模型可见文案。
- `run_context`：当前生效的运行上下文包装对象。

返回一个字符串来替换文案，或者返回`None`使用SDK默认文案。

```python
from agents import Agent, RunConfig, Runner, ToolErrorFormatterArgs


def format_rejection(args: ToolErrorFormatterArgs[None]) -> str | None:
    if args.kind == "approval_rejected":
        return (
            f"Tool call '{args.tool_name}' was rejected by a human reviewer. "
            "Ask for confirmation or propose a safer alternative."
        )
    if args.kind == "tool_not_found":
        return f"Tool '{args.tool_name}' is not available. Choose one of the listed tools."
    return None


agent = Agent(name="Assistant")
result = Runner.run_sync(
    agent,
    "Please delete the production database.",
    run_config=RunConfig(tool_error_formatter=format_rejection),
)
```

**`reasoning_item_id_policy`**——控制当Runner把历史继续往下传时（比如用`RunResult.to_input_list()`或session支撑的运行），推理条目要怎么被转换成下一回合的模型输入。

- `None`或`"preserve"`（默认）：保留推理条目的ID。
- `"omit"`：在生成下一回合输入时，去掉推理条目的ID。

`"omit"`主要是给一类Responses API的400报错准备的opt-in缓解方案——报错场景是：一个推理条目带着`id`发出去了，但缺少它必须紧跟着的后续条目（比如报错信息类似`Item 'rs_...' of type 'reasoning' was provided without its required following item.`）。

这种情况可能发生在多轮agent运行里，SDK从之前的输出构造后续输入时（包括session持久化、服务端管理的conversation增量、流式/非流式的后续回合、以及恢复路径），一个推理条目的ID被保留了下来，但provider要求这个ID必须继续跟它对应的后续条目配对。

设置`reasoning_item_id_policy="omit"`会保留推理内容本身，但去掉推理条目的`id`，这样就不会在SDK生成的后续输入里触发那条API的强制约束。

范围说明：

- 这个设置只影响SDK在构造后续输入时生成/转发的推理条目。
- 不会改写用户提供的初始输入条目。
- 应用这条策略之后，`call_model_input_filter`仍然可以有意地把推理ID重新加回去。

## 状态与对话管理

### 选择一种记忆策略

有四种常见的方式，可以把状态带到下一回合：

| 策略 | 状态存在哪 | 最适合场景 | 下一回合要传什么 |
| --- | --- | --- | --- |
| `result.to_input_list()` | 你的应用自己的内存 | 小型聊天循环、完全手动控制、适用任何provider | `result.to_input_list()`返回的列表，加上下一条用户消息 |
| `session` | 你自己的存储 + SDK | 持久化聊天状态、可恢复的运行、自定义存储 | 同一个`session`实例，或者指向同一个存储的另一个实例 |
| `conversation_id` | OpenAI Conversations API | 想跨worker/服务共享的、有名字的服务端对话 | 同一个`conversation_id`，加上仅这一轮的新用户输入 |
| `previous_response_id` | OpenAI Responses API | 轻量级的服务端管理式续接，不需要创建一个conversation资源 | `result.last_response_id`，加上仅这一轮的新用户输入 |

`result.to_input_list()`和`session`是**客户端管理**的；`conversation_id`和`previous_response_id`是**OpenAI管理**的，只在你用OpenAI Responses API时才适用。大多数应用里，一段对话只应该选一种持久化策略——把客户端管理的历史和OpenAI管理的状态混着用，除非你刻意去协调这两层，否则很容易产生重复的上下文。

> **官方笔记**：Session持久化不能在同一次运行里跟服务端管理的conversation设置（`conversation_id`、`previous_response_id`、或`auto_previous_response_id`）混用。每次调用只能选一种方式。

### 对话/聊天线程

调用任意一个run方法，可能会导致一个或多个agent运行（因此也是一次或多次LLM调用），但它代表的是聊天对话里**单独一个逻辑回合**。举个例子：

1. **用户回合**：用户输入文字。
2. **Runner运行**：第一个agent调用LLM、跑工具、把任务handoff给第二个agent，第二个agent再跑更多工具，最后产出一个输出。

agent运行结束之后，你可以自己决定给用户看什么——比如可以把agent产出的每一条新内容都展示出来，也可以只展示最终输出。不管哪种方式，用户接下来可能会问一个后续问题，这时候你可以再调用一次run方法。

#### 手动管理对话

可以用`RunResultBase.to_input_list()`方法手动管理对话历史，拿到下一回合要用的输入：

```python
from agents import Agent, Runner, trace

async def main():
    agent = Agent(name="Assistant", instructions="Reply very concisely.")

    thread_id = "thread_123"  # Example thread ID
    with trace(workflow_name="Conversation", group_id=thread_id):
        # First turn
        result = await Runner.run(agent, "What city is the Golden Gate Bridge in?")
        print(result.final_output)
        # San Francisco

        # Second turn
        new_input = result.to_input_list() + [{"role": "user", "content": "What state is it in?"}]
        result = await Runner.run(agent, new_input)
        print(result.final_output)
        # California
```

#### 用Sessions自动管理对话

更简单的方式是用[Sessions](sessions/index.md)，不用手动调`.to_input_list()`就能自动处理对话历史：

```python
from agents import Agent, Runner, SQLiteSession, trace

async def main():
    agent = Agent(name="Assistant", instructions="Reply very concisely.")

    # Create session instance
    session = SQLiteSession("conversation_123")

    thread_id = "thread_123"  # Example thread ID
    with trace(workflow_name="Conversation", group_id=thread_id):
        # First turn
        result = await Runner.run(agent, "What city is the Golden Gate Bridge in?", session=session)
        print(result.final_output)
        # San Francisco

        # Second turn - agent automatically remembers previous context
        result = await Runner.run(agent, "What state is it in?", session=session)
        print(result.final_output)
        # California
```

Sessions会自动：

- 每次运行**前**取回对话历史；
- 每次运行**后**存储新消息；
- 为不同的session ID维护各自独立的对话。

更多细节见[Sessions文档](sessions/index.md)。

#### 服务端管理的对话

也可以让OpenAI的conversation state功能在服务端管理对话状态，而不是用`to_input_list()`或`Sessions`在本地处理。这样可以在不用每次都重发全部历史消息的前提下，保留对话历史。用下面这两种服务端管理方式，每次请求只需要传这一轮的新输入，然后复用保存好的ID。更多细节见[OpenAI Conversation state guide](https://platform.openai.com/docs/guides/conversation-state?api-mode=responses)。

OpenAI提供两种跨回合追踪状态的方式：

**方式1：用`conversation_id`**——先用OpenAI Conversations API创建一段对话，之后每次调用都复用它的ID：

```python
from agents import Agent, Runner
from openai import AsyncOpenAI

client = AsyncOpenAI()

async def main():
    agent = Agent(name="Assistant", instructions="Reply very concisely.")

    # Create a server-managed conversation
    conversation = await client.conversations.create()
    conv_id = conversation.id

    while True:
        user_input = input("You: ")
        result = await Runner.run(agent, user_input, conversation_id=conv_id)
        print(f"Assistant: {result.final_output}")
```

**方式2：用`previous_response_id`**——另一种方式是**response chaining（响应链）**，每一回合都显式链接到上一回合的response ID：

```python
from agents import Agent, Runner

async def main():
    agent = Agent(name="Assistant", instructions="Reply very concisely.")

    previous_response_id = None

    while True:
        user_input = input("You: ")

        # Setting auto_previous_response_id=True enables response chaining automatically
        # for the first turn, even when there's no actual previous response ID yet.
        result = await Runner.run(
            agent,
            user_input,
            previous_response_id=previous_response_id,
            auto_previous_response_id=True,
        )
        previous_response_id = result.last_response_id
        print(f"Assistant: {result.final_output}")
```

如果一次运行因为等待审批而暂停，之后你从一个`RunState`恢复它，SDK会保留之前保存好的`conversation_id`/`previous_response_id`/`auto_previous_response_id`设置，让恢复的这一回合继续用同一个服务端管理的对话。

`conversation_id`和`previous_response_id`是互斥的。想要一个能跨系统共享、有名字的对话资源时用`conversation_id`；只是想要从一轮到下一轮最轻量的Responses API续接手段时用`previous_response_id`。

> **官方笔记**：SDK会自动对`conversation_locked`报错做带退避的重试。在服务端管理的对话运行里，重试之前会先把内部的conversation追踪器输入回滚，这样同样准备好的条目才能被干净地重新发送。
>
> 在本地基于session的运行里（不能跟`conversation_id`、`previous_response_id`、`auto_previous_response_id`混用），SDK也会尽力回滚最近持久化的输入条目，减少重试后产生的重复历史记录。
>
> 这种兼容性重试，即便你没有配置`ModelSettings.retry`也会发生。关于模型请求更广泛的opt-in重试行为，见[Runner-managed retries](models/index.md#runner-managed-retries)。

## Hooks与自定义

### Call model input filter

用`call_model_input_filter`可以在模型调用**前一刻**编辑模型输入。这个钩子会收到当前的agent、context，以及合并好的input items（如果有session历史，也包含在内），返回一个新的`ModelInputData`。

返回值必须是一个`ModelInputData`对象，它的`input`字段是必填的、必须是一个input item列表。返回其他形状的数据会抛出`UserError`。

```python
from agents import Agent, Runner, RunConfig
from agents.run import CallModelData, ModelInputData

def drop_old_messages(data: CallModelData[None]) -> ModelInputData:
    # Keep only the last 5 items and preserve existing instructions.
    trimmed = data.model_data.input[-5:]
    return ModelInputData(input=trimmed, instructions=data.model_data.instructions)

agent = Agent(name="Assistant", instructions="Answer concisely.")
result = Runner.run_sync(
    agent,
    "Explain quines",
    run_config=RunConfig(call_model_input_filter=drop_old_messages),
)
```

Runner传给这个钩子的是准备好的input列表的**一份拷贝**，所以你可以裁剪、替换、重新排序它，不会直接改动调用方原本的列表。

如果你在用session，`call_model_input_filter`会在session历史**已经加载完并跟当前回合合并之后**才运行。如果想自定义这个更早的合并步骤本身，用`session_input_callback`。

如果你在用OpenAI服务端管理的对话状态（`conversation_id`、`previous_response_id`或`auto_previous_response_id`），这个钩子跑在为下一次Responses API调用准备好的payload上——这份payload可能已经只是这一轮的增量，而不是完整的历史重放。对于这种服务端管理的续接，只有你返回的那些条目才会被标记为"已发送"。

可以按运行单独设置这个钩子（通过`run_config`），用来脱敏敏感数据、裁剪过长的历史、或者注入额外的系统指导内容。

## 错误与恢复

### 错误处理器（Error handlers）

所有`Runner`入口方法都接受一个`error_handlers`参数，是一个按错误类型分类的字典。支持的key是`"max_turns"`、`"model_refusal"`、`"invalid_final_output"`。想让运行返回一个受控的最终输出、而不是直接以对应错误结束时，就用它们。

```python
from agents import (
    Agent,
    RunErrorHandlerInput,
    RunErrorHandlerResult,
    Runner,
)

agent = Agent(name="Assistant", instructions="Be concise.")


def on_max_turns(_data: RunErrorHandlerInput[None]) -> RunErrorHandlerResult:
    return RunErrorHandlerResult(
        final_output="I couldn't finish within the turn limit. Please narrow the request.",
        include_in_history=False,
    )


result = Runner.run_sync(
    agent,
    "Analyze this long transcript",
    max_turns=3,
    error_handlers={"max_turns": on_max_turns},
)
print(result.final_output)
```

`"invalid_final_output"`用在模型消息没有通过agent结构化`output_type`的校验、或者模型压根没返回结构化最终消息时。这个处理器可以返回一个应用自定义的兜底值，SDK会用同一个`output_type`去校验它——**不会**重新调用模型、也不会重放任何工具的副作用。返回`None`表示放弃恢复。没有提供兜底值的情况下，非空的校验失败仍然会抛出`ModelBehaviorError`，空的结构化响应保留现有的下一回合行为。

```python
from pydantic import BaseModel

from agents import Agent, ModelBehaviorError, RunErrorHandlerInput, Runner


class Recipe(BaseModel):
    ingredients: list[str]
    recovered_from_invalid_output: bool = False


def on_invalid_final_output(data: RunErrorHandlerInput[None]) -> Recipe:
    assert isinstance(data.error, ModelBehaviorError)
    return Recipe(ingredients=[], recovered_from_invalid_output=True)


agent = Agent(
    name="Recipe assistant",
    instructions="Return a structured recipe.",
    output_type=Recipe,
)

result = Runner.run_sync(
    agent,
    "Plan tonight's dinner.",
    error_handlers={"invalid_final_output": on_invalid_final_output},
)
print(result.final_output)
```

`RunErrorHandlerResult.include_in_history`默认是`True`。对`max_turns`处理器来说，这会把合成出来的兜底输出追加进对话历史，并持久化到配置好的session里。想让兜底结果只返回给调用方、不写进结果历史或session存储时，设成`include_in_history=False`。

`"model_refusal"`用在模型拒绝回答、你想让它产出一个应用自定义的兜底值，而不是直接以`ModelRefusalError`结束运行时。

```python
from pydantic import BaseModel

from agents import Agent, ModelRefusalError, RunErrorHandlerInput, Runner


class Recipe(BaseModel):
    ingredients: list[str]
    refusal_reason: str | None = None


def on_model_refusal(data: RunErrorHandlerInput[None]) -> Recipe:
    assert isinstance(data.error, ModelRefusalError)
    return Recipe(ingredients=[], refusal_reason=data.error.refusal)


agent = Agent(
    name="Recipe assistant",
    instructions="Return a structured recipe.",
    output_type=Recipe,
)

result = Runner.run_sync(
    agent,
    "Make me something unsafe.",
    error_handlers={"model_refusal": on_model_refusal},
)
print(result.final_output)
```

## 学习笔记：`error_handlers` vs Claude Code `ResultMessage.subtype`——两种错误处理哲学

这条不是原文内容，是跟Claude Code Agent SDK的错误处理机制做的对比，属于OpenAI这套`error_handlers`机制的拓展学习，不放进`TurnLoop.md`主线（跟"Loop怎么运行"关系不大，更贴近这篇文档自己的错误处理设计）。

**核心不在"用什么字段"，在"错误处理这一步能不能拦截住即将抛出的异常"。**

![error_handlers与ResultMessage.subtype两种错误处理机制对比图：上半部分OpenAI Agents SDK面板——Runner循环触发错误条件后，先检查error_handlers字典里有没有注册对应kind的handler；已注册且返回非None则调用handler拿到RunErrorHandlerResult(final_output, include_in_history)，不抛出任何异常，Runner.run()正常返回一个RunResult，result.final_output就是handler给的兜底值，include_in_history默认True会把这个兜底输出追加进历史并持久化到session；未注册或handler返回None则抛出对应异常MaxTurnsExceeded/ModelRefusalError/ModelBehaviorError；配了真实代码引用展示result.final_output可以直接访问、完全没有try except。下半部分Claude Code Agent SDK面板——不管Loop正常还是异常结束，SDK都会先往消息流里yield一条ResultMessage，用subtype字段标出具体原因(success/error_max_turns/error_max_budget_usd/error_during_execution/error_max_structured_output_retries)，只有success时result字段才可用；调用方在async for循环里检查message.subtype只是被动获知发生了什么、不能阻止接下来的事情发生；官方原文明确写着单次query()调用会先yield这条最终结果消息、然后照样抛出一个异常，这个raise是故意设计的，必须用try块包起来才能继续执行；配了真实代码引用展示async for内部检查subtype、外部依然套了一层except Exception。底部结论框指出OpenAI把"要不要把这次失败当成失败"的决定权交给了开发者，可以让运行看起来像正常成功返回；Claude Code把这个决定权收在自己手里，失败就是失败、异常一定会抛，subtype只回答"为什么失败"不改变"失败了"这个既成事实](error-handling-philosophy-comparison.svg)

**两条实锤证据是这个对比成立的关键**：

1. **OpenAI这边"确实不抛异常"，不是推断出来的**——官方示例代码里`Runner.run_sync(..., error_handlers={"max_turns": on_max_turns})`之后直接`print(result.final_output)`，**没有任何`try/except`包裹**。而且原文明确说用`error_handlers`是为了"return a controlled final output **instead of ending the run with the corresponding error**"——字面意思就是"不要以那个错误结束这次运行"。
2. **Claude Code这边"异常照样会抛"，是官方原文自己写死的**——"A single-shot `query()` call yields the final result message, **then raises an error**... **The raise is intentional**."——这句话把这个设计定性成"故意的"，不是bug，`subtype`检查和这个异常是两件独立发生的事，检查代码写得再仔细也拦不住这个异常。

**一句话总结这个区别，可以带去后面学"故障恢复策略"（Layer 5）时用**：OpenAI的`error_handlers`是运行内部的**拦截点**，能让失败在调用方看来"像没发生过"；Claude Code的`subtype`是运行结束之后的**事后诊断**，只告诉你"为什么"，不改变"失败了"这个既成事实，开发者只能决定收到诊断结果之后要不要重开一次。

## 持久化执行集成 与 人在回路

关于工具审批的暂停/恢复模式，先看专门的[人在回路指南](human_in_the_loop.md)。下面这些集成，是给"运行可能要经历长时间等待、重试、或进程重启"这类场景用的持久化编排方案。

- **Dapr**：用Agents SDK的[Dapr](https://dapr.io) Diagrid集成，跑能自动从故障中恢复、支持人在回路工作流的持久化长时运行agent。Dapr是一个厂商中立的[CNCF](https://cncf.io)工作流编排器。
- **Temporal**：用Agents SDK的[Temporal](https://temporal.io/)集成，跑持久化的长时工作流，包括人在回路任务。
- **Restate**：用Agents SDK的[Restate](https://restate.dev/)集成，做轻量级、持久化的agent，包括人工审批、handoff、session管理。这个集成需要Restate的单二进制运行时作为依赖，支持把agent跑成进程/容器或serverless函数。
- **DBOS**：用Agents SDK的[DBOS](https://dbos.dev/)集成，跑能在故障和重启后保留进度的可靠agent，支持长时运行agent、人在回路工作流、handoff，同步/异步方法都支持，只需要一个SQLite或Postgres数据库。

## 异常

SDK在特定情况下会抛出异常，完整列表见`agents.exceptions`，概览如下：

- **`AgentsException`**：所有SDK抛出异常的基类，是一个通用类型，其他所有具体异常都从它派生。
- **`MaxTurnsExceeded`**：agent运行超过了传给`Runner.run`/`Runner.run_sync`/`Runner.run_streamed`方法的`max_turns`限制时抛出，说明agent没能在指定的agent循环回合数（即LLM调用次数）内完成任务。设`max_turns=None`可以禁用这个限制。
- **`ModelTimeoutError`**：一次模型调用尝试超过`ModelSettings.timeout`时抛出，具体范围和重试行为见[Model-call timeouts](models/index.md#model-call-timeouts)。
- **`ModelBehaviorError`**：底层模型（LLM）产出了意外或非法输出时抛出，可能包括：
  - **格式错误的JSON**：模型给工具调用、或者在配置了具体`output_type`时给直接输出，提供了格式错误的JSON结构。
  - **意外的工具相关故障**：模型没有以预期的方式使用工具。
  - **非流式Responses调用失败或不完整**：`OpenAIResponsesModel`和`AnyLLMModel`里的Responses路径，在返回的response终止状态是`failed`或`incomplete`时会抛出这个异常，异常里会标明终止状态、并包含response里能拿到的报错或不完整详情。
- **`ToolTimeoutError`**：一次function tool调用超过了配置的超时、且该工具用的是`timeout_behavior="raise_exception"`时抛出。
- **`UserError`**：你（使用SDK写代码的人）在用SDK时出错时抛出，通常源自代码实现错误、配置无效、或者误用了SDK的API。
- **`InputGuardrailTripwireTriggered`**、**`OutputGuardrailTripwireTriggered`**：分别在输入guardrail的条件满足、和输出guardrail的条件满足时抛出——输入guardrail在处理之前检查传入的消息，输出guardrail在交付之前检查agent的最终响应。
