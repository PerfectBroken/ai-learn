# Graph API overview（LangGraph）

来源：[Graph API overview - Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/graph-api)（官方文档，从GitHub仓库`langchain-ai/docs`拉取的原始mdx源码翻译，避免网页版被摘要）

> 说明：原文每一段都有Python/JavaScript两套并行示例，这里**只保留Python版本**（这是我们一直在用的语言，两套内容概念完全一致，没必要重复看两遍）。原文里有一段"Untracked values"和"Type utilities"（`GraphNode`/`State.Node`/`ConditionalEdgeRouter`等）**只有JavaScript版本、没有对应的Python内容**，因此这两节被跳过，不是翻译遗漏。

## Graphs（图）

**LangGraph的核心是把agent工作流建模成一张图**。你用三个关键组件定义agent的行为：

1. **`State`（状态）**：一个共享的数据结构，代表你的应用当前的快照。可以是任意数据类型，但通常用一个共享的state schema来定义。
2. **`Nodes`（节点）**：编码agent逻辑的函数。它们接收当前state作为输入，执行一些计算或副作用，返回更新后的state。
3. **`Edges`（边）**：根据当前state判断接下来该执行哪个`Node`的函数。可以是条件分支，也可以是固定的转移。

通过组合`Nodes`和`Edges`，你可以搭建出复杂的、会循环的工作流，让state随时间演变。但真正的威力在于LangGraph怎么管理这份state。

**要强调的是**：`Nodes`和`Edges`说到底就是函数——它们可以包一个LLM调用，也可以就是普通代码。

一句话概括：**节点负责干活，边负责告诉下一步该去哪**。

