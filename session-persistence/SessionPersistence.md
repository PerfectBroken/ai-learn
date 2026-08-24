# 会话持久化

Layer 3第二个话题，跟上一章Turn Loop末尾"Agent State"那节是紧挨着的——那一节回答的是"agent的执行状态/业务状态长什么样、存不存在一起"，这一章要回答的是往下一层的问题："这份状态具体怎么落盘、存在哪、怎么在进程重启/换机器/多用户并发的情况下正确恢复"。

## 目录

- [1 背景：为什么需要会话持久化](#1-背景为什么需要会话持久化)
- [2 学习笔记](#2-学习笔记)
  - [2.1 五家全景对比表——按背景里①②③④的顺序展开](#21-五家全景对比表按背景里①②③④的顺序展开)
    - [2.1.1 ① 隔离单元、默认存储介质、可插拔性](#211-隔离单元默认存储介质可插拔性)
    - [2.1.2 ② Fork/分支能力——四种截然不同的成熟度](#212-fork分支能力四种截然不同的成熟度)
    - [2.1.3 ③ 跨进程/跨机器恢复机制](#213-跨进程跨机器恢复机制)
    - [2.1.4 ④ "释放资源"和"彻底删除数据"是不是同一个动作](#214-释放资源和彻底删除数据是不是同一个动作四家里语义最容易搞混的一组对比)
  - [2.2 补充发现：压缩之后，原始消息是物理删除还是逻辑删除](#22-补充发现压缩compaction之后原始消息是物理删除还是逻辑删除三家分成两派)
- [3 参考资料](#3-参考资料)

## 1 背景：为什么需要会话持久化

**先如实说明**：这次读的五篇官方文档里，没有一篇专门用一整段去论证"为什么需要持久化"——都是产品文档，直接扎进机制细节，不像Turn Loop那章有《Building Effective AI Agents》、Agent State那章有12-Factor Agents这种理念层文章打底。但如果一定要选一个立论基点，**最接近讲背景的是Claude Agent SDK的开篇**——就以这段话为基准展开这一节：

> "会话（session）是SDK在你的智能体工作过程中累积的对话历史……回到一个会话意味着智能体拥有之前的完整上下文：它已经读过的文件、已经执行过的分析、已经做出的决策。你可以提出后续问题、从中断中恢复，或者分支出去尝试不同的方法。"

这几句话虽短，但拆开看其实是一条完整的论证链——**攒了什么值钱的东西 → 什么场景下要把它找回来 → 保得住到什么程度**，正好对应下面三层：

**第一层：会话里攒的是"已经花了成本换来的中间产物"，不是聊天记录本身**——原文列的三样东西是"已经读过的文件、已经执行过的分析、已经做出的决策"。这三样东西的共同点是都很贵：读一个大文件要消耗token，一次分析可能要跑好几轮工具调用才收敛，一个决策背后往往是agent试错几次才得出的结论。持久化保住的正是这些成本——没有它，进程一退出，这些成本全部清零，下次只能重新掏钱再买一遍。

**第二层：这份"省下来的成本"在三种具体场景下被兑现**——`Work with session`这篇指南把原文那三个场景各自展开成了一个具体能力：

- **提出后续问题** → 对应`resume`最常见的用例："智能体已经分析了某些内容；现在你希望它基于该分析采取行动，而无需重新读取文件。"——最日常的场景，用户不想每次都把背景重新讲一遍。
- **从中断中恢复** → 对应`resume`的另外两个用例：一是"从限制中恢复"（第一次运行因`error_max_turns`或`error_max_budget_usd`提前终止，用更高的限额恢复），二是"重启你的进程"（进程被动关闭，重启后接着聊）。这里"中断"不只是用户手滑关窗口这种主动行为，也包括agent自己触发的资源上限、进程本身的非预期退出——要扛住的中断类型比字面意思更宽。
- **分支出去尝试不同方法** → 对应`fork`，原文的例子很具体：已经分析完一个认证模块、沿JWT方向推进到一半，这时想换评估OAuth2这条路，但又不想放弃JWT那条线已有的进度。`fork`从同一个起点分裂出两条各自独立、可分别恢复的历史，互不干扰——本质上是把"探索性试错"的成本也降了下来：不持久化的话，"要不要换个方向试试"这个念头常常会因为"换了就要从头再来"而被直接打消。

**第三层：这份持久化到底能扛多远，原文自己也做了诚实的校准**——`Work with session`专门用一整节讲"跨主机恢复"的局限：会话文件本质是"创建它的那台机器本地的"文件，换一台机器默认就找不到了；要跨主机，要么手动把`.jsonl`搬过去，要么接一个`SessionStore`适配器把转录镜像到共享存储。这提醒我们**"持久化"解决的是"进程生命周期"这个维度的丢失问题，不天然解决"机器/环境"这个维度的丢失问题**——这是两件事，后一件需要额外的工程投入才能补上。

**串起来看，这一章要回答的问题跟下面四张对比表是一一对应的**：①"隔离单元、存储介质、可插拔性"对应的是"攒的东西具体存在哪、怎么存"；②"Fork能力"对应的正是上面第二层里"分支尝试"这个场景，五家谁真正把它做出来了；③"跨进程/跨机器恢复"对应第三层——"进程重启"和"换机器"这两层恢复各家分别做到了哪一层；④"释放资源vs彻底删除"对应的是持久化的另一端——不想要了、想清掉，各家怎么定义"清掉"。

**跟上一章"Agent State"的关系**：那一节回答的是"该保存什么"（业务状态vs执行状态），这一节回答的是"怎么让它真正扛过中断"——没有持久化机制，Agent State那节讨论的一切都只存在于一次进程运行的内存里，中断就清零。

（另外四篇文档——LangGraph、OpenAI Agents SDK、GitHub Copilot SDK、OpenClaw——都没有给出类似这样的场景化背景铺垫，直接从"怎么配置""API长什么样"讲起，所以这一节以Claude Agent SDK的开篇为主干展开，其余四家的具体机制放进下面的对比表里。）

## 2 学习笔记

（这里只放读完多篇文档之后的综合/对比结论。单篇文档的翻译笔记放在各自独立的文件里，见"参考资料"清单里的链接。）

### 2.1 五家全景对比表——按背景里①②③④的顺序展开

行是Claude Agent SDK、OpenAI Agents SDK、GitHub Copilot SDK、OpenClaw、**DeepAgents**（`deepagents_code` CLI，替换了原来的LangGraph）。**这个替换是有意为之**：LangGraph本身是个通用图执行引擎，不是一个"agent产品"，拿它跟Claude Agent SDK/OpenAI Agents SDK/Copilot SDK/OpenClaw这几个成品级agent SDK/产品放在一起比"session怎么持久化"，比较对象不对等；DeepAgents（尤其是官方CLI`deepagents_code`）才是跟另外四家同一量级的"成品agent产品"，换成它对比更公平。OpenClaw的`Restart recovery`已经完整翻译（见[Restart recovery（OpenClaw）学习笔记](Restart%20recovery（OpenClaw）学习笔记.md)）；个别格子原文确实没提到的内容，照样标"未查到"，不编。

#### 2.1.1 ① 隔离单元、默认存储介质、可插拔性

| 系统 | 隔离单元 | 默认/常见存储介质 | 能不能换存储后端 |
|---|---|---|---|
| **DeepAgents**（`deepagents_code` CLI） | `thread`——CLI里叫`/threads`，底层继承自LangGraph的`thread_id` | **SQLite**：`~/.deepagents/.state/sessions.db`，`AsyncSqliteSaver`——官方Configuration文档和源码（`deepagents_code/sessions.py`）双重确认，两边完全一致 | **CLI产品层面硬编码SQLite**，不像底层`create_agent`库函数那样开放`checkpointer`参数给用户选——库本身依然可插拔（继承`BaseCheckpointSaver`即可），只是这个CLI没把选择权交出来，是"库保持中立、官方CLI替用户做好选择"的又一个例子 |
| **Claude Agent SDK** | `session_id`（对应`~/.claude/projects/<cwd>/<session-id>.jsonl`一个文件） | 本地JSONL文件 | **不可插拔**，唯一存储形态是本地文件；跨机器只能靠手动搬文件，或接`SessionStore`适配器镜像到自定义后端（见④） |
| **OpenAI Agents SDK** | `session`（命名自由，无强制格式） | `SQLiteSession`（默认，可纯内存/可落文件） | **可插拔**，官方**10种**内置实现（含Redis/MongoDB/SQLAlchemy/Dapr），自定义走鸭子类型协议 |
| **GitHub Copilot SDK** | `session_id`（对应`~/.copilot/session-state/<session-id>/`一个目录） | 本地文件系统（`checkpoints/`下逐个JSON快照文件） | **不可插拔，硬编码**——官方issue（"Support pluggable session storage backends"）明确承认这是当前限制，两条相关issue都被标记duplicate指向一个私有仓库的release追踪，没法确认后续有没有落地 |
| **OpenClaw** | `session`——但存储其实是**两层**：对话历史是"每个agent一份SQLite数据库"，子agent/后台任务/投递队列/cron/重启哨兵这些"执行状态"另外存在一份**共享**SQLite状态数据库里，两者物理分开 | SQLite（`transcript_events`表 + 共享状态库） | 原文没提供任何"换存储后端"的接口/配置项，看起来是**硬编码SQLite**，但不像Copilot那样有官方issue明确承认这是限制——置信度中等，不是"未深挖"，是"查了相关文档，没找到可插拔的证据" |

#### 2.1.2 ② Fork/分支能力——四种截然不同的成熟度

| 系统 | 有没有 | 落地程度 |
|---|---|---|
| **DeepAgents**（`deepagents_code` CLI） | 官方Quickstart/Configuration都没提到fork/分支功能 | **没找到**——底层LangGraph的`copy_thread`接口本身也没被这个CLI用上，跟"接口有、没人接"这个既有结论一致，只是这次是从产品文档角度又确认了一遍，没在CLI功能列表里看到 |
| **Claude Agent SDK** | 有，`fork_session=True` | **真正落地、开箱即用**——一个参数直接支持，官方文档给了完整可跑的示例代码 |
| **OpenAI Agents SDK** | 有，`AdvancedSQLiteSession.create_branch_from_turn()` | **真正落地，但只在这一种加强版实现里有**——普通的`SQLiteSession`及其余8种官方实现都没有这个方法 |
| **GitHub Copilot SDK** | 未查到 | 没有专门查证过，留白，不编 |
| **OpenClaw** | `Restart recovery`原文没有提到fork/分支功能 | 查了持久化相关的官方文档没找到，不代表OpenClaw完全没有这个能力——只是没在这次读的文档范围里出现，如实标注 |

**DeepAgents这一行背后的底层依据，是`Persistence（LangGraph）学习笔记.md`里"深挖：`copy_thread`到底能不能用"那节的结论**（DeepAgents的checkpointer机制直接继承自LangGraph）；五家的fork成熟度差得很开——从"官方直接给你一个参数"到"接口画了饼、连一个内置实现都没接、CLI产品也没接"都有。

#### 2.1.3 ③ 跨进程/跨机器恢复机制

| 系统 | 机制 |
|---|---|
| **DeepAgents**（`deepagents_code` CLI） | 官方文档没有讨论跨机器迁移，只给出了本地存储路径；底层继承自`create_agent`的checkpointer理论上能换成连远程Postgres的实现，但这个CLI产品硬编码了本地SQLite文件，没有暴露"换后端"的配置项，天然不支持跨机器 |
| **Claude Agent SDK** | 两条路：①手动把`.jsonl`文件复制到新主机对应路径，`cwd`必须匹配；②接`SessionStore`适配器，让SDK自动把转录镜像到自定义共享后端（S3/Redis/数据库） |
| **OpenAI Agents SDK** | 跟LangGraph同理——只要换的是共享后端（Redis/Postgres/MongoDB等），天然支持 |
| **GitHub Copilot SDK** | 必须把`~/.copilot/session-state/`挂载到共享持久卷（比如Azure Files），没有应用层"镜像到远程存储"的抽象——这跟它"存储不可插拔"是同一个限制的两个表现 |
| **OpenClaw** | **原文讨论的其实是同一台机器上"进程重启/崩溃恢复"，不是另外四家那种"跨机器迁移"**——自建SQLite+`writer-claim`机制（`activeWriterRunId`声明+`expectedWriterRunId`校验），多进程/多Gateway访问同一状态目录靠状态目录锁防冲突；`Restart recovery`原文没有讨论"怎么把这份状态搬到另一台机器"这个问题，这跟另外四家的"跨机器"语境不完全对齐，是唯一一家聚焦"同机重启"而不是"跨机器"的 |

#### 2.1.4 ④ "释放资源"和"彻底删除数据"是不是同一个动作——四家里语义最容易搞混的一组对比

| 系统 | 只释放资源、数据还在 | 彻底删除数据 |
|---|---|---|
| **GitHub Copilot SDK** | `session.disconnect()` | `client.deleteSession()`，官方原文明确写了"irreversible" |
| **OpenAI Agents SDK** | 各Session实现的`close()`——**但只对"owned client"场景生效**（`RedisSession.from_url()`/`DaprSession.from_address()`/`MongoDBSession.from_uri()`这几种自己创建连接的用法），关掉的是客户端连接，Redis/Mongo/Dapr里的数据本身不受影响 | `clear_session()`——**这个反而是真删数据**（源码实锤：SQL `DELETE`语句），命名上"clear"听起来比"delete"更温和，实际杀伤力一样大，是这四家里语义最容易被搞混的一个方法名 |
| **DeepAgents**（`deepagents_code` CLI） | 官方文档没提到"仅释放资源"这个概念——CLI本身没有维护长连接的"session对象"要显式释放 | 手动`rm ~/.deepagents/.state/sessions.db*`——**没有专门的CLI删除命令**，官方原文明确警告"这无法撤销"，跟Copilot`deleteSession()`的"irreversible"是同一个警示语气 |
| **Claude Agent SDK** | 进程退出，或者设置`persistSession:false`（纯内存跑，从不落盘） | 没查到一个显式的"删除某个session"API；有`cleanupPeriodDays`这种基于时间的自动过期清理策略，不是主动调用式的删除 |
| **OpenClaw** | **既不是单纯"释放资源"，也不是"彻底删除"，是第三种状态——"墓碑化"（tombstoned）**：自动恢复预算耗尽、或者子agent反复恢复失败，session会被标记成墓碑，不再参与自动恢复循环，但原文没说数据会被删掉——用户被引导用`/new`/`/reset`开一个替代session，暗示原session的数据大概率还在，只是"死"了、不会再被自动接续 | 原文没有提到一个显式的"彻底删除某个session数据"的操作/命令 |

**这张表最大的坑还是在OpenAI那一行**——`close()`看着像"清理"，其实只关连接；`clear_session()`听着像"清一下"，其实是真删——命名和实际破坏力完全不对称，四家里独一份。**OpenClaw这次补充的"墓碑化"则是一个全新的第三种状态**，不属于"释放资源"或"彻底删除"这个二元框架，值得单独记住：它是"标记为不再自动处理，但不主动清数据"。

### 2.2 补充发现：压缩（Compaction）之后，原始消息是物理删除还是逻辑删除？——三家分成两派

这个发现不属于①②③④里的任何一层，是读OpenAI文档时顺带查出来的一个岔路，单独放在这里。容易被"压缩=安全的软操作"这个直觉带偏，三家查完实锤，结论分成两派，其中一家反直觉：

| 系统 | 结论 | 证据 |
|---|---|---|
| **OpenClaw** | **逻辑删除**——原始记录完整留在磁盘上，压缩只改变下一轮模型能看到什么 | 官方文档原文（`docs/concepts/compaction.md`）："The full conversation history stays on disk. Compaction only changes what the model sees on the next turn." |
| **Claude Code** | **逻辑删除**（高置信度推断，非单句官方原文实锤）——JSONL是追加式格式，`compact_boundary`是标记检查点的系统消息，不是重写已有行 | 官方"Manage sessions"文档对JSONL格式的描述（每行一条独立记录）+ 多个独立第三方来源一致确认transcript文件在压缩后依然完整存在 |
| **OpenAI Agents SDK**（`OpenAIResponsesCompactionSession`） | **物理删除**——压缩时对底层session先`clear_session()`（若底层是`SQLiteSession`，就是真的执行`DELETE FROM ... WHERE session_id=?`并`commit()`），再用压缩后的内容重新`add_items()`写入，原始消息在成功压缩后从这个存储层真正消失 | 源码实锤：`src/agents/memory/sqlite_session.py`的`clear_session()`方法 + `src/agents/memory/openai_responses_compaction_session.py`的`run_compaction()`内部调用链 |

**反直觉的地方**：三家里，`compaction`这个词听起来最像是"轻量级的软操作"，但真正把原始数据从存储层删掉的，恰恰是唯一一家提供官方开箱即用压缩会话（`OpenAIResponsesCompactionSession`）的——OpenClaw和Claude Code虽然也做摘要压缩，但压缩动的只是"喂给模型看什么"这一层，从没碰过底层持久化的原始数据。**这跟④里记的另一个发现（OpenAI的`clear_session()`才是真删、`close()`反而只关连接）连起来看，是同一个设计取向的延续：OpenAI这边的Session机制在"改写/重组底层存储"这件事上，比另外几家更激进、也走得更深。**

（唯一的局限：OpenAI这条结论目前只源码验证了`SQLiteSession`这一种底层实现；`clear_session()`是`Session`协议里的通用契约方法，理论上其余几种官方实现——Redis/MongoDB/SQLAlchemy等——大概率遵循同样"clear就是真删"的语义，但没有逐一去查每一种的具体实现代码，这一点如实标注，不代表已经对全部10种实现都做了源码核实。）

## 3 参考资料

**实现层——官方产品怎么具体做的**

- LangGraph官方文档，[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) + [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)——**已读**，全文翻译见[Persistence（LangGraph）学习笔记](Persistence（LangGraph）学习笔记.md)。这两篇讲的是Checkpointer（thread作用域，对应"会话持久化"）；文档中还包括了stores部分[Stores](https://docs.langchain.com/oss/python/langgraph/stores)链接到的这篇，讲跨thread长期记忆，跟"会话持久化"不是一回事，翻译笔记挪到了[context-window/Stores（LangGraph）学习笔记.md](../context-window/Stores（LangGraph）学习笔记.md)。
- Claude Agent SDK官方文档，[Work with sessions](https://code.claude.com/docs/en/agent-sdk/sessions)——**已读**，全文翻译见[Work with session(claude code)学习笔记](Work%20with%20session(claude%20code)学习笔记.md)。另外还有一个**概念上完全不同**的[File checkpointing](https://platform.claude.com/docs/en/agent-sdk/file-checkpointing)——这个存的是agent对文件系统的修改快照，不是对话状态，容易搞混，要专门区分清楚。
- OpenAI Agents SDK官方文档，[Sessions](https://openai.github.io/openai-agents-python/sessions/)——**已读**，全文翻译见[Sessions（OpenAI）学习笔记](Sessions（OpenAI）学习笔记.md)。实际内容比预告丰富得多：`Session`协议 + **10种**官方内置实现（不只是四种），其中`AdvancedSQLiteSession`带一个真正落地的对话分支/fork能力（`create_branch_from_turn`），`OpenAIResponsesCompactionSession`把压缩做成了session层的一等公民。
- GitHub Copilot SDK官方文档，[Session resume and persistence](https://docs.github.com/en/copilot/how-tos/copilot-sdk/use-copilot-sdk/session-persistence)——**已读**，全文翻译见[Session resume and persistence（GitHub Copilot）学习笔记](Session%20resume%20and%20persistence（GitHub%20Copilot）学习笔记.md)。除了目录结构之外，比预告丰富的地方：恢复时能顺手重新配置model/工具/system prompt等15个选项、`disconnect()`（释放内存但保留磁盘数据）vs `deleteSession()`（磁盘数据永久删除）的关键区分、无限会话的压缩阈值用的是上下文利用率比例、以及官方主动承认"没有内置会话锁"这几点。
- OpenClaw，两篇要分开看：
  - Agent loop文档里的**Session Transcript部分**——见`Agent loop（OpenClaw）学习笔记.md`"深挖：Session Transcript的存储结构"节，SQLite `transcript_events`（JSON blob主表）+ `transcript_event_identities`（二级索引，幂等键）都在里面。
  - [Restart recovery](https://docs.openclaw.ai/gateway/restart-recovery)——**已读**，全文翻译见[Restart recovery（OpenClaw）学习笔记](Restart%20recovery（OpenClaw）学习笔记.md)。比标题范围大得多，重心其实是"怎么保证恢复不会重复执行/不丢外部副作用"（幂等性设计），比另外四家的"能不能恢复对话"深一层；还有三个另外四家都没有的机制：三次计费的自动派发预算+耗尽墓碑化、子agent恢复的2小时窗口安全阀、优雅重启的5分钟排空预算（大部分重启其实什么都不打断）。
- DeepAgents官方文档，[Deep Agents Code](https://docs.langchain.com/oss/deepagents/code/overview) + [Configuration](https://docs.langchain.com/oss/deepagents/code/configuration) + [Quickstart](https://docs.langchain.com/oss/deepagents/code/quickstart)——**已读关键部分**（存储路径、`/threads`恢复命令、删除方式），没有整篇通读做完整笔记，五家对比表里的结论都有原文引用支撑。
