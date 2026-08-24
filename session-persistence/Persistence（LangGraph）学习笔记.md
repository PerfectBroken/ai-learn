# Persistence（LangGraph）

来源：`docs.langchain.com/oss/python/langgraph/persistence`

> 这篇是概览页，篇幅很短，只有Quickstart/对比表/踩坑排查/下一步四块内容——专门核实过，页面里**没有**checkpoint结构细节、`get_state`/`get_state_history`、时间旅行、子图持久化、Store的`put`/`get`/`search`语义搜索这些内容，全都在它链接出去的两篇更详细的指南里：`Checkpointers`和`Stores`。`Checkpointers`的翻译接在下面；`Stores`翻译完之后核对发现它讲的是跨thread长期记忆，功能上不属于"会话持久化"，挪去了[context-window/Stores（LangGraph）学习笔记.md](../context-window/Stores（LangGraph）学习笔记.md)，跟`ContextWindow.md`的Write/长期记忆那节放在一起。

## 持久化概述

LangGraph的持久化层通过checkpointer提供短期记忆，通过store提供长期记忆。持久化让LangGraph应用能在单次图运行之外保留有用信息——agent要接着对话、要从中断里恢复、要从失败里恢复、要跨多次交互记住东西，都得靠它。

两个互补的持久化系统：

- **Checkpointer**——把一个thread的图state存成一个个checkpoint。用于短期、thread作用域的记忆：对话连续性、人在回路工作流、时间旅行、容错。
- **Store**——在图state之外，持久化应用自己定义的数据。用于长期、跨thread的记忆：用户偏好、事实、共享知识。

大多数应用两者都会用——checkpointer跟踪当前thread，store跟踪跨thread的持久信息。

## Quickstart

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

checkpointer = InMemorySaver()
store = InMemoryStore()

graph = builder.compile(checkpointer=checkpointer, store=store)

result = graph.invoke(
    {"messages": [{"role": "user", "content": "Hi, my name is Bob."}]},
    {"configurable": {"thread_id": "thread-1"}},
)
```

原文特别提示：用Agent Server（LangGraph的托管部署产品）时不需要手动实现/配置checkpointer或store，服务器自己在背后处理持久化基础设施。

## Checkpointer vs. Store对照表

| 维度 | Checkpointer | Store |
|---|---|---|
| 持久化的内容 | 图state快照 | 应用自定义的键值数据 |
| 作用范围 | 单个thread | 跨thread |
| 记忆类型 | 短期、thread作用域 | 长期、跨thread |
| 适用场景 | 对话连续性、人在回路、时间旅行、容错 | 用户偏好、事实、共享知识 |
| 怎么访问 | 图配置里传`thread_id` | 节点/应用代码里直接读写item |

## 常见踩坑（原文Troubleshooting，四条）

1. **`PostgresSaver`：`thread_id`太长**——用`PostgresSaver`/`AsyncPostgresSaver`时，`thread_id`存在一个长度有限的数据库列里，超长会报错。解决：`thread_id`控制在255字符以内，需要确定性ID就用UUID或哈希：
   ```python
   import uuid
   config = {"configurable": {"thread_id": str(uuid.uuid4())[:255]}}
   ```
2. **`MemorySaver`重启后不持久化**——`MemorySaver`/`InMemorySaver`把checkpoint存在RAM里，进程重启全部丢失。解决：生产环境用`PostgresSaver`（支持异步）或`SqliteSaver`（本地开发用文件存储）。
3. **checkpoint无限增长**——长对话里checkpoint不断累积，拖慢延迟、增加存储成本。解决：定期清理旧checkpoint或设置保留策略：
   ```python
   from langgraph.checkpoint.postgres import PostgresSaver
   checkpointer = PostgresSaver.from_conn_string("postgresql://...")
   checkpointer.setup()  # 建表+建索引
   ```
4. **父图访问不到子图的state**——子图更新了自己的state，父图可能看不到，因为每个子图管理自己独立的checkpoint命名空间。解决：跨图边界的数据用Store共享，或者配置子图把写入同步给父图的checkpoint。

## 下一步

原文指向两篇更详细的指南：用checkpointer持久化+查看thread state（→`Checkpointers`指南），用Store在thread间持久化数据（→`Stores`指南）。

## 值得记的点

- **Checkpointer和Store是两个互补但相互独立的持久化系统**，粒度不同（单thread vs 跨thread），是"短期记忆"和"长期记忆"两个不同的问题，不要混为一谈。
- **LangGraph官方自己承认"checkpoint无限增长"是个真实痛点**，需要手动清理策略——这跟上一章发现的DeepAgents用`DeltaChannel`归约器优化`messages`checkpoint增长（O(N²)→O(N)）其实是同一个问题的两种应对方式：一个是从底层数据结构上优化增长曲线，一个是从运维角度定期清理旧数据，两者不冲突，可以一起用。
- Agent Server（LangGraph的托管部署产品）会自动处理持久化——这是个还没接触过的产品面，等后面涉及部署相关内容时再展开，这里先不跑题。

---

# Checkpointers（详细指南）

来源：`docs.langchain.com/oss/python/langgraph/checkpointers`

## 核心概念

Checkpointer在每个**超级步骤（super-step）**保存图state的快照，按**thread**组织。编译时挂上checkpointer之后，才能实现人在回路、时间旅行调试、容错执行、跨轮对话记忆这几件事。

### Thread（线程）

Thread是分配给checkpointer保存的一串检查点的唯一ID，代表一系列运行累积下来的state。调用带checkpointer的图时，必须在配置里指定`thread_id`：

```python
{"configurable": {"thread_id": "1"}}
```

Thread要在执行运行前先"存在"（checkpointer用`thread_id`当主键存取检查点），之后才能查它的当前/历史state。

### Checkpoint（检查点）

Thread在某个时间点的state叫一个checkpoint，是每个超级步骤保存的图state快照，用`StateSnapshot`对象表示。

**超级步骤（super-step）**：图的一个"tick"，这个tick里排定要跑的所有节点（可能并行）全部执行完，才算一个超级步骤。比如`START → A → B → END`这样一个顺序图，输入、节点A、节点B各自是独立的超级步骤，每个步骤跑完都生成一个checkpoint。除了超级步骤级别的checkpoint，LangGraph还在**节点（任务）级别**保留写入——超级步骤内每个节点跑完，它的输出会作为一条任务记录写进checkpointer的`checkpoint_writes`表。

**Checkpoint namespace（`checkpoint_ns`）**：标识这个checkpoint属于哪个图/子图——空字符串`""`代表属于父（根）图，`"node_name:uuid"`代表属于作为某个节点被调用的子图，嵌套子图之间用`|`连接。节点内部可以从config里读到这个值：

```python
def my_node(state: State, config: RunnableConfig):
    checkpoint_ns = config["configurable"]["checkpoint_ns"]
