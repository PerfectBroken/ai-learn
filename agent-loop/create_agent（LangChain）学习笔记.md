# `create_agent`（LangChain，`create_react_agent`的替代品）

来源：`langchain-ai/langchain`仓库`libs/langchain_v1/langchain/agents/factory.py`里`create_agent`函数的docstring（直接从源码拉取，这是`reference.langchain.com`网页文档的生成来源）

> **背景**：本来打算学的是`langgraph.prebuilt.create_react_agent`（`reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent`），但查文档时发现它已经在源码里标了废弃：
>
> ```
> !!! warning
>     This function is deprecated in favor of `create_agent` from the `langchain` package,
>     which provides an equivalent agent factory with a flexible middleware system.
> ```
>
> 于是直接改学官方现在指路的`create_agent`（在`langchain`包，不是`langgraph`包里）。

## 函数签名

```python
def create_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    response_format: ResponseFormat[ResponseT] | type[ResponseT] | dict[str, Any] | None = None,
    state_schema: type[AgentState[ResponseT]] | None = None,
    context_schema: type[ContextT] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache[Any] | None = None,
    transformers: Sequence[TransformerFactory] | None = None,
) -> CompiledStateGraph[...]:
```

## 参数说明

- **`model`**：agent用的语言模型。可以是字符串标识符（比如`"openai:gpt-5.5"`），也可以是直接传一个chat model实例（比如`ChatOpenAI`）。
- **`tools`**：工具列表、`dict`、或`Callable`。如果是`None`或空列表，agent就只是一个不带工具调用循环的纯模型节点。
- **`system_prompt`**：可选的系统提示词。可以是`str`（会被转换成`SystemMessage`），也可以直接传`SystemMessage`实例。会被加在调用模型时消息列表的最前面。
- **`middleware`**：一串middleware实例，应用在这个agent上。**Middleware能在agent运行的各个阶段拦截、修改agent行为**——这是`create_agent`相比`create_react_agent`最核心的新增机制，`create_react_agent`原本只有`pre_model_hook`/`post_model_hook`两个单点钩子，`create_agent`换成了一整套可组合的middleware系统（这份docstring本身没有展开讲middleware具体怎么写，只指了路，链接在[Middleware文档](https://docs.langchain.com/oss/python/langchain/middleware)，值得之后单独学一次）。
- **`response_format`**：可选的结构化响应配置。可以是`ToolStrategy`、`ProviderStrategy`，或者直接一个Pydantic模型类——如果提供了，agent会在对话过程中处理结构化输出；原始schema会根据模型能力被自动包进合适的strategy里。（对比`create_react_agent`：那边`response_format`接受的是裸schema或`(prompt, schema)`元组，这边多包了一层"strategy"抽象。）
- **`state_schema`**：可选的、扩展自`AgentState`的`TypedDict` schema。**官方建议**：一般应该优先通过middleware去扩展state，而不是直接改这个参数——这样能把状态扩展的范围，收得跟对应的hook/工具强相关，不要到处乱加字段。
- **`context_schema`**：运行时上下文的可选schema（对应`Graph API overview`里学过的`Runtime[Context]`机制）。
- **`checkpointer`**：可选的checkpoint saver，用来给单个线程（比如一次对话）持久化图的state（比如当聊天记忆用）。
- **`store`**：可选的store对象，用来跨多个线程（比如多个对话/多个用户）持久化数据。
- **`interrupt_before`** / **`interrupt_after`**：可选的、要在哪些节点前/后中断的节点名列表——前者适合加用户确认或其他中断，后者适合直接返回结果或对输出做额外处理。
- **`debug`**：是否开启详细日志，打印每个节点执行、state更新、状态转移的细节，方便调试middleware行为、理解agent执行流程。
- **`name`**：给这个`CompiledStateGraph`起的可选名字——当把这个agent图当subgraph节点加进另一个图时会自动用到，对搭建multi-agent系统特别有用。
- **`cache`**：可选的`BaseCache`实例，给图执行开启缓存。
- **`transformers`**：可选的、感知scope的`StreamTransformer`工厂序列，注册到编译好的图上（在agent默认的基础上追加）。每个工厂都以`factory(scope)`的形式被调用，所以每次调用拿到的都是全新实例。编译出来的图上，最终顺序是：`ToolCallTransformer` → middleware通过`AgentMiddleware.transformers`声明的工厂 → 这里传进来的工厂。

## 核心机制：跟`create_react_agent`一模一样的两节点循环

> "The agent node calls the language model with the messages list (after applying the system prompt). If the resulting `AIMessage` contains `tool_calls`, the graph will then call the tools. The tools node executes the tools and adds the responses to the messages list as `ToolMessage` objects. The agent node then calls the language model again. The process repeats until no more `tool_calls` are present in the response. The agent then returns the full list of messages."

翻译：agent节点用（套上system prompt之后的）消息列表调用语言模型；如果产出的`AIMessage`带`tool_calls`，图就去调用tools节点；tools节点执行这些工具、把响应作为`ToolMessage`对象追加进消息列表；agent节点再次调用语言模型；这个过程一直重复，直到响应里不再出现`tool_calls`；最后agent返回完整的消息列表。

**这跟`Graph API overview`里学的机制完全对得上**——两个节点（`agent`/`tools`），中间用条件边连成一个循环，条件判断依据就是"最新一条`AIMessage`有没有`tool_calls`"，没有工具调用了就走向`END`。`create_agent`没有在图结构层面发明新东西，新增的核心是**middleware这层可组合的拦截机制**，图本身的循环拓扑是延续`create_react_agent`原来那套的。

## 示例代码

```python
from langchain.agents import create_agent


def check_weather(location: str) -> str:
    """Return the weather forecast for the specified location."""
    return f"It's always sunny in {location}"


graph = create_agent(
    model="anthropic:claude-sonnet-4-5-20250929",
    tools=[check_weather],
    system_prompt="You are a helpful assistant",
)
inputs = {"messages": [{"role": "user", "content": "what is the weather in sf"}]}
for chunk in graph.stream(inputs, stream_mode="updates"):
    print(chunk)
```

## 深挖：真实的Node/Edge定义（源码，`factory.py`，非docstring内容）

docstring里只用一句话描述了机制，没有给具体的`add_node`/`add_edge`调用。查了`libs/langchain_v1/langchain/agents/factory.py`里`create_agent`函数体，发现真实的图结构比"两节点循环"复杂不少——**核心原因是：middleware不是简单包一层回调函数，是被编译成图里真正的、独立的节点**。

### 1. 固定的两个基础节点

```python
graph.add_node("model", RunnableCallable(model_node, amodel_node, trace=False))

if tool_node is not None:
    graph.add_node("tools", tool_node)
```

`model`节点永远存在；`tools`节点只有在传了`tools`参数时才加——跟`Graph API overview`里学的"没有workflow就是单节点"逻辑一致。

### 2. Middleware贡献的四种节点，按名字动态生成

对每一个传进来的middleware实例，只要它**重写**（override）了对应的钩子方法，就会给图新增一个节点，节点名是`f"{middleware.name}.{钩子名}"`：

```python
graph.add_node(f"{m.name}.before_agent", ...)   # 只在整个agent运行前跑一次
graph.add_node(f"{m.name}.before_model", ...)   # 循环内，每次调模型前跑
graph.add_node(f"{m.name}.after_model", ...)    # 循环内，每次模型响应后跑
graph.add_node(f"{m.name}.after_agent", ...)    # 整个agent运行结束后跑一次
```

**关键点**：`before_agent`/`after_agent`在整个loop外层，各只跑一次；`before_model`/`after_model`在loop内部，每一轮迭代都会跑。这四个位置分别对应"整个agent的生命周期起止"和"loop内部每一轮的起止"两个不同粒度。

### 3. 四个动态计算出来的"角色位置"

图真正连边之前，会先算出四个关键位置（哪个具体节点名，取决于你注册了哪些middleware、它们各自实现了哪些钩子）：

```python
# entry_node：整个agent只跑一次的入口——before_agent > before_model > model
if middleware_w_before_agent:
    entry_node = f"{middleware_w_before_agent[0].name}.before_agent"
elif middleware_w_before_model:
    entry_node = f"{middleware_w_before_model[0].name}.before_model"
else:
    entry_node = "model"

# loop_entry_node：循环每一轮回到的位置（不含before_agent，因为它只跑一次）
if middleware_w_before_model:
    loop_entry_node = f"{middleware_w_before_model[0].name}.before_model"
else:
    loop_entry_node = "model"

# loop_exit_node：循环每一轮结束的位置（after_model或model，不含after_agent）
if middleware_w_after_model:
    loop_exit_node = f"{middleware_w_after_model[0].name}.after_model"
else:
    loop_exit_node = "model"

# exit_node：整个agent只跑一次的出口——after_agent或END
if middleware_w_after_agent:
    exit_node = f"{middleware_w_after_agent[-1].name}.after_agent"
else:
    exit_node = END
```

**用一个具体例子固化理解**：假设你只注册了一个middleware、只实现了`before_model`和`after_model`（没实现`before_agent`/`after_agent`），那么：`entry_node = loop_entry_node = "我的middleware.before_model"`，`loop_exit_node = "我的middleware.after_model"`，`exit_node = END`（因为没有`after_agent`）。

### 4. 真正的边——`model`↔`tools`的条件循环，接在上面算出来的位置上

```python
graph.add_edge(START, entry_node)

if tool_node is not None:
    # tools执行完，条件路由回loop入口，或者（工具标了return_direct/有结构化输出工具时）直接退出
    graph.add_conditional_edges(
        "tools",
        _make_tools_to_model_edge(...),
        tools_to_model_destinations,  # [loop_entry_node] 或 [loop_entry_node, exit_node]
    )

    # 模型响应完，条件路由到tools（有tool_calls）、退出（没有）、或跳回loop入口（HITL注入了工具消息/需要重新生成结构化输出）
    graph.add_conditional_edges(
        loop_exit_node,
        _make_model_to_tools_edge(...),
        model_to_tools_destinations,  # ["tools", exit_node] 或再加上 loop_entry_node
    )
```

**这跟我们之前理解的"agent节点↔tools节点两点循环"，本质没变——只是"agent节点"这个概念，被拆成了`entry_node`/`loop_entry_node`/`loop_exit_node`/`exit_node`四个可能不同的具体节点，middleware越多，这条链就越长**（多个middleware的`before_model`会依次排在loop入口前面，多个`after_model`会依次排在loop出口后面）。如果一个middleware都不传（等价于`create_react_agent`原来的行为），这四个变量会全部退化成`"model"`或`END`，边的结构就完全变回最简单的两节点循环。

### 5. 完整流程图（以注册了一个实现全部4个钩子的middleware为例）

![create_agent真实节点/边流程图：以一个实现了before_agent/before_model/after_model/after_agent全部四个钩子的middleware M为例。节点从上到下是START、M.before_agent（entry_node）、M.before_model（loop_entry_node）、model、tools、M.after_model（loop_exit_node）、M.after_agent（exit_node）、END，其中四个M.xxx节点画成虚线框标出是middleware贡献的可选节点。边：START到M.before_agent固定边；M.before_agent到M.before_model、M.before_model到model都是条件边（默认走这条，也能跳到exit_node提前结束整个agent）；model到M.after_model是唯一一条纯固定边；M.after_model三选一条件边——有tool_calls去tools，没有去exit_node，HITL注入工具消息或需要重新生成结构化输出则跳回loop_entry_node；tools二选一条件边——正常回loop_entry_node，工具标了return_direct或有结构化输出工具则直接去exit_node；M.after_agent条件边——默认到END，也能跳回loop_entry_node重新进入循环。图下方额外说明了多个middleware时的串联规则：before_agent/before_model按注册顺序正序串联，after_model/after_agent按注册顺序反序串联，以及一个middleware都不注册时整张图退化成model与tools的两节点循环](create-agent-node-edge-flow.svg)

**两个源码里验证到、但值得特别记一下的点**：

1. **`model → M.after_model`是全图唯一一条"纯固定边"**——其余`M.before_agent → M.before_model`、`M.before_model → model`、`M.after_agent → END`这几条看起来像"线性走一遍"的连接，其实全部是**条件边**，只是默认路径是"往下走"，middleware可以通过`can_jump_to`让它们直接跳到`loop_entry_node`或`exit_node`，实现"提前结束整个agent"或者"重新回到循环开头"这类HITL/异常处理场景。
2. **多middleware的链式顺序，`before_X`和`after_X`方向相反**——`before_agent`/`before_model`按注册顺序正序串联（第一个注册的离入口最近）；`after_model`/`after_agent`按注册顺序**反序**串联（最后注册的离`model`最近）。直觉上可以类比装饰器套娃：最后包上去的middleware，进入时最晚生效、退出时最早生效。

### 六个节点分别做了什么（逐个读源码验证过）

| 节点 | 图上角色 | 框架默认行为 | 官方内置middleware的真实用法 |
|---|---|---|---|
| `M.before_agent` | 入口，整个agent只跑一次 | 提供了Hook，框架本身不实现具体逻辑，留给开发者挂自己的中间件 | 开启一个新会话（比如shell工具中间件会在这里启动一个shell进程，供后面所有工具调用复用） |
| `M.before_model` | 循环入口，每轮对话开始前都会经过 | 同样提供了Hook | 请求模型之前的把关：查有没有超过调用次数上限（超了就提前结束或报错）；对话太长时先做一次摘要压缩，省token；检查并脱敏用户刚发来的敏感信息 |
| `model` | 核心节点，固定存在 | 把系统提示词、工具列表、当前对话历史拼成一次真正的模型请求并发出去，拿到回复后解析成标准格式；只管执行，不做任何"接下来去哪"的路由判断 | 框架允许在这一步前后包一层自定义逻辑（比如重试、记录日志），但明确不允许在这里做流程跳转，跳转只能交给前后的把关节点 |
| `tools` | 仅在配置了工具时存在 | 一次性并发执行模型请求的所有工具调用，给每个工具按需提供当前状态/存储等运行时数据；某个工具跑挂了会转成一条报错消息还给模型，不会导致整个流程崩掉 | 官方没有专门在这一步加逻辑，纯粹是框架自带能力；"要不要工具跑完就直接结束"这类判断不在这一步做，而是紧跟其后单独判断 |
| `M.after_model` | 循环出口，每轮对话结束后都会经过 | 同样提供了Hook | 模型给出回复之后的把关：拦下需要人工确认的敏感操作，暂停下来等人类批准/拒绝/修改后再继续；给调用计数器累加，累计次数超过上限就直接结束整个agent |
| `M.after_agent` | 出口，整个agent只跑一次 | 同样提供了Hook | 收尾清理（比如shell工具中间件会在这里关掉`before_agent`开的那个会话、释放资源，并且保证就算前面出错了这一步也一定会执行） |

一个共同规律：**四个把关节点（`before_agent`/`before_model`/`after_model`/`after_agent`）在框架层面全是空的，具体做什么完全取决于开发者挂了什么中间件；而`model`和`tools`这两个"真正干活"的节点，都遵循"节点只管执行、下一步去哪交给紧跟其后的判断逻辑"这一设计原则。**

## 跟`create_react_agent`对照，变化点小结

| | `create_react_agent`（已废弃） | `create_agent`（现在推荐） |
|---|---|---|
| 所在包 | `langgraph.prebuilt` | `langchain.agents` |
| 定制机制 | `pre_model_hook` / `post_model_hook`两个单点钩子 | 一整套可组合的`middleware`系统 |
| `response_format` | 裸schema或`(prompt, schema)`元组 | 包了一层`ToolStrategy`/`ProviderStrategy`抽象 |
| `state_schema`扩展方式 | 直接传自定义`TypedDict` | 官方建议优先通过middleware扩展，保持state改动跟具体hook/工具绑定 |
| 图的核心循环拓扑 | agent节点 ↔ tools节点，条件边判断`tool_calls` | 完全一样，没变 |