**LangGraph底层的图算法用的是[消息传递](https://en.wikipedia.org/wiki/Message_passing)机制来定义一个通用程序**。一个Node执行完，会沿着一条或多条边把消息发给其他节点。这些接收节点执行各自的函数，把产出的消息传给下一批节点，如此循环。这套机制受Google的[Pregel](https://research.google/pubs/pregel-a-system-for-large-scale-graph-processing/)系统启发，整个程序按离散的"**超步（super-step）**"推进。

一个超步可以理解成对图节点的**一轮**迭代。并行执行的节点属于同一个超步；顺序执行的节点属于不同的超步。图开始执行时，所有节点都处于`inactive`（不活跃）状态。当一个节点在自己的任意一条入边（或者说"通道"）上收到新消息（state）时，就会变成`active`（活跃）状态，然后运行自己的函数、返回更新。**每个超步结束时，没有收到入站消息的节点会投票`halt`（停止），把自己标记为`inactive`**。当所有节点都变成`inactive`、并且没有任何消息还在传输中时，图执行就终止了。

### `StateGraph`

`StateGraph`类是要用的主要图类，用一个用户自定义的`State`对象来参数化。

### 编译你的图

搭图的流程是：先定义[state](#state)，再加[nodes](#nodes)和[edges](#edges)，最后编译它。编译这一步具体做了什么、为什么需要？

编译是很简单的一步——它对图的结构做几项基本检查（比如有没有孤立节点等），同时也是你能指定运行时参数（比如[checkpointer](/oss/langgraph/persistence)和断点）的地方。调用`.compile`方法来编译图：

```python
graph = graph_builder.compile(...)
```

> **警告**：你**必须**先编译图，才能使用它。

## State（状态）

定义图时第一件要做的事，就是定义图的`State`。`State`由[图的schema](#schema)和[`reducer`函数](#reducers)组成——后者规定了怎么把更新应用到state上。`State`的schema会是图里所有`Nodes`和`Edges`的输入schema，可以是`TypedDict`，也可以是`Pydantic`模型。所有`Nodes`都会对`State`发出更新，这些更新会用指定的`reducer`函数来应用。

### Schema

官方文档里主要推荐的定义图schema的方式是用[`TypedDict`](https://docs.python.org/3/library/typing.html#typing.TypedDict)。如果你想在state里提供默认值，用[`dataclass`](https://docs.python.org/3/library/dataclasses.html)。也支持用Pydantic的[`BaseModel`](/oss/langgraph/use-graph-api#use-pydantic-models-for-graph-state)当图state（如果你需要递归的数据校验的话，不过要注意Pydantic比`TypedDict`或`dataclass`性能差一些）。

默认情况下，图的输入schema和输出schema是同一个。如果想改变这一点，你也可以直接指定显式的输入/输出schema——当你的key很多、有些明确是输入用、有些明确是输出用时，这个功能很有用。

> **提示**：`langchain`里更高层的[`create_agent`](/oss/langchain/agents)工厂函数**不支持**Pydantic的state schema。

#### 多重schema

通常来说，图里所有节点都用同一套schema通信——也就是说它们读写的是同一批state通道。但有些情况下我们想对这件事做更精细的控制：

- 内部节点之间可能需要传递一些不需要出现在图的输入/输出里的信息。
- 我们可能想给图用不同的输入/输出schema——比如输出可能只需要包含一个相关的key。

节点内部可以往**私有state通道**写数据，用于图内部节点间的通信——只需要定义一个私有schema，`PrivateState`。也可以给图定义显式的输入/输出schema——这种情况下，我们定义一个包含所有图操作相关key的"内部"schema，同时定义`input`和`output`两个schema，作为这个"内部"schema的子集，用来约束图的输入和输出。

来看一个例子：

```python
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class InputState(TypedDict):
    user_input: str


class OutputState(TypedDict):
    graph_output: str


class OverallState(TypedDict):
    foo: str
    user_input: str
    graph_output: str


class PrivateState(TypedDict):
    bar: str


def node_1(state: InputState) -> OverallState:
    # Write to OverallState
    return {"foo": state["user_input"] + " name"}


def node_2(state: OverallState) -> PrivateState:
    # Read from OverallState, write to PrivateState
    return {"bar": state["foo"] + " is"}


def node_3(state: PrivateState) -> OutputState:
    # Read from PrivateState, write to OutputState
    return {"graph_output": state["bar"] + " Lance"}


builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
builder.add_node("node_1", node_1)
builder.add_node("node_2", node_2)
builder.add_node("node_3", node_3)
builder.add_edge(START, "node_1")
builder.add_edge("node_1", "node_2")
builder.add_edge("node_2", "node_3")
builder.add_edge("node_3", END)

graph = builder.compile()
graph.invoke({"user_input": "My"})
# {'graph_output': 'My name is Lance'}
```

这里有两个微妙但重要的点：

1. 我们把`state: InputState`作为输入schema传给`node_1`，但它写出到`foo`——`OverallState`里的一个通道。为什么能写到一个不在输入schema里的state通道？因为**一个节点可以写图state里的任何通道**。图state是初始化时定义的所有state通道的**并集**，包括`OverallState`以及`InputState`/`OutputState`这两个过滤器。
2. 我们用`StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)`初始化图。那`node_2`怎么能写`PrivateState`？如果`PrivateState`根本没在`StateGraph`初始化时传进去，图是怎么拿到这个schema的访问权的？——因为**只要这个state schema定义存在，节点就可以声明额外的state通道**。这里`PrivateState`这个schema是定义好的，所以我们可以把`bar`当成一个新的state通道加进图里，直接写它。

> **警告：私有通道在流式输出时不会被隐藏。** 输入、输出、私有schema约束的是每个节点**读什么**（它的输入schema）、以及`invoke`**返回什么**（输出schema）——它们**不会**把通道从`stream`里隐藏掉。用`stream_mode="values"`做流式输出时，图默认会吐出**全部**state通道，包括私有的，因为values流式输出默认对齐的是全部state通道集合、而不是输出schema。这就是为什么`bar`这个私有通道被`invoke`隐藏了、但在流式输出时却能看到：
>
> ```python
> stream = graph.stream_events({"user_input": "My"}, version="v3")
> for snapshot in stream.values:
>     print(snapshot)
> # {'user_input': 'My'}
> # {'foo': 'My name', 'user_input': 'My'}
> # {'foo': 'My name', 'user_input': 'My', 'bar': 'My name is'}        # <-- private channel
> # {'foo': 'My name', 'user_input': 'My', 'graph_output': 'My name is Lance', 'bar': 'My name is'}
> ```
>
> 想把流式输出限制到一组特定通道（比如只要输出schema），传`output_keys`：
>
> ```python
> stream = graph.stream_events(
>     {"user_input": "My"},
>     version="v3",
>     output_keys=["graph_output"],
> )
> for snapshot in stream.values:
>     print(snapshot)
> # {'graph_output': 'My name is Lance'}
> ```
>
> 如果你只需要每一步节点**实际产出**的那部分通道（而不是完整累积的state），改用`stream_mode="updates"`。

### Reducers（归约器）

**Reducer是理解"节点的更新怎么被应用到`State`上"的关键**。`State`里每个key都有自己独立的reducer函数。如果没有显式指定reducer函数，就默认对这个key的所有更新都是**覆盖**。

#### Reducer参数

每个reducer都是一个接受两个位置参数的二元函数：

- **左参数**：这个key当前已经存在state里的值。
- **右参数**：节点返回的、针对这个key的更新。

当节点返回一次部分更新时，LangGraph会为每个被更新的key调用对应的reducer，把返回值存成新的state值：

```python
new_value = reducer(left=current_state[key], right=node_update[key])
```

左参数永远来自累积的state，右参数永远来自最新一次节点更新。下面这个例子把两个参数都显式命名了：

```python
from typing import Annotated

from typing_extensions import TypedDict


def append_strings(left: list[str], right: list[str]) -> list[str]:
    """Combine the existing state value (left) with a node update (right)."""
    return left + right


class State(TypedDict):
    tags: Annotated[list[str], append_strings]
```

假设state是`{"tags": ["draft"]}`，某个节点返回`{"tags": ["review"]}`，LangGraph会调用：

```python
append_strings(left=["draft"], right=["review"])  # returns ["draft", "review"]
```

`tags`的新state值就是`["draft", "review"]`。

自定义reducer会**合并**左右两个参数；[默认reducer](#默认reducer)则会丢弃左参数、只保留右参数。

#### 默认reducer

默认reducer会忽略左参数，直接用右参数替换state值：

```python
from typing_extensions import TypedDict


class State(TypedDict):
    foo: int
    bar: list[str]
```

这个例子里没有为任何key指定reducer函数。假设图的输入是`{"foo": 1, "bar": ["hi"]}`，第一个`Node`返回`{"foo": 2}`——这被当成一次state更新（注意`Node`不需要返回整个`State` schema，只需要返回更新的那部分）。应用这次更新后，`State`会变成`{"foo": 2, "bar": ["hi"]}`。如果第二个节点返回`{"bar": ["bye"]}`，`State`就会变成`{"foo": 2, "bar": ["bye"]}`。

#### 自定义reducer

自定义reducer会把左右参数**合并**、而不是替换state值，这对累积值（比如往列表里追加更新）很有用：

```python
from operator import add
from typing import Annotated

from typing_extensions import TypedDict


class State(TypedDict):
    foo: int
    bar: Annotated[list[str], add]
```

这个例子用`Annotated`类型给第二个key（`bar`）指定了一个reducer函数（`operator.add`），第一个key保持不变。假设输入是`{"foo": 1, "bar": ["hi"]}`，第一个`Node`返回`{"foo": 2}`，应用后`State`变成`{"foo": 2, "bar": ["hi"]}`。如果第二个节点返回`{"bar": ["bye"]}`，`State`会变成`{"foo": 2, "bar": ["hi", "bye"]}`——注意这里`bar`是把两个列表**加在一起**更新的。

#### Overwrite（绕开reducer直接覆盖）

有些场景下你可能想绕开reducer、直接覆盖一个state值。LangGraph为此提供了[`Overwrite`](https://reference.langchain.com/python/langgraph/types/)类型。

### 在图state里使用消息

#### 为什么要用消息？

大多数现代LLM provider的chat model接口，接受的输入是一个消息列表。LangChain的[chat model接口](/oss/langchain/models)接受的正是一个消息对象列表，这些消息有多种形式，比如`HumanMessage`（用户输入）或`AIMessage`（LLM响应）。

#### 在图里使用消息

很多情况下，把之前的对话历史存成一个消息列表放进图state里会很有帮助。做法是给图state加一个key（通道），存`Message`对象列表，并给它标注一个reducer函数（见下面例子里的`messages`key）。这个reducer函数至关重要——它告诉图每次state更新时该怎么更新这个`Message`对象列表。如果不指定reducer，每次state更新都会用最新提供的值**整个覆盖**消息列表。如果你只是想把消息追加到已有列表，可以用`operator.add`当reducer。

但你也可能想手动更新图state里的消息（比如人在回路场景）。如果用`operator.add`，你发给图的手动state更新会被**追加**到已有消息列表末尾，而不是**更新**已有的消息。为了避免这个问题，你需要一个能追踪消息ID、并在消息被更新时覆盖已有消息的reducer——这正是内置的`add_messages`函数要做的事：对全新的消息，它会正常追加进已有列表；但也能正确处理对已有消息的更新。

#### 序列化

除了追踪消息ID，`add_messages`函数还会在`messages`通道收到state更新时，尝试把消息反序列化成LangChain的`Message`对象。这让下面两种格式的图输入/state更新都能被支持：

```python
# this is supported
{"messages": [HumanMessage(content="message")]}

# and this is also supported
{"messages": [{"type": "human", "content": "message"}]}
```

由于用`add_messages`时state更新总是会被反序列化成LangChain的`Messages`，你应该用点号写法访问消息属性，比如`state["messages"][-1].content`。

下面是一个用`add_messages`当reducer的图示例：

```python
from langchain.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing import Annotated
from typing_extensions import TypedDict

class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

#### `MessagesState`

因为"state里放一份消息列表"这种需求太常见了，LangGraph内置了一个叫`MessagesState`的预制state，让使用消息更方便。`MessagesState`就定义了一个`messages`key（`AnyMessage`对象列表），用`add_messages`当reducer。通常还需要追踪消息以外的更多state，所以大家一般会继承这个state、再加更多字段：

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]
```

#### 深挖：`add_messages`的合并逻辑到底怎么实现的（非原文翻译，查源码补充）

官方文档只说了"对全新消息会追加，对已有消息会正确处理更新"，没说具体怎么做的。去查了`langgraph/graph/message.py`里`add_messages`的源码，核心合并逻辑是这样的：

```python
merged = left.copy()
merged_by_id = {m.id: i for i, m in enumerate(merged)}
ids_to_remove = set()
for m in right:
    if (existing_idx := merged_by_id.get(m.id)) is not None:
        if isinstance(m, RemoveMessage):
            ids_to_remove.add(m.id)
        else:
            ids_to_remove.discard(m.id)
            merged[existing_idx] = m          # ← 关键这一行
    else:
        merged_by_id[m.id] = len(merged)
        merged.append(m)
merged = [m for m in merged if m.id not in ids_to_remove]
```

**关键在`merged[existing_idx] = m`这一行**——先算出旧消息在`left`（已有消息列表）里的**下标**，然后对这个下标做**原地赋值**，把新消息换上去。也就是说，**如果两条消息id相同，旧消息后面（以及前面）的所有其他消息都会被完整保留、位置不变**，只有匹配到的那一个下标被替换——不是"丢弃匹配点之后的历史"，也不是"把新消息拼到列表末尾"。

举例：假设`messages`是`[msg_1, msg_2(id=123), msg_3, msg_4]`，往里合并一条id同样是`123`、内容不同的新消息，结果是`[msg_1, msg_2'(id=123，内容变了), msg_3, msg_4]`——`msg_3`、`msg_4`原封不动。

**另外两个相关但不同的机制，也在这份源码里**：

- **真正删除一条消息**：往`right`里传`RemoveMessage(id=xxx)`，这个id会被记进`ids_to_remove`，最后那行列表推导式会把它从`merged`里**过滤掉**——这是删除，不是替换。
- **清空整个历史重新开始**：如果`right`里出现`RemoveMessage(id=REMOVE_ALL_MESSAGES)`这个特殊标记，函数会直接`return right[remove_all_idx + 1:]`，**完全无视`left`**，只保留这个标记之后的新消息——这是整个列表推倒重来，跟前面两种"只动一条"的操作完全不是一个量级。

## Nodes（节点）

在LangGraph里，节点是Python函数（同步或异步都行），接受以下参数：

1. **`state`**——图的[state](#state)
2. **`config`**——一个`RunnableConfig`对象，包含`thread_id`这类配置信息，也包含`tags`这类追踪信息
3. **`runtime`**——一个`Runtime`对象，包含[运行时`context`](#runtime-context)以及`store`、`stream_writer`、`execution_info`、`server_info`、`heartbeat`（用于刷新空闲超时）、`control`（用于[优雅停机](/oss/langgraph/fault-tolerance#graceful-shutdown)）等其他信息

类似`NetworkX`，用`add_node`方法把这些节点加进图里：

```python
from dataclasses import dataclass
from typing_extensions import TypedDict

from langgraph.graph import StateGraph
from langgraph.runtime import Runtime

class State(TypedDict):
    input: str
    results: str

@dataclass
class Context:
    user_id: str

builder = StateGraph(State)

def plain_node(state: State):
    return state

def node_with_runtime(state: State, runtime: Runtime[Context]):
    print("In node: ", runtime.context.user_id)
    return {"results": f"Hello, {state['input']}!"}

def node_with_execution_info(state: State, runtime: Runtime):
    print("In node with thread_id: ", runtime.execution_info.thread_id)
    return {"results": f"Hello, {state['input']}!"}


builder.add_node("plain_node", plain_node)
builder.add_node("node_with_runtime", node_with_runtime)
builder.add_node("node_with_execution_info", node_with_execution_info)
...
```

底层实现上，这些函数会被转换成`RunnableLambda`，这会给你的函数加上批处理和异步支持，还带[原生的追踪和调试能力](/langsmith/observability)。

如果给图加节点时没指定名字，会用函数名当默认名字：

```python
builder.add_node(my_node)
# You can then create edges to/from this node by referencing it as `"my_node"`
```

### 重新执行与幂等性

配了[checkpointer](/oss/langgraph/persistence)编译图之后，LangGraph会在[超步](#graphs)边界保存checkpoint，**不是在节点函数内部中途保存**。如果执行停止后又恢复了（比如经历了一次[interrupt](/oss/langgraph/interrupts)或一次[重试](/oss/langgraph/fault-tolerance#retries)），受影响的**节点**会从它函数的**开头**重新跑一遍——暂停之前的代码和副作用都会重新执行一次。

**幂等性**：设计节点逻辑时要考虑到重新执行不能破坏state。如果一个节点会往数据库插一行数据，跑两次不应该产生重复行（除非这是故意的）。用幂等键、upsert、或者写之前先读一遍这类手段。

**图的改动**：关于代码改动的[确定性](/oss/langgraph/functional-api#determinism)规则不适用于图结构本身——你可以增删**节点**和边，不会破坏已有线程的恢复能力。恢复运行时用的是已保存的state，执行的是你**现在**编译出来的图，不管图结构改没改。

**节点内部的task和interrupt**：如果一个**节点**调用了[**task**](/oss/langgraph/functional-api#task)或`interrupt`，恢复时会有更严格的确定性规则生效。LangGraph会从checkpointer里恢复已完成的**task**结果，但如果在恢复点之前改动了代码里task或`interrupt`的调用顺序，可能会跟缓存的值对不上。[Functional API](/oss/langgraph/functional-api)的**entrypoint**会被编译成一个单独的**节点**，以这种方式运行整个entrypoint方法。

### 在节点内使用task

如果一个[节点](#nodes)包含多个操作，你可能会发现把每个操作实现成一个[**task**](/oss/langgraph/functional-api#task)、而不是把逻辑拆到多个节点里，会更方便。当图配了checkpointer时，task结果会被checkpoint，所以恢复一个线程时可以跳过节点内部已经完成的task工作。

**原始写法（不用task）**：

```python
from typing import NotRequired

import requests
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class State(TypedDict):
    url: str
    result: NotRequired[str]


def call_api(state: State):
    """Example node that makes an API request."""
    result = requests.get(state["url"]).text[:100]
    return {"result": result}


builder = StateGraph(State)
builder.add_node("call_api", call_api)
builder.add_edge(START, "call_api")
builder.add_edge("call_api", END)

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

thread_id = str(uuid7())
config = {"configurable": {"thread_id": thread_id}}

graph.invoke({"url": "https://www.example.com"}, config)
```

**用task改写（每个请求单独checkpoint，可以并行、可以按task粒度恢复）**：

```python
from typing import NotRequired

import requests
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.func import task
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


class State(TypedDict):
    urls: list[str]
    results: NotRequired[list[str]]


@task
def _make_request(url: str):
    """Make a request."""
    return requests.get(url).text[:100]


def call_api(state: State):
    """Example node that makes API requests as checkpointed tasks."""
    futures = [_make_request(url) for url in state["urls"]]
    results = [f.result() for f in futures]
    return {"results": results}


builder = StateGraph(State)
builder.add_node("call_api", call_api)
builder.add_edge(START, "call_api")
builder.add_edge("call_api", END)

checkpointer = InMemorySaver()
graph = builder.compile(checkpointer=checkpointer)

thread_id = str(uuid7())
config = {"configurable": {"thread_id": thread_id}}

graph.invoke({"urls": ["https://www.example.com"]}, config)
```

### `START`节点

`START`节点是一个特殊节点，代表"把用户输入发给图"这个节点。引用它主要是为了确定哪些节点该被最先调用：

```python
from langgraph.graph import START

graph.add_edge(START, "node_a")
```

### `END`节点

`END`节点是一个特殊节点，代表一个终止节点——想标明某条边执行完之后就没有后续动作时，引用它：

```python
from langgraph.graph import END

graph.add_edge("node_a", END)
```

### 节点缓存

LangGraph支持基于节点输入做task/node级别的缓存。用法：

- 编译图（或指定entrypoint）时指定一个cache
- 给节点指定一个cache policy，每个cache policy支持：
  - `key_func`：根据节点输入生成缓存key的函数，默认是对输入做pickle后取hash
  - `ttl`：缓存的存活时间（秒），不指定就永不过期

例子：

```python
import time
from typing_extensions import TypedDict
from langgraph.graph import StateGraph
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy


class State(TypedDict):
    x: int
    result: int


builder = StateGraph(State)


def expensive_node(state: State) -> dict[str, int]:
    # expensive computation
    time.sleep(2)
    return {"result": state["x"] * 2}


builder.add_node("expensive_node", expensive_node, cache_policy=CachePolicy(ttl=3))
builder.set_entry_point("expensive_node")
builder.set_finish_point("expensive_node")

graph = builder.compile(cache=InMemoryCache())

print(graph.invoke({"x": 5}, stream_mode='updates'))
# [{'expensive_node': {'result': 10}}]
print(graph.invoke({"x": 5}, stream_mode='updates'))
# [{'expensive_node': {'result': 10}, '__metadata__': {'cached': True}}]
```

> **说明**：`set_entry_point(node)`定义图要执行的第一个节点，等价于`builder.add_edge(START, node)`；`set_finish_point(node)`定义图的最后一个节点，等价于`builder.add_edge(node, END)`。两种写法都有效，但`add_edge(START, ...)`和`add_edge(..., END)`是推荐的现代写法。

第一次运行耗时2秒（模拟的耗时计算）；第二次运行命中缓存，很快返回。

## Edges（边）

边定义了逻辑怎么被路由、图怎么决定停止——这是agent怎么运作、不同节点怎么互相通信的重要组成部分。有几种关键的边类型：

- **普通边（Normal Edges）**：直接从一个节点走到下一个。
- **条件边（Conditional Edges）**：调用一个函数决定接下来走哪个/哪些节点。
- **入口点（Entry Point）**：用户输入到达时，第一个调用的节点。
- **条件入口点（Conditional Entry Point）**：调用一个函数决定用户输入到达时第一个该调用哪个/哪些节点。

一个节点可以有多条出边。如果一个节点有多条出边，**所有**这些目标节点都会作为下一个超步的一部分**并行**执行。

> **警告**：对每个节点，选一种路由机制就好——要么用普通边做静态路由，要么用条件边/`Command`做动态路由。不要在同一个节点上混用普通边和动态路由，因为两条路径都可能执行，会让图的行为更难推理。

### 普通边

如果你**总是**想从节点A走到节点B，直接用`add_edge`方法：

```python
graph.add_edge("node_a", "node_b")
```

### 条件边

如果你想**有条件地**路由到一个或多个边（或者有条件地终止），用`add_conditional_edges`方法。这个方法接受一个节点名，和一个在该节点执行完之后要调用的"路由函数"：

```python
graph.add_conditional_edges("node_a", routing_function)
```

跟节点类似，`routing_function`接受图当前的`state`，返回一个值。默认情况下，`routing_function`的返回值会被当成下一步要把state发给哪个节点（或哪些节点）的名字，所有这些节点都会作为下一个超步的一部分并行运行。

你也可以传一个字典，把`routing_function`的输出映射到下一个节点的名字：

```python
graph.add_conditional_edges("node_a", routing_function, {True: "node_b", False: "node_c"})
```

> **提示**：如果你想在一个函数里同时做state更新和路由，用[`Command`](#command)代替条件边。

### 入口点

入口点是图启动时第一个（或第一批）运行的节点。用`add_edge`方法，从虚拟的`START`节点连到第一个要执行的节点，来指定图从哪里进入：

```python
from langgraph.graph import START

graph.add_edge(START, "node_a")
```

### 条件入口点

条件入口点让你可以根据自定义逻辑，从不同的节点开始执行。用`add_conditional_edges`从虚拟的`START`节点出发即可实现：

```python
from langgraph.graph import START

graph.add_conditional_edges(START, routing_function)
```

同样可以传一个字典，把`routing_function`的输出映射到下一个节点的名字：

```python
graph.add_conditional_edges(START, routing_function, {True: "node_b", False: "node_c"})
```

## `Send`

默认情况下，`Nodes`和`Edges`是提前定义好的，作用在同一份共享state上。但有些场景下，具体的边事先并不知道，和/或你可能想让`State`同时存在不同的版本。一个常见的例子是[map-reduce](/oss/langgraph/use-graph-api#map-reduce-and-the-send-api)设计模式——第一个节点可能产出一个对象列表，你想对所有这些对象都跑另一个节点。对象的数量可能事先未知（意味着边的数量也事先未知），而且下游`Node`的输入`State`应该是不同的（每个生成对象对应一份）。

为了支持这种设计模式，LangGraph支持从条件边里返回`Send`对象。`Send`接受两个参数：第一个是节点名，第二个是要传给该节点的state：

```python
from langgraph.types import Send

def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state['subjects']]

graph.add_conditional_edges("node_a", continue_to_jokes)
```

## `Command`

`Command`是一个用来控制图执行的、用途广泛的原语。它接受四个参数：

- **`update`**：应用state更新（类似从节点返回更新）。
- **`goto`**：导航到特定节点（类似[条件边](#条件边)）。
- **`graph`**：从[subgraph](/oss/langgraph/use-subgraphs)导航时，指定父图为目标。
- **`resume`**：在[interrupt](/oss/langgraph/interrupts)之后提供一个值来恢复执行。

`Command`会在三种场景下用到：

- **[从节点返回](#从节点返回)**：用`update`、`goto`、`graph`把state更新和控制流结合在一起。
- **[作为`invoke`或`stream`的输入](#作为invoke或stream的输入)**：用`resume`在interrupt之后继续执行。
- **[从工具返回](#从工具返回)**：跟从节点返回类似，在工具内部把state更新和控制流结合起来。

### 从节点返回

#### `update`和`goto`

从节点函数里返回`Command`，一步同时完成"更新state"和"路由到下一个节点"：

```python
def my_node(state: State) -> Command[Literal["my_other_node"]]:
    return Command(
        # state update
        update={"foo": "bar"},
        # control flow
        goto="my_other_node"
    )
```

用`Command`同样可以实现动态控制流（跟[条件边](#条件边)效果一致）：

```python
def my_node(state: State) -> Command[Literal["my_other_node"]]:
    if state["foo"] == "bar":
        return Command(update={"foo": "baz"}, goto="my_other_node")
```

当你需要**同时**更新state**和**路由到另一个节点时，用`Command`；如果只是需要路由、不需要更新state，用[条件边](#条件边)就够了。

> **说明**：在节点函数里返回`Command`时，必须加上返回类型标注，列出这个节点可能路由到的节点名列表，比如`Command[Literal["my_other_node"]]`——这对图的渲染是必要的，也是在告诉LangGraph`my_node`可以导航到`my_other_node`。

> **警告**：`Command`只会**新增**动态边——用`add_edge`定义的静态边照样会执行。举个例子，如果`node_a`返回`Command(goto="my_other_node")`，同时你还定义了`graph.add_edge("node_a", "node_b")`，那么`node_b`和`my_other_node`**都会**运行。对每个节点，要么用`Command`、要么用静态边路由到下一批节点，不要两个都用。

#### `graph`

如果你在用[subgraph](/oss/langgraph/use-subgraphs)，可以在`Command`里指定`graph=Command.PARENT`，从subgraph内部的一个节点导航到父图里的另一个节点：

```python
def my_node(state: State) -> Command[Literal["other_subgraph"]]:
    return Command(
        update={"foo": "bar"},
        goto="other_subgraph",  # where `other_subgraph` is a node in the parent graph
        graph=Command.PARENT
    )
```

> **说明**：把`graph`设成`Command.PARENT`会导航到最近的父图。当你从subgraph节点往父图节点发更新、且这个key在父图和subgraph的[state schema](#schema)里都存在时，**必须**在父图state里为这个key定义[reducer](#reducers)。

这个机制在实现[multi-agent handoffs](/oss/langchain/multi-agent/handoffs)时特别有用。

### 作为`invoke`或`stream`的输入

> **警告**：`Command(resume=...)`是**唯一**适合当作`invoke()`/`stream()`输入的`Command`模式（可以配合`update=...`在恢复时顺便应用一次state变更）。**不要**单独用`Command(update=...)`作为输入来延续多轮对话——因为把任何`Command`当输入传进去，都会从**最近一次checkpoint**（也就是上次跑到的那一步，不是`__start__`）恢复执行，如果图已经跑完了，看起来就会像卡住了。要在一个已有线程上继续对话，应该传一个普通的输入dict：
>
> ```python
> # 错误——图会从最近一次checkpoint恢复（上次跑到的那一步），看起来像卡住了
> graph.invoke(Command(update={
>     "messages": [{"role": "user", "content": "follow up"}]
> }), config)
>
> # 正确——普通dict会从__start__重新开始
> graph.invoke({
>     "messages": [{"role": "user", "content": "follow up"}]
> }, config)
> ```

#### `resume`

用`Command(resume=...)`提供一个值，在[interrupt](/oss/langgraph/interrupts)之后恢复图的执行。传给`resume`的值，会变成暂停节点内部`interrupt()`调用的返回值：

```python
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class State(TypedDict):
    messages: list[dict]


def human_review(state: State):
    # Pauses the graph and waits for a value
    answer = interrupt("Do you approve?")
    return {"messages": [{"role": "user", "content": answer}]}


graph = (
    StateGraph(State)
    .add_node("human_review", human_review)
    .add_edge(START, "human_review")
    .add_edge("human_review", END)
    .compile(checkpointer=InMemorySaver())
)

config = {"configurable": {"thread_id": "graph-api-resume"}}

# First run - hits the interrupt and pauses
stream = graph.stream_events({"messages": []}, config, version="v3")
_ = stream.output  # drive the stream to completion
print(stream.interrupts)

# Resume with a value - the interrupt() call returns "yes"
resumed = graph.stream_events(Command(resume="yes"), config, version="v3")
final = resumed.output
```

### 从工具返回

可以从工具里返回`Command`，用来更新图state和控制流——用`update`修改state（比如保存对话过程中查到的客户信息），用`goto`在工具执行完之后路由到指定节点。

> **警告**：在工具内部使用时，`goto`会新增一条动态边——调用这个工具的节点上已经定义好的静态边照样会执行。对每个节点，要么用工具驱动的动态路由、要么用静态边路由到下一批节点，不要两个都用。

## 图迁移

即便用了checkpointer追踪state，LangGraph也能轻松处理图定义（节点、边、state）的迁移：

- 对于已经走到图末尾（也就是没有被中断）的线程，你可以改变图的整个拓扑（所有节点和边——删除、新增、改名都行）。
- 对于当前正被中断的线程，除了给节点改名/删除节点之外的所有拓扑改动都支持（因为那个线程可能正准备进入一个已经不存在的节点）。
- 对于state的改动，新增和删除key有完整的向前向后兼容性。
- 被改名的state key会丢失已有线程里保存的state。
- state key的类型如果发生不兼容的变化，可能会让改动之前就有state的线程出问题。

## Runtime context（运行时上下文）

创建图时，可以指定一个`context_schema`，用来给节点传运行时上下文——这对传递一些不属于图state的信息很有用，比如你可能想传model名称、数据库连接这类依赖：

```python
@dataclass
class ContextSchema:
    llm_provider: str = "openai"

graph = StateGraph(State, context_schema=ContextSchema)
```

然后可以通过`invoke`方法的`context`参数，把这份上下文传进图里：

```python
graph.invoke(inputs, context={"llm_provider": "anthropic"})
```

在节点或条件边内部访问和使用这份上下文：

```python
from langgraph.runtime import Runtime

def node_a(state: State, runtime: Runtime[ContextSchema]):
    llm = get_llm(runtime.context.llm_provider)
    # ...
```

### 递归限制（Recursion limit）

递归限制设定了图在**一次执行**里最多能跑多少个[超步](#graphs)。一旦超过这个限制，LangGraph会抛出`GraphRecursionError`。从1.0.6版本起，默认递归限制是1000步。可以在运行时给任意图设置递归限制，通过`invoke`/`stream`的config字典传入。**重要的是**，`recursion_limit`是一个独立的`config`顶层key，不应该像其他用户自定义配置那样塞进`configurable`这个key里面：

```python
graph.invoke(inputs, config={"recursion_limit": 5}, context={"llm": "anthropic"})
```

### 访问和处理递归计数器

**当前的步数计数器可以在任何节点内部通过`config["metadata"]["langgraph_step"]`访问到**，这让你能在真正碰到递归限制**之前**就主动处理它——可以在图逻辑里实现优雅降级策略。

#### 原理

步数计数器存在`config["metadata"]["langgraph_step"]`里。LangGraph在图执行过程中递增这个计数器，一旦超过配置好的`recursion_limit`就抛出`GraphRecursionError`。

#### 访问当前步数计数器

可以在任意节点内部访问当前步数计数器，监控执行进度：

```python
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph

def my_node(state: dict, config: RunnableConfig) -> dict:
    current_step = config["metadata"]["langgraph_step"]
    print(f"Currently on step: {current_step}")
    return state
```

#### 主动式递归处理

LangGraph提供一个`RemainingSteps`托管值（managed value），追踪距离碰到递归限制还剩多少步，让你能在图内部实现优雅降级：

```python
from typing import Annotated, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.managed import RemainingSteps

class State(TypedDict):
    messages: Annotated[list, lambda x, y: x + y]
    remaining_steps: RemainingSteps  # Managed value - tracks steps until limit

def reasoning_node(state: State) -> dict:
    # RemainingSteps is automatically populated by LangGraph
    remaining = state["remaining_steps"]

    # Check if we're running low on steps
    if remaining <= 2:
        return {"messages": ["Approaching limit, wrapping up..."]}

    # Normal processing
    return {"messages": ["thinking..."]}

def route_decision(state: State) -> Literal["reasoning_node", "fallback_node"]:
    """Route based on remaining steps"""
    if state["remaining_steps"] <= 2:
        return "fallback_node"
    return "reasoning_node"

def fallback_node(state: State) -> dict:
    """Handle cases where recursion limit is approaching"""
    return {"messages": ["Reached complexity limit, providing best effort answer"]}

# Build graph
builder = StateGraph(State)
builder.add_node("reasoning_node", reasoning_node)
builder.add_node("fallback_node", fallback_node)
builder.add_edge(START, "reasoning_node")
builder.add_conditional_edges("reasoning_node", route_decision)
builder.add_edge("fallback_node", END)

graph = builder.compile()

# RemainingSteps works with any recursion_limit
result = graph.invoke({"messages": []}, {"recursion_limit": 10})
```

#### 主动式 vs 被动式两种处理方式

处理递归限制主要有两种思路：**主动式**（在图内部监控）和**被动式**（在外部捕获报错）。

```python
from typing import Annotated, Literal, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.managed import RemainingSteps
from langgraph.errors import GraphRecursionError

class State(TypedDict):
    messages: Annotated[list, lambda x, y: x + y]
    remaining_steps: RemainingSteps

# Proactive Approach (recommended) - using RemainingSteps
def agent_with_monitoring(state: State) -> dict:
    """Proactively monitor and handle recursion within the graph"""
    remaining = state["remaining_steps"]

    # Early detection - route to internal handling
    if remaining <= 2:
        return {
            "messages": ["Approaching limit, returning partial result"]
        }

    # Normal processing
    return {"messages": [f"Processing... ({remaining} steps remaining)"]}

def route_decision(state: State) -> Literal["agent", END]:
    if state["remaining_steps"] <= 2:
        return END
    return "agent"

# Build graph
builder = StateGraph(State)
builder.add_node("agent", agent_with_monitoring)
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", route_decision)
graph = builder.compile()

# Proactive: Graph completes gracefully
result = graph.invoke({"messages": []}, {"recursion_limit": 10})

# Reactive Approach (fallback) - catching error externally
try:
    result = graph.invoke({"messages": []}, {"recursion_limit": 10})
except GraphRecursionError as e:
    # Handle externally after graph execution fails
    result = {"messages": ["Fallback: recursion limit exceeded"]}
```

两种方式的关键区别：

| 方式 | 检测时机 | 处理位置 | 控制流 |
|---|---|---|---|
| 主动式（用`RemainingSteps`） | 达到限制**之前** | 图**内部**，靠条件路由 | 图正常走到完成节点 |
| 被动式（捕获`GraphRecursionError`） | 超过限制**之后** | 图**外部**的try/catch | 图执行被终止 |

**主动式的优势**：
- 图内部就能优雅降级
- 可以把中间state存进checkpoint
- 能返回部分结果，用户体验更好
- 图正常跑完（不抛异常）

**被动式的优势**：
- 实现更简单
- 不需要改图的逻辑
- 报错处理集中在一处

#### 其他可用的元数据

除了`langgraph_step`，`config["metadata"]`里还有这些元数据可用：

```python
def inspect_metadata(state: dict, config: RunnableConfig) -> dict:
    metadata = config["metadata"]

    print(f"Step: {metadata['langgraph_step']}")
    print(f"Node: {metadata['langgraph_node']}")
    print(f"Triggers: {metadata['langgraph_triggers']}")
    print(f"Path: {metadata['langgraph_path']}")
    print(f"Checkpoint NS: {metadata['langgraph_checkpoint_ns']}")

    return state
```

## 可视化

图变复杂之后，能可视化经常很有用。LangGraph自带好几种内置的图可视化方式。

## 可观测性与追踪

要追踪、调试、评估你的agent，用[LangSmith](/langsmith/observability)。

## 延伸阅读

- [How to use the Graph API](/oss/langgraph/use-graph-api)
- [Functional API conceptual overview](/oss/langgraph/functional-api)
- [Choosing between Graph API and Functional API](/oss/langgraph/choosing-apis)
