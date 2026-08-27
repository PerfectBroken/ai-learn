# Subagents（LangChain）

官方文档：[Subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)

## 1 定义与架构

**Subagents架构里，中央主agent（通常叫supervisor/监督者）把子agent当工具调用来协调它们。主agent决定调用哪个子agent、给什么输入、怎么合并结果。子agent是无状态的——不记得过去的交互，所有对话记忆都由主agent维护。这提供了上下文隔离：每次子agent调用都在一个干净的context window里工作，防止主对话被撑爆。**

架构示意：用户→主agent→（子agent A/B/C）→结果返回主agent→主agent回复用户。

**关键特性四条**：
- **集中控制**：所有路由都经过主agent
- **不直接跟用户交互**：子agent把结果返回给主agent、不是返回给用户（虽然可以在子agent内部用中断让用户参与）
- **通过工具调用子agent**：子agent是以工具的形式被调用的
- **并行执行**：主agent可以在同一轮里调用多个子agent

**Supervisor vs Router，官方专门做了区分**：Supervisor（这篇讲的模式）是一个**维持对话上下文、能跨多轮动态决定调用哪些子agent的完整agent**；Router通常只是**单一的分类步骤**，不维护持续的对话状态——这个区分后面Router笔记里还会再展开对比。

## 2 什么时候用

**当你有多个不同领域**（比如日历/邮件/CRM/数据库）、**子agent不需要直接跟用户对话**、或者**想要集中式的工作流控制**时，用Subagents模式；工具数量不多的简单场景，用单个agent就够。

**子agent里也能有用户交互**：虽然子agent通常是把结果返回给主agent，但可以在子agent内部用**中断（interrupt）**暂停执行、收集用户输入——子agent需要澄清或者需要审批才能继续时很有用。主agent仍然是编排者，但子agent可以在任务执行到一半时向用户收集信息。

## 3 基础实现

核心机制：把子agent包装成主agent能调用的工具。

```python
from langchain.tools import tool
from langchain.agents import create_agent

subagent = create_agent(model="...", tools=[...])

@tool("research", description="研究一个主题并返回发现")
def call_research_agent(query: str):
    result = subagent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content

main_agent = create_agent(model="...", tools=[call_research_agent])
```

## 4 五个设计决策，逐一展开

| 决策 | 选项 |
|---|---|
| 同步 vs 异步 | 同步（阻塞）vs 异步（后台） |
| 工具模式 | 每个agent一个工具 vs 单一分派工具 |
| 子agent规格 | 系统提示枚举 vs 枚举约束 vs 基于工具的发现 |
| 子agent输入 | 仅查询 vs 完整上下文 |
| 子agent输出 | 子agent结果 vs 完整对话历史 |

### 4.1 同步 vs 异步——不是Python的async/await，是"主agent要不要等"

**特别提醒（原文加了个Note）**：这里的"异步"不是Python语言层面的`async`/`await`，是指主agent启动一个后台作业（通常在独立的进程/服务里）后继续往下走、不阻塞。

| 模式 | 主agent行为 | 最佳用途 | 权衡 |
|---|---|---|---|
| **同步（默认）** | 等子agent跑完才继续 | 主agent的下一步需要这个结果 | 实现简单，但会阻塞对话 |
| **异步** | 子agent在后台跑的同时主agent继续 | 独立任务，用户不该被晾在那等 | 响应更及时，但更复杂 |

**同步的例子**（序列图）：用户问"东京天气怎么样"→主agent调research子agent→**主agent等待结果**→子agent返回"72°F，晴朗"→主agent回复用户。适用场景：主agent需要这个结果才能组织回复；任务有顺序依赖（取数据→分析→回复）；子agent失败应该直接阻止主agent继续回复。

**异步的例子**（序列图，更复杂）：用户说"审查这份并购合同"→主agent向作业系统发起`run_agent("legal_reviewer", task)`→作业系统返回一个`job_id`→**主agent立刻回复用户"已经开始审查了（job_123）"**→合同审查agent在后台跑（可能要审100多页）→期间用户可以随时问"现在什么状态"，主agent查`check_status(job_id)`返回"running"→合同审查完成后，用户再问一次，主agent查到"completed"，再调`get_result(job_id)`拿到完整分析、回复用户。

**异步实现要用到的"三工具模式"**：①**启动作业**（返回job_id）②**检查状态**（返回pending/running/completed/failed）③**获取结果**（拿已完成的产出）。**作业完成后怎么通知用户**：原文给的一个思路是——显示一条通知，用户点击后触发发一条"检查job_123并总结结果"的`HumanMessage`。

