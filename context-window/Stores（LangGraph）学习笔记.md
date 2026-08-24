# Stores（LangGraph）

来源：`docs.langchain.com/oss/python/langgraph/stores`

> 这篇原本作为LangGraph`Persistence`文档的配套细节指南，在`session-persistence/`目录下翻译。后来核对发现：`Store`解决的是"跨thread的长期记忆"，功能上不属于"会话持久化"（那是`Checkpointer`管的，thread作用域、恢复的是"这一次正在进行的对话"），而是`ContextWindow.md`§2.3.1"Write：长期记忆"那一节里，LangGraph（+`langmem`）例子用的`store.put()`背后的具体API机制——两边讲的是同一个东西的两个切面（`ContextWindow.md`那边关注"agent什么时候决定要写、写了会不会影响当前窗口"；这篇关注"这个API具体怎么用"）。所以挪到这个目录下，跟`ContextWindow.md`/`LangChain_ContextEngineering_Notes.md`放在一起。

## 核心概念

Store提供**跨thread**的长期记忆。跟checkpointer不同，官方原文："Stores hold arbitrary key-value data accessible from any thread"——存的是任意键值数据，任何thread都能访问，让agent能在多个对话线程之间持久化用户偏好、累积下来的知识等信息。

## 基础用法

```python
from langgraph.store.memory import InMemoryStore
store = InMemoryStore()
```

**Namespace（命名空间）**是元组形式，比如`(user_id, "memories")`——任意长度都行，不一定非要跟用户绑定。

**存（put）**：

```python
namespace_for_memory = (user_id, "memories")
memory_id = str(uuid.uuid4())
store.put(namespace_for_memory, memory_id, {"food_preference": "I like pizza"})
```

**查（search）**：返回这个命名空间下的记忆列表（默认最多10条），每一项是个`Item`对象，含`value`（内容）/`key`/`namespace`/`created_at`/`updated_at`。

```python
memories = store.search(namespace_for_memory)
```

## 列出/分页/发现命名空间

`search`不传`query`也不传`filter`时，返回的是`namespace_prefix`前缀匹配下的所有项（**前缀匹配，不是精确匹配**），超过`limit`直接截断、**不会有"还有更多"的信号**，排序行为依赖具体后端（`PostgresStore`按`updated_at`降序，`InMemoryStore`按插入顺序）。

```python
# 分页
page_size = 50; offset = 0
while True:
    page = store.search(("alice", "memories"), limit=page_size, offset=offset)
    if not page:
        break
    offset += page_size

# 发现有哪些命名空间
namespaces = store.list_namespaces(prefix=("alice",), max_depth=2)
```

## 语义搜索

配一个embedding模型就能开启"按语义找"而不是精确匹配：

```python
from langchain.embeddings import init_embeddings

store = InMemoryStore(
    index={
        "embed": init_embeddings("openai:text-embedding-3-small"),
        "dims": 1536,
        "fields": ["food_preference", "$"]
    }
)

memories = store.search(namespace_for_memory, query="What does the user like to eat?", limit=3)
```

`put`时可以控制哪些字段参与embedding：

```python
# 只嵌入food_preference这个字段
store.put(namespace_for_memory, str(uuid.uuid4()),
          {"food_preference": "I love Italian cuisine", "context": "Discussing dinner plans"},
          index=["food_preference"])

# 完全不嵌入
store.put(namespace_for_memory, str(uuid.uuid4()), {"system_info": "Last updated: 2024-01-01"}, index=False)
```

部署时也能在`langgraph.json`里配置：

```json
{
    "store": {
        "index": {"embed": "openai:text-embeddings-3-small", "dims": 1536, "fields": ["$"]}
    }
}
```

## 在图里怎么用

编译时同时挂`checkpointer`（管thread内的短期记忆）和`store`（管跨thread的长期记忆）：

```python
@dataclass
class Context:
    user_id: str

graph = builder.compile(checkpointer=checkpointer, store=store)
```

节点内部通过`Runtime`对象拿到`store`和`context`：

```python
from langgraph.runtime import Runtime

async def update_memory(state: MessagesState, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    namespace = (user_id, "memories")
    await runtime.store.aput(namespace, str(uuid.uuid4()), {"memory": memory})

async def call_model(state: MessagesState, runtime: Runtime[Context]):
    user_id = runtime.context.user_id
    memories = await runtime.store.asearch((user_id, "memories"), query=state["messages"][-1].content, limit=3)
    info = "\n".join([d.value["memory"] for d in memories])
```

**换一个全新的`thread_id`，只要`user_id`一样，一样能查到之前存的记忆**——这就是"跨thread"的实际效果：

```python
config = {"configurable": {"thread_id": "2"}}  # 全新thread
graph.stream({"messages": [...]}, config, context=Context(user_id="1"))  # 但user_id没变
```

## 自定义Store实现

继承`BaseStore`，实现五个async方法（可选再实现对应的同步版本）：

| 方法 | 说明 |
|---|---|
| `aput(namespace, key, value, index=None)` | 存/覆盖一项 |
| `aget(namespace, key)` | 按key查一项，没有返回`None` |
| `adelete(namespace, key)` | 删一项 |
| `asearch(namespace_prefix, *, query=None, filter=None, limit=10, offset=0)` | 在命名空间前缀下搜索 |
| `alist_namespaces(*, prefix=None, suffix=None, max_depth=None, limit=100, offset=0)` | 列出匹配的命名空间 |

设计原则：命名空间要支持前缀匹配；精确key查找要做到O(1)或接近。

参考SQL架构：

```sql
CREATE TABLE store_items (
    namespace   TEXT[] NOT NULL,
    key         TEXT NOT NULL,
    value       JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (namespace, key)
);
CREATE INDEX ON store_items USING gin(namespace);
```

存的值必须是纯Python字典（JSON可序列化），用`json.dumps`/`json.loads`或JSONB列，不能存不可JSON序列化的Python对象。实现语义搜索时，`query`不为空就要做embedding+按余弦相似度排序，每项`Item`要带上`score`字段；不支持向量搜索就该抛`NotImplementedError`，不要假装支持。

## 生产环境建议

`InMemoryStore`只适合开发测试。生产环境官方建议用`PostgresStore`/`MongoDBStore`/`RedisStore`/`UpstashStore`这类持久化实现，都实现同一个`BaseStore`接口。

## 值得记的点

- **这就是`ContextWindow.md`§2.3.1"Write：长期记忆"里`langmem`例子背后的真实API**——`create_manage_memory_tool`函数体那一行`store.put(namespace, key, value)`，`store`就是这里的`BaseStore`，两处笔记讲的是同一个机制。
- Store支持语义搜索（配embedding模型），Checkpointer不支持——这是两者定位不同的直接体现：Checkpointer存的是"图state快照"，没有"语义相关性"这个维度的需求；Store存的是"知识/偏好"，天然需要按意思查而不是按精确key查。
- Namespace是前缀匹配、`search`默认无`query`时按后端自己的排序规则返回、超过`limit`直接截断不报信号——这几个行为细节容易在实际使用时踩坑，写代码前要留意。
