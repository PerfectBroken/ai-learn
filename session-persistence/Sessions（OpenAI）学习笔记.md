# Sessions（OpenAI Agents SDK）

来源：`openai.github.io/openai-agents-python/sessions/`

## 核心概念

Sessions是Agents SDK内置的会话记忆机制，自动维护多次agent运行之间的对话历史——原文："消除了在turn之间手动处理`.to_input_list()`的需要"（`to_input_list()`是之前在`TurnLoop.md`§4读过的"四种conversation state策略"之一，`Session`本质上是把这个手动操作封装成了自动挡）。

## Quickstart

```python
from agents import Agent, Runner, SQLiteSession

agent = Agent(name="Assistant", instructions="Reply very concisely.")
session = SQLiteSession("conversation_123")

result = await Runner.run(agent, "What city is the Golden Gate Bridge in?", session=session)
print(result.final_output)  # "San Francisco"

result = await Runner.run(agent, "What state is it in?", session=session)
print(result.final_output)  # "California"，agent自动记住了上一轮的上下文
```

同步版本也支持：`Runner.run_sync(agent, "...", session=session)`。

## 中断运行的恢复

用同一个session实例（或另一个配了相同session ID+存储后端的实例），可以恢复一个被暂停的运行（比如HITL审批）：

```python
result = await Runner.run(agent, "Delete temporary files...", session=session)

if result.interruptions:
    state = result.to_state()
    for interruption in result.interruptions:
        state.approve(interruption)
    result = await Runner.run(agent, state, session=session)
```

这里的`result.to_state()`/`state.approve()`，就是`TurnLoop.md`§3.1实锤过的`RunState`那套机制——`RunState`专门为HITL暂停/恢复设计，这里是它在实际API里的用法。

## 核心会话行为（三步）

1. **运行前**：runner自动检索这个session的对话历史，前置到本次输入项目前面。
2. **运行后**：这次运行产生的所有新项目自动存进session里。
3. **上下文保留**：每次后续运行都带着完整的对话历史。

## 控制历史与新输入怎么合并

`RunConfig.session_input_callback`——一个自定义合并步骤的回调，接收`(history, new_input)`两个列表，返回最终喂给模型的输入列表：

```python
def keep_recent_history(history, new_input):
    return history[-10:] + new_input  # 只保留最近10条历史，再接上这轮新输入

result = await Runner.run(
    agent, "Continue from the latest updates only.", session=session,
    run_config=RunConfig(session_input_callback=keep_recent_history),
)
```

原文提示：回调收到的是两个列表的**副本**，可以放心地在回调内部修改它们，不会影响原始数据。

## 限制检索的历史条数

`SessionSettings`控制每次运行前拉取多少条历史：

```python
result = await Runner.run(
    agent, "Summarize our recent discussion.", session=session,
    run_config=RunConfig(session_settings=SessionSettings(limit=50)),
)
```

- `SessionSettings(limit=None)`（默认）——取全部
- `SessionSettings(limit=N)`——只取最近N条

## 内存操作（增删查）

```python
session = SQLiteSession("user_123", "conversations.db")

items = await session.get_items()           # 取全部
await session.add_items([{"role": "user", "content": "Hello"},
                          {"role": "assistant", "content": "Hi there!"}])  # 追加
last_item = await session.pop_item()          # 弹出并删除最后一条
await session.clear_session()                 # 清空
```

`pop_item`可以用来"撤销"最后一次交互，实现纠正对话：

```python
result = await Runner.run(agent, "What's 2 + 2?", session=session)
# 用户想改口
assistant_item = await session.pop_item()  # 先弹掉agent的回复
user_item = await session.pop_item()       # 再弹掉自己刚才的问题
result = await Runner.run(agent, "What's 2 + 3?", session=session)  # 换个问题重新问
```

## 内置Session实现——数量远超预期

官方一次性列了**10种**内置实现，这是之前完全没料到的规模，比LangGraph（一个`InMemorySaver`+两个官方数据库Saver）、Claude Agent SDK（只有本地JSONL一种）都要丰富得多：

| Session类型 | 最适用场景 | 说明 |
|---|---|---|
| `SQLiteSession` | 本地开发、简单应用 | 内置、轻量，可选文件或纯内存 |
| `AsyncSQLiteSession` | 需要异步SQLite驱动 | 基于`aiosqlite` |
| `RedisSession` | 跨worker/服务共享的低延迟内存 | 分布式部署 |
| `SQLAlchemySession` | 生产应用，复用已有数据库 | 支持SQLAlchemy的任意数据库 |
| `MongoDBSession` | 已经用MongoDB，或需要多进程存储 | 基于异步`pymongo` |
| `DaprSession` | 云原生部署，用Dapr sidecar | 借力Dapr支持的30+种数据库后端 |
| `OpenAIConversationsSession` | OpenAI服务端托管存储 | 基于Conversations API |
| `OpenAIResponsesCompactionSession` | 长对话，需要自动压缩 | 包裹另一个session后端使用 |
| `AdvancedSQLiteSession` | SQLite + 分支/分析 | 比基础版功能更重 |
| `EncryptedSession` | 透明加密+TTL | 包装器，需要选一个底层session |