```

### 一个完整例子：4个checkpoint是怎么来的

```python
class State(TypedDict):
    foo: str
    bar: Annotated[list[str], add]

def node_a(state: State):
    return {"foo": "a", "bar": ["a"]}

def node_b(state: State):
    return {"foo": "b", "bar": ["b"]}

workflow = StateGraph(State)
workflow.add_node(node_a); workflow.add_node(node_b)
workflow.add_edge(START, "node_a"); workflow.add_edge("node_a", "node_b"); workflow.add_edge("node_b", END)

checkpointer = InMemorySaver()
graph = workflow.compile(checkpointer=checkpointer)
graph.invoke({"foo": "", "bar": []}, {"configurable": {"thread_id": "1"}})
```

跑完之后产生4个checkpoint：①`START`作为下一个待执行节点的空checkpoint；②用户输入`{'foo': '', 'bar': []}`，下一个节点是`node_a`；③`node_a`输出`{'foo': 'a', 'bar': ['a']}`，下一个节点是`node_b`；④`node_b`输出`{'foo': 'b', 'bar': ['a', 'b']}`，没有下一个节点。**`bar`这个通道因为定义了reducer（`add`），值是累积的（`['a', 'b']`）；`foo`没有reducer，是覆盖（最终是`'b'`）**——这个reducer行为在Graph API overview那章已经吃透过，这里是实际存进checkpoint里的效果。

## 获取和更新状态

### `get_state`——查最新（或某个历史点的）状态

```python
config = {"configurable": {"thread_id": "1"}}
graph.get_state(config)  # 最新状态