**这一段读完容易留一个悬念：结果到底是怎么"写回"主agent上下文的？去查了DeepAgents的开源实现（`libs/deepagents/deepagents/middleware/async_subagents.py`里的`AsyncSubAgentMiddleware`）把这个机制实锤了——结论是：写回这一步100%是"拉"（pull），没有任何自动推送渠道。**

最直接的证据是`check_async_task`这个工具自己的description原文："Statuses shown earlier in the conversation are always stale, so call this to get the current status rather than reporting a status from a previous tool result."——**这是写给LLM看的明确警告：之前对话里出现过的任何状态都已经过期，必须重新调用这个工具才能拿到当前真实状态**，主agent没有任何被动接收通知的能力，只能主动查。

完整写回路径：主agent调用`check_async_task(task_id)`→内部先查一次这次远程运行的状态→**只有状态是"success"时**，才会再去把这个远程thread的完整state拉回来，取出消息列表里**最后一条消息**的内容当作结果→把结果打包进一个**完全普通的`ToolMessage`**，通过`Command(update={"messages": [...]})`写进主agent自己的状态——跟任何一次普通工具调用的`tool_result`回填方式没有任何特殊之处。

**顺带核实出一个之前不知道的架构细节**：DeepAgents的异步子agent，跑的不是"同进程后台线程"，而是**通过LangGraph SDK连到一个远程的、符合Agent Protocol标准的LangGraph服务器**（源码注释原文："Async subagents use the LangGraph SDK to launch background runs on remote Agent Protocol servers"）——这跟Claude Code"后台subagent"（同进程内的不同执行路径）是完全不同的部署形态，DeepAgents的异步子agent天然就是分布式的。

### 4.2 工具模式——每个agent一个工具，还是一个统一的派发工具

| 模式 | 最佳用途 | 权衡 |
|---|---|---|
| **每个agent一个工具** | 想对每个子agent的输入/输出做精细控制 | 配置更多，但自定义空间更大 |
| **单一分派工具** | agent很多、开发分布在多个团队、更看重约定优于配置 | 组合更简单，但每个agent能自定义的空间更少 |

**每个agent一个工具**：就是第3节那个基础示例——每个子agent各自包一层`@tool`，主agent根据任务跟工具描述的匹配程度决定调哪个。

**单一分派工具**：用一个参数化的`task`工具，按名字调用任意一个已注册的临时子agent——任务描述作为一条人类消息传给子agent，子agent的最后一条消息作为工具结果返回。**这是一种基于约定的方法，用简单性去换取"代理组合和强上下文隔离"，代价是牺牲了每个子agent单独做上下文工程的灵活性**。

**适用场景**：想把agent开发分给多个团队；需要把复杂任务隔离进单独的context window；需要一种不改协调器代码就能加新agent的可扩展方式；更看重约定而不是自定义。

**一个值得记的提示**：这种模式下，子agent的能力甚至可以跟主agent完全一样——这种情况下调用子agent**纯粹是为了上下文隔离**：让复杂的多步骤任务在隔离的context window里跑，不撑爆主agent的对话历史，子agent自主完成任务、只返回一份简明摘要，主线程保持精简高效。

**"代理注册表+任务派发器"代码示例**：

```python
SUBAGENTS = {
    "research": research_agent,
    "writer": writer_agent,
}

@tool
def task(agent_name: str, description: str) -> str:
    """为任务启动临时子agent。

    可用的agent：
    - research: 研究和事实查找
    - writer: 内容创建和编辑
    """
    agent = SUBAGENTS[agent_name]
    result = agent.invoke({"messages": [{"role": "user", "content": description}]})
    return result["messages"][-1].content
```

## 5 上下文工程——控制信息在主agent和子agent之间怎么流动

| 类别 | 目的 | 影响 |
|---|---|---|
| 子agent规格 | 确保该调用的时候真的调用了 | 主agent的路由决策 |
| 子agent输入 | 确保子agent拿到优化过的上下文、能好好干活 | 子agent的表现 |
| 子agent输出 | 确保主agent能对子agent的结果采取行动 | 主agent的表现 |

### 5.1 子agent规格——name和description是主agent"认识"子agent的主要方式

**这是提示词层面的杠杆，要仔细选**：
- **name**：主agent怎么称呼这个子agent，要清晰、面向动作（比如`research_agent`、`code_reviewer`）
- **description**：主agent对这个子agent能力的全部认知，要具体说明它处理什么任务、什么时候该用它

对于"单一分派工具"这种设计，还得额外告诉主agent有哪些子agent可选，官方给了三种方法：