### `OpenAIConversationsSession`——服务端托管

```python
session = OpenAIConversationsSession()
# 或者恢复之前的对话：
# session = OpenAIConversationsSession(conversation_id="conv_123")
```

这就是`TurnLoop.md`§4提过的"四种conversation state策略"里`conversation_id`那一种的具体实现——历史存在OpenAI自己的服务器上，本地不用管存储。

### `OpenAIResponsesCompactionSession`——自动压缩，这次翻译里最值得细看的一个

包裹一个底层session，用Responses API的`responses.compact`能力压缩历史，可以在每轮后按`should_trigger_compaction`自动触发：

```python
underlying = SQLiteSession("conversation_123")
session = OpenAIResponsesCompactionSession(
    session_id="conversation_123",
    underlying_session=underlying,
)
result = await Runner.run(agent, "Hello", session=session)
```

原文关键句："在每个turn之后，SDK检查压缩候选是否满足阈值，仅当满足时才进行压缩"——不是每轮都压缩，是达到阈值才触发。

三种压缩模式：`"previous_response_id"`（用Responses API保留的响应ID）、`"input"`（从当前session的项重建压缩请求）、`"auto"`（默认，自动选最安全的）。

**自动压缩有个副作用，原文专门提醒了**：

> 压缩清空并重写会话历史，因此SDK在考虑运行完成前等待压缩完成。在流式传输模式中，如果压缩很重，`run.stream_events()`可能在最后输出令牌后保持开放几秒钟。

也就是说自动压缩会**拖慢`Runner.run()`的返回时机**——压缩请求本身的用量也会算进这次运行的`Usage`统计里。想避免这个副作用，可以关掉自动触发，自己找时机手动压缩：

```python
session = OpenAIResponsesCompactionSession(
    session_id="conversation_123",
    underlying_session=underlying,
    should_trigger_compaction=lambda _: False,  # 关闭自动触发
)
result = await Runner.run(agent, "Hello", session=session)
await session.run_compaction({"force": True})  # 自己挑时机手动压缩（空闲时/每N轮/达到大小阈值等）
```

**并发写入这一层，官方原文只在这个包装器内部做了有限保护，边界之外要开发者自己小心**：原文明确写了"The wrapper serializes calls to `add_items()`、`pop_item()`和`clear_session()` with the locked replacement and recovery phase"——也就是说压缩执行期间，这三个写操作会被串行化，不会跟"清空重写"这个动作打架。但原文紧接着划了一条边界："Run manual compaction between turns without concurrent wrapper mutations, and do not mutate the underlying session directly while compaction is running"——**只保护"通过这个包装器发起的调用"，不保护"绕过包装器直接改底层session"这种场景**，后者原文明确说是不安全的，要开发者自己避免。

### 其余几种实现的关键细节

- **`AsyncSQLiteSession`**：需要`pip install aiosqlite`。
- **`RedisSession`**：`RedisSession.from_url(...)`会自己创建并**拥有**Redis客户端，`close()`之后这个session就"终止"了，后续操作会抛`RuntimeError`（重复/并发调用`close()`是安全的）；如果应用已经自己管理Redis客户端，可以直接传`redis_client=...`构造，这种情况下`close()`是空操作，客户端归属权还在调用者手上。
- **`SQLAlchemySession`**：`from_url(...)`或直接传现成的`engine`，`create_tables=True`自动建表。
- **`DaprSession`**：同样有"owned client vs 外部传入client"的`close()`行为差异，支持`ttl=`自动过期、`consistency=DAPR_CONSISTENCY_STRONG`更强的读后写一致性保证。
- **`MongoDBSession`**：`from_uri(...)`拥有并自动关闭`AsyncMongoClient`；用两个集合——`sessions_collection`（默认`agent_sessions`）和`messages_collection`（默认`agent_messages`）；每次非空`add_items()`调用写入一个**逻辑批处理文档**，用单调递增的`seq`排序——原文补充了一条原子性保证："A logical batch must fit within MongoDB's single-document size limit; an oversized batch fails atomically without storing a partial batch."，也就是一批写入要么整批成功、要么整批不落盘，不会出现"写了一半"的中间状态。
- **`AdvancedSQLiteSession`**：多了**对话分支**能力——`await session.create_branch_from_turn(2)`，从第2轮直接分叉出一条新对话线，还有`store_run_usage()`做token用量追踪。**这是目前查到的、除LangGraph`copy_thread`接口之外，另一个真正跟"fork"相关的能力，而且这个是有具体实现落地的，不是只停留在接口层面。**
- **`EncryptedSession`**：任意session实现的加密包装器，`encryption_key`+`ttl`，包一层就行：