config = {"configurable": {"thread_id": "1", "checkpoint_id": "1ef663ba-..."}}
graph.get_state(config)  # 某个具体checkpoint的状态
```

返回一个`StateSnapshot`，字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `values` | `dict` | 这个checkpoint时刻各通道的值 |
| `next` | `tuple[str, ...]` | 下一步要跑的节点名；空`()`代表图跑完了 |
| `config` | `dict` | 含`thread_id`/`checkpoint_ns`/`checkpoint_id` |
| `metadata` | `dict` | `source`（`"input"`/`"loop"`/`"update"`）、`writes`（节点输出）、`step`（超级步骤计数器） |
| `created_at` | `str` | ISO 8601时间戳 |
| `parent_config` | `dict \| None` | 前一个checkpoint的config，第一个是`None` |
| `tasks` | `tuple[PregelTask, ...]` | 这一步要跑的任务，每个任务有`id`/`name`/`error`/`interrupts`，可选`state`（子图快照） |

### `get_state_history`——查完整历史

```python
list(graph.get_state_history(config))  # 最新的排最前
```

可以直接在这份历史列表里筛想要的checkpoint：

```python
history = list(graph.get_state_history(config))
before_node_b = next(s for s in history if s.next == ("node_b",))       # node_b执行前
step_2 = next(s for s in history if s.metadata["step"] == 2)             # 按步骤号
forks = [s for s in history if s.metadata["source"] == "update"]         # 由update_state创建的
interrupted = next(s for s in history if s.tasks and any(t.interrupts for t in s.tasks))  # 发生过中断的
```

### 回放（Replay）

用某个历史`checkpoint_id`重新调用图，会**跳过**这个checkpoint之前的节点（结果已经存好了），**重新执行**这个checkpoint之后的节点——包括其中任何LLM调用、API请求、中断，回放时都会真实地重新触发一遍，不是读缓存。

### `update_state`——手动改状态

`update_state`会创建一个**带更新值的新checkpoint**，不会改原来那个。更新会走跟节点更新一样的路径——有reducer的通道走reducer（**累加**而不是覆盖）。可以指定`as_node`让LangGraph把这次更新当成"来自某个节点"，从而影响接下来该跑哪个节点。

## 三种耐久性模式（Durability Modes）

调用图执行方法时可以指定，从低到高：

| 模式 | 行为 | 取舍 |
|---|---|---|
| `"exit"` | 只在图执行**退出**时（成功/报错/HITL中断）才落盘 | 长时间运行的图性能最好，但中间state不保存，进程崩溃就恢复不了 |
| `"async"` | 每一步执行时**异步**落盘 | 性能和可靠性都不错，但进程若在落盘完成前崩溃，有小概率丢一个checkpoint |
| `"sync"` | 下一步开始前**同步**落盘 | 每个checkpoint都保证写完才继续，最高可靠性，有性能开销 |

```python
graph.stream({"input": "test"}, durability="sync")
```

## 优化检查点存储：`DeltaChannel`

默认情况下，LangGraph每个超级步骤都会把每个state通道的**完整值**写进checkpoint。对于像多轮对话`messages`这种会不断累积的长线程，这会造成存储随时间显著增长（DeepAgents那个O(N²)→O(N)问题的根源就在这里）。`DeltaChannel`只存**这一步新增的增量**，不存完整累积值，大幅压缩追加密集型通道的checkpoint体积。

## Checkpointer库（官方几个实现）

| 库 | 后端 | 适用场景 |
|---|---|---|
| `langgraph-checkpoint` | 内存（`InMemorySaver`） | LangGraph自带，基础接口+序列化协议 |
| `langgraph-checkpoint-sqlite` | SQLite（`SqliteSaver`/`AsyncSqliteSaver`） | 实验、本地开发 |
| `langgraph-checkpoint-postgres` | Postgres（`PostgresSaver`/`AsyncPostgresSaver`） | 生产环境，LangSmith也用它 |
| `langchain-azure-cosmosdb` | Azure Cosmos DB for NoSQL | Azure生产环境，支持同步/异步 |

### Checkpointer要实现的接口（`BaseCheckpointSaver`）

四个核心方法（异步图执行走`.aput`/`.aput_writes`/`.aget_tuple`/`.alist`这几个异步版本）：

- **`.put`**——存一个checkpoint（带config和metadata）
- **`.put_writes`**——存链接到某个checkpoint的中间写入（待写入）
- **`.get_tuple`**——按`thread_id`+`checkpoint_id`取一个checkpoint元组，给`graph.get_state()`用
- **`.list`**——按条件列出checkpoint，给`graph.get_state_history()`用

### 序列化器

默认`JsonPlusSerializer`（底层用ormsgpack+JSON），处理LangChain/LangGraph原生类型、日期时间、枚举等。遇到它不支持的类型（比如Pandas DataFrame）可以开`pickle_fallback=True`退回pickle：

```python
graph.compile(checkpointer=InMemorySaver(serde=JsonPlusSerializer(pickle_fallback=True)))
```

也支持整体加密——传一个`EncryptedSerializer`给`serde`参数，最简单是用`from_pycryptodome_aes()`（从环境变量`LANGGRAPH_AES_KEY`读AES密钥）：

```python
serde = EncryptedSerializer.from_pycryptodome_aes()
checkpointer = SqliteSaver(sqlite3.connect("checkpoint.db"), serde=serde)
```

在LangSmith上跑时，只要这个环境变量存在就自动开启加密。

## 自定义Checkpointer：底层其实是两张表

官方原文点破了LangGraph持久化层的物理结构：

> LangGraph's persistence layer is built on two storage abstractions: a **Checkpoints table**（每个超级步骤一行，存序列化后的图state——`channel_values`/`channel_versions`/`versions_seen`，并链接到父checkpoint）和一张 **Writes table**（每个超级步骤内每个节点输出一行，存`(task_id, channel, value)`）。

这跟上一章`TurnLoop.md`§3实锤LangGraph`Checkpoint`TypedDict字段（`channel_values`/`versions_seen`）时的发现是同一件事的两个角度——那次是看Python的`TypedDict`定义，这次是看官方指南直接讲的存储层设计，两者对得上。

推荐的SQL建表方式（官方给的参考架构）：

```sql
CREATE TABLE checkpoints (
    thread_id          TEXT NOT NULL,
    checkpoint_ns      TEXT NOT NULL DEFAULT '',
    checkpoint_id      TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type               TEXT,
    checkpoint         BYTEA,
    metadata           JSONB,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE writes (
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    task_path     TEXT NOT NULL DEFAULT '',
    idx           INTEGER NOT NULL,
    channel       TEXT NOT NULL,
    type          TEXT,
    value         BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, task_path, idx)
);
```

因为`checkpoint_id`是ULID（按字典序排序、越大越新），"拿最新"就是`ORDER BY checkpoint_id DESC LIMIT 1`，"按ID拿"就是主键等值查询——这个设计选择官方特别强调：**`get_tuple`必须同时支持"不带`checkpoint_id`拿最新"和"带具体`checkpoint_id`拿指定那个"两条路径，而且后者不能只靠扫描实现，要保证O(1)或接近**，因为它不仅用于时间旅行，还是每次图调用时重建`DeltaChannel`状态的关键依赖——这条路径如果查不到东西，`DeltaChannel`的状态重建会**默默地**变成空的，不报错，是一个容易埋雷的细节。

### 可选的扩展能力

`BaseCheckpointSaver`还有几个可选方法，实现了能解锁Agent Server的额外功能，Agent Server启动时会自动探测checkpointer实现了哪些：

| 方法 | 解锁的能力 |
|---|---|
| `adelete_for_runs` | 多任务策略的回滚 |
| `acopy_thread` | 高效地给线程分叉（fork） |
| `aprune` | 清理线程历史 |
| `aget_delta_channel_history` | 高效重建DeltaChannel状态（默认有个通用但较慢的实现，遍历祖先链逐个查；存储后端如果查询能力强，可以覆盖成两次查询搞定，官方给了具体实现示例，核心思路是分两阶段：先找到每个通道最近的`_DeltaSnapshot`快照当种子，再一次性把这些通道从种子到目标checkpoint之间的所有写入查出来重放） |

用`aprune`/`adelete_for_runs`清理历史时要小心：**不能删掉存活checkpoint依赖的DeltaChannel祖先写入**，否则那些通道重建出来会是空的——官方给了三个安全选项：清理前先遍历标记哪些写入不能删、清理前强制在保留点写一份完整快照再自由删祖先、或者干脆跳过对用了DeltaChannel的线程做清理。

#### 深挖：`copy_thread`（fork）到底能不能用——源码验证过，答案是"接口有，官方没实现"

`copy_thread`/`acopy_thread`的docstring（`libs/checkpoint/langgraph/checkpoint/base/__init__.py`）就是"fork一个会话"这件事：

```python
def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
    """Copy all checkpoints and writes from one thread to another.
    ...
    """
    raise NotImplementedError