| 方法 | 最适合 | 权衡 |
|---|---|---|
| **系统提示枚举** | 小型、静态的agent列表（<10个） | 简单，但agent变了就要改提示词 |
| **枚举约束**（给`agent_name`参数加enum） | 小型、静态的agent列表（<10个） | 类型安全、显式，但agent变了要改代码 |
| **基于工具的发现**（专门一个`list_agents`工具） | 大型或动态的agent注册表 | 灵活可扩展，但增加了复杂度 |

三种各自的代码示例（精简）：
- 系统提示枚举：直接把agent列表和描述写进`system_prompt`里。
- 枚举约束：`agent_name: AgentName`（一个`str, Enum`类型），给`task`工具的参数加类型约束。
- 基于工具的发现：额外提供`list_agents(query: str = "")`工具，主agent先调它按需发现可用agent，再调`task`。

### 5.2 子agent输入——不只是传一句查询，还能从状态里塞进更多东西

通过从agent的状态里提取内容，可以往子agent输入里加进"完整消息历史/之前的结果/任务元数据"这些静态提示词里塞不进去的东西：

```python
class CustomState(AgentState):
    example_state_key: str

@tool("subagent1_name", description="subagent1_description")
def call_subagent1(query: str, runtime: ToolRuntime[None, CustomState]):
    subagent_input = some_logic(query, runtime.state["messages"])
    result = subagent1.invoke({
        "messages": subagent_input,
        "example_state_key": runtime.state["example_state_key"]
    })
    return result["messages"][-1].content
```

### 5.3 子agent输出——两种策略保证主agent能拿到有用的信息

1. **在prompt里明确要求**：精确指定子agent应该返回什么。**一个常见的失败模式，原文专门提醒**：子agent执行了工具调用或推理，但**没有把结果写进最后一条消息**——因为监督者只看得到最后一条输出，得在prompt里提醒它这一点。
2. **在代码里格式化**：在返回之前调整/丰富这个响应，比如用`Command`除了传最后的文本之外、还额外传回特定的状态key。

```python
@tool("subagent1_name", description="subagent1_description")
def call_subagent1(query: str, tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    result = subagent1.invoke({"messages": [{"role": "user", "content": query}]})
    return Command(update={
        "example_state_key": result["example_state_key"],
        "messages": [ToolMessage(content=result["messages"][-1].content, tool_call_id=tool_call_id)]
    })
```

**这一点直接呼应了OpenAI那边`custom_output_extractor`的讨论**——两家都在解决"子agent的产出怎么被父agent更精确地拿到"这个问题，但走的路子不一样：OpenAI是在父agent这一侧用一个提取函数对子agent的历史做后处理；LangChain这里是**让子agent自己主动把额外的结构化状态塞进`Command`里返回**，是子agent侧主动配合，不是父agent侧被动提取。

## 6 检查点和状态检查

默认情况下子agent用的是**继承检查点（inherit checkpointer）模式**——每次调用都从新鲜状态开始，支持中断，能安全并行跑。如果需要子agent在多次调用之间维持自己独立的持久对话历史，编译时传`checkpointer=True`（续用模式）。

**一个容易踩坑的细节**：因为子agent是在工具函数内部被调用的，**LangGraph没法静态地发现它们**——这意味着带`subgraphs`参数的`get_state`调用**拿不到子agent的状态**。如果需要读取嵌套图的状态（比如在中断期间），得改成从一个自定义图里的节点函数去调用子agent，而不是从工具函数里调用。

## 值得记的点

- **"同步/异步"这个设计决策，直接对上了`TurnLoop.md`§4.2已经整理过的三家对比**（Claude Code默认异步后台/OpenClaw异步投递队列/OpenAI `as_tool()`真同步阻塞）——LangChain这里把它明确列成了"设计决策"，而不是某家框架的固定行为，说明这本来就是一个所有多agent系统都要显式做的选择，不是某一家的特色。
- **"单一分派工具"模式其实就是Claude Code`Agent`工具+`subagent_type`参数的设计思路**——一个统一的`task`/`Agent`工具，按名字选子agent类型，这跟"单一分派工具"章节描述的注册表+分派器模式几乎是同一个东西，只是LangChain这边把"为什么要这样设计"（团队分布式开发、约定优于配置、可扩展性）讲得更清楚。
- **子agent规格的三种发现方法（系统提示枚举/枚举约束/工具发现）**，本质上是"工具发现"那一章学过的"规模化场景检索机制"在"子agent"这个具体场景下的复刻——agent数量小于10用静态枚举，数量大或动态变化就得上专门的发现工具，这条经验规律是可迁移的。