```python
underlying_session = SQLAlchemySession.from_url("user_123", url="sqlite+aiosqlite:///conversations.db", create_tables=True)
session = EncryptedSession(session_id="user_123", underlying_session=underlying_session, encryption_key="your-secret-key", ttl=600)
```

## 操作模式（Patterns）

**Session ID命名**：官方建议给ID赋予明确语义——`"user_12345"`（按用户）、`"thread_abc123"`（按对话线）、`"support_ticket_456"`（按业务上下文）。

**多个session互相独立**：

```python
session_1 = SQLiteSession("user_123", "conversations.db")
session_2 = SQLiteSession("user_456", "conversations.db")
# 各自维护独立的对话历史
```

**多个agent可以共享同一个session**：

```python
support_agent = Agent(name="Support")
billing_agent = Agent(name="Billing")
session = SQLiteSession("user_123")
# 两个agent看到的是同一份对话历史
```

## 自定义Session实现——鸭子类型，不需要继承基类

原文强调：**不需要继承`SessionABC`**，只要一个类结构上符合`Session`协议（定义`session_id`/`session_settings`，实现四个方法）就行：

```python
class MyCustomSession:
    session_settings: SessionSettings | None = None

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.items: list[TResponseInputItem] = []

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        if limit is None:
            return list(self.items)
        if limit <= 0:
            return []
        return list(self.items[-limit:])

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> TResponseInputItem | None:
        return self.items.pop() if self.items else None

    async def clear_session(self) -> None:
        self.items.clear()
```

这跟LangGraph的`BaseCheckpointSaver`（继承抽象基类，覆写`raise NotImplementedError`的方法）是两种不同的扩展哲学——**OpenAI这边走的是Python鸭子类型协议（Protocol），LangGraph走的是抽象基类继承**。

### 让自定义Session拿到`RunContextWrapper`

给四个方法都加一个显式命名、仅限关键字的`wrapper`参数，SDK就会自动把当前的`RunContextWrapper`传进来（可以用来做租户路由、鉴权之类的存储决策）：

```python
class ContextAwareSession:
    async def get_items(self, limit: int | None = None, *, wrapper: RunContextWrapper[Any] | None = None) -> list[TResponseInputItem]: ...
    async def add_items(self, items: list[TResponseInputItem], *, wrapper: RunContextWrapper[Any] | None = None) -> None: ...
    async def pop_item(self, *, wrapper: RunContextWrapper[Any] | None = None) -> TResponseInputItem | None: ...
    async def clear_session(self, *, wrapper: RunContextWrapper[Any] | None = None) -> None: ...
```

原文强调：**四个方法必须都声明`wrapper`，SDK才会启用这个集成；用通用的`**kwargs`接收是不满足这个签名检查的**——这是个容易踩的坑，鸭子类型协议下"签名对不对"比继承体系下更容易被忽略。

## 社区实现

官方文档列了一个社区维护的实现例子：`openai-django-sessions`——基于Django ORM，适配任何Django支持的数据库（PostgreSQL/MySQL/SQLite等）。

## 值得记的点

- **OpenAI这边的Session生态比想象中丰富得多**——10种官方内置实现，覆盖了从纯内存到分布式Redis/MongoDB/Dapr、服务端托管、加密包装器等各种组合，比LangGraph和Claude Agent SDK都要多样。
- **压缩（Compaction）这里是内置的一等公民**——`OpenAIResponsesCompactionSession`直接包在session这一层，甚至有"自动压缩会拖慢`run()`返回"这种官方明确记录的副作用+对应的手动关闭方案；这跟LangGraph把压缩完全下放给用户自己写middleware（`SummarizationMiddleware`）判断"要不要压缩"是不同的设计取向。
- **`AdvancedSQLiteSession`的`create_branch_from_turn()`是一个真正落地的"fork"实现**——跟上一篇笔记里"LangGraph的`copy_thread`只停留在接口层面、没有官方实现"形成直接对比，值得放进后续的对比表格里。
- **自定义扩展走的是鸭子类型协议，不是继承抽象基类**——跟LangGraph的`BaseCheckpointSaver`哲学不同，这点也值得记进对比表。