```

原文特别提醒了一个坑：如果用了`DeltaChannel`，复制时**不能只复制最新那个checkpoint，必须把完整的祖先链（回溯到最近一个`_DeltaSnapshot`）一起复制过去**，否则目标thread的`DeltaChannel`状态没法重建。

但这只是`BaseCheckpointSaver`基类里的一个**可选方法，默认`raise NotImplementedError`**——查了官方目前发布的具体实现，**没有一个真正实现它**：`InMemorySaver`源码里搜不到`copy_thread`；Postgres的异步Saver（`checkpoint-postgres/langgraph/checkpoint/postgres/aio.py`）也搜不到。唯一相关的是`libs/checkpoint-conformance/`里一个`test_copy_thread.py`——这只是"如果你自己实现了这个方法，帮你验证对不对"的一致性测试规范，不代表官方真的实现了。Agent Server会在启动时自动探测checkpointer实现了哪些扩展能力，所以`copy_thread`这个口子理论上是给"你自己接一个实现了这个方法的自定义checkpointer"用的。

**DeepAgents（库函数`create_deep_agent`+官方CLI`deepagents_code`）也没有在这基础上多做任何事**：`create_deep_agent`只透传`checkpointer`参数；官方CLI虽然真的接了`AsyncSqliteSaver`做持久化，但整个仓库搜"fork"没有找到任何会话分叉功能，只有一处跟macOS上gRPC进程fork相关的无关代码。

**结论**：LangGraph官方认可"fork一个thread"这个需求（专门设计了接口、专门写了conformance测试），但截至目前（2026-08-23）没有任何官方checkpointer把它真正实现出来，想用得自己写一个自定义checkpointer补上`copy_thread`方法。这跟Claude Agent SDK的`resume`+`fork_session=True`——**官方直接内置、开箱即用**——是本质不同的两种状态："预留了接口但没人实现" vs "官方帮你实现好了"，不是能力天花板的差异。**这一点后续做各家会话持久化能力对比表时，值得单独列一行。**

### 用一致性测试套件验证实现

```bash
pip install langgraph-checkpoint-conformance
```

```python
from langgraph.checkpoint.conformance import checkpointer_test, validate

@checkpointer_test(name="MyCheckpointer")
async def my_checkpointer():
    async with MyCheckpointer.create() as saver:
        yield saver

report = await validate(my_checkpointer)
if not report.passed_all_base():
    raise RuntimeError("Checkpointer failed conformance suite")
```

官方建议把这个套件跑在发布前的CI里——这是LangGraph自己的checkpointer实现，以及`langgraph-checkpoint-postgres`这些官方库，发布前都会跑的同一套验证。

## 为什么需要Checkpointer——官方给的五个理由

- **人在回路**：人必须能在任意时刻查看图的state，图也必须能在人做完state更新之后正确恢复执行。
- **记忆**：多轮对话这种重复交互场景，后续消息发到同一个thread，就能带着之前的记忆。
- **时间旅行**：能回放之前的执行去检查/调试某一步，也能在任意checkpoint处分叉（fork）去探索另一条路径。
- **容错**：某个超级步骤里一个或多个节点失败了，能从最后成功的那一步重新开始，不用从头跑。
- **待写入（Pending writes）**：一个超级步骤里，如果某个节点执行失败，LangGraph会把**同一超级步骤里其他已经成功完成的节点**的写入存成"待写入"；从这一步恢复执行时，这些已经成功的节点不会被重新跑一遍。

## 值得记的点（Checkpointers这篇）

- **物理结构上，checkpointer的持久层就是两张表**：一张按超级步骤存图state（`Checkpoints`表），一张按节点输出存中间写入（`Writes`表）——跟`TurnLoop.md`§3实锤的`Checkpoint` TypedDict字段（`channel_values`/`versions_seen`）完全对得上，这次是从"官方存储设计"这个角度又确认了一遍。
- **`get_tuple`要同时支持"查最新"和"按ID精确查"，而且后者必须是O(1)级别**——这条容易被忽视的工程细节，直接决定了`DeltaChannel`能不能正确重建状态，是这次翻译里最值得记的一条"隐藏依赖"。
- **Store（跨thread长期记忆）是完全独立的另一套持久化系统，节点里可以跟checkpointer同时用**——一个负责"这轮对话记得住"，一个负责"换个对话/换个人还能查到"，两者解决的是不同粒度的问题，不是二选一；`Stores`详细指南的翻译笔记见[context-window/Stores（LangGraph）学习笔记.md](../context-window/Stores（LangGraph）学习笔记.md)。
