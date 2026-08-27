# Handoffs（LangChain）

官方文档：[Handoffs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)

## 1 定义——比OpenAI的Handoff概念更宽

**Handoffs架构里，行为随状态动态变化。核心机制：工具更新一个状态变量（比如`current_step`或`active_agent`），这个变量跨多轮持续存在，系统读取它来调整行为——要么切换到不同配置（系统提示/工具），要么路由到不同agent。**

原文专门加了一条术语来源提示："**handoffs**这个术语由**OpenAI**创造，用工具调用（比如`transfer_to_sales_agent`）在agent或状态之间转移控制权"——跟`TurnLoop.md`§4.1里记的OpenAI Handoff机制是同一个源头，但LangChain这篇文档把这个概念用得更宽：**不仅包括"切换到另一个agent"，也包括"同一个agent内部的动态配置变更"**（不换agent实例，只是换这个agent的system prompt/工具集）。这是这次翻译最重要的一条概念澄清。

### 序列图（保修维修场景，原文用mermaid画的，翻译描述如下）

用户："我的手机坏了"→（当前步骤：获取保修状态，可用工具：`record_warranty_status`）agent问"设备还在保修期内吗"→用户"是的，还在保修期"→agent调用`record_warranty_status("in_warranty")`把状态记下来→（**状态变了，步骤切换到"分类问题"，可用工具变成`record_issue_type`**）agent问"能描述一下问题吗"→用户"屏幕碎了"→agent调用`record_issue_type("hardware")`→（**再次切换，步骤变成"提供解决方案"，可用工具变成`provide_solution`/`escalate_to_human`**）agent给出保修维修流程。

**这个例子里全程只有一个"agent"在跟用户对话，变化的是它每一步能用的工具和背后的指令**——这正是LangChain把"单代理动态配置"也算进Handoffs的原因。

## 2 关键特征

- **状态驱动行为**：行为随状态变量（`current_step`/`active_agent`）的变化而变化
- **工具驱动转换**：工具负责更新状态变量，从而在状态间移动
- **直接用户交互**：每个状态对应的配置都直接处理用户消息（不像Subagents那样结果要经手主agent）
- **持久状态**：状态跨对话轮次保留

## 3 什么时候用

需要强制顺序约束（满足前置条件才解锁某个功能）、agent需要在不同状态下都直接跟用户对话、或者要搭建多阶段对话流时，用Handoffs。**客服场景特别适用**：比如必须先收集保修ID，才能处理退款——这种"先XX才能YY"的顺序要求。

## 4 基础实现——一个返回`Command`的工具

核心机制是一个工具，返回`Command`来更新状态，从而触发状态或agent的转换：

```python
@tool
def transfer_to_specialist(runtime) -> Command:
    """Transfer to the specialist agent."""
    return Command(
        update={
            "messages": [ToolMessage(content="Transferred to specialist", tool_call_id=runtime.tool_call_id)],
            "current_step": "specialist"  # 触发行为变化
        }
    )
```

**为什么一定要带`ToolMessage`**：LLM调用工具后期待收到一个响应，带着匹配`tool_call_id`的`ToolMessage`才能完成这个"请求-响应"闭环——没有它，对话历史在协议层面就是格式错误的。**这是Handoff工具跟普通工具在协议层面唯一的共同约束，没有特殊豁免**。

## 5 两种实现方式

### 5.1 单代理中间件——只有一个agent，靠middleware动态换配置

用中间件拦截每次模型调用，根据状态动态调整system prompt和可用工具；工具通过更新状态变量触发转换：

```python
class SupportState(AgentState):
    current_step: str = "triage"
    warranty_status: str | None = None

@tool
def record_warranty_status(status: str, runtime: ToolRuntime[None, SupportState]) -> Command:
    return Command(update={
        "messages": [ToolMessage(content=f"Warranty status recorded: {status}", tool_call_id=runtime.tool_call_id)],
        "warranty_status": status,
        "current_step": "specialist"
    })

@wrap_model_call
def apply_step_config(request: ModelRequest, handler) -> ModelResponse:
    step = request.state.get("current_step", "triage")
    configs = {
        "triage": {"prompt": "Collect warranty information...", "tools": [record_warranty_status]},
        "specialist": {"prompt": "Provide solutions based on warranty: {warranty_status}", "tools": [provide_solution, escalate]},
    }
    config = configs[step]
    request = request.override(system_prompt=config["prompt"].format(**request.state), tools=config["tools"])
    return handler(request)

agent = create_agent(
    model,
    tools=[record_warranty_status, provide_solution, escalate],
    state_schema=SupportState,
    middleware=[apply_step_config],
    checkpointer=InMemorySaver()  # 跨轮持久化状态
)
```

**这个模式的本质**：`create_agent`本身只创建了**一个**agent实例，`middleware`在每次模型调用前读一次`current_step`，动态换上不同的prompt和tools——从头到尾没有"第二个agent"参与，纯粹是同一个agent的配置随状态切换。

### 5.2 多代理子图——真的有多个独立agent，各自是图上的节点

用`Command(goto=..., graph=Command.PARENT)`在代理节点之间导航，指定下一个执行的节点：

```python
@tool
def transfer_to_sales(runtime: ToolRuntime) -> Command:
    last_ai_message = next(msg for msg in reversed(runtime.state["messages"]) if isinstance(msg, AIMessage))
    transfer_message = ToolMessage(content="Transferred to sales agent", tool_call_id=runtime.tool_call_id)
    return Command(
        goto="sales_agent",
        update={"active_agent": "sales_agent", "messages": [last_ai_message, transfer_message]},
        graph=Command.PARENT
    )
```

官方完整示例是一个销售agent+支持agent互相转接的系统：两个agent各自是`StateGraph`上独立的节点，各自持有对方的`transfer_to_*`工具，靠`route_after_agent`这个路由函数判断"该结束、还是继续路由到某个活跃agent"。

**官方明确的选型建议**："**大多数Handoffs场景用单代理中间件**——更简单。只有当确实需要为每个agent定制复杂实现时（比如某个节点本身是带反思/检索步骤的复杂图），才用多代理子图。"——这条建议直接把"要不要真的多起一个agent"这个决策标准给出来了：默认从更简单的单代理动态配置开始，除非某个"状态"背后真的需要一整套独立的复杂逻辑。

## 6 子图Handoffs的上下文工程——这是最需要小心处理的部分

原文专门用一个Warning强调：子图Handoffs（多代理子图这条路）需要谨慎的上下文工程，跟单代理中间件（消息历史自然流动，不用额外处理）不一样——**必须明确决定哪些消息在agent之间传递**，处理不当会让接收方agent看到格式错误的历史，或者背上臃肿的上下文。

**切换时必须保证的最小配对**：LLM期望"工具调用"和"工具调用的响应"成对出现，所以用`Command.PARENT`切换到另一个agent时，必须至少带上两条消息：

1. **触发这次handoff的那条带工具调用的`AIMessage`**
2. **确认这次handoff的`ToolMessage`**（对那个工具调用的人工响应）

**为什么不把子agent的完整历史都传过去**——原文专门用一个Note解释：虽然可以把完整对话都塞进handoff，但常常会导致问题——接收方agent可能被无关的内部推理搞糊涂，token成本也不必要地增加。**只传这一对"handoff配对"消息，让父图的上下文始终聚焦在高层协调上**；如果接收方确实需要额外上下文，应该考虑在`ToolMessage`的内容里**总结**子agent做过的工作，而不是直接甩过去原始的消息历史。

**把控制权还给用户时**：要确保最后一条消息是`AIMessage`——这样才能保持对话历史有效，也能让用户界面正确表示"agent这一轮已经处理完了"。

## 7 实现时要考虑的三件事

- **上下文过滤策略**：每个agent是收到完整对话历史，还是过滤过的一部分，还是一份总结？不同agent因为角色不同，可能需要不同的上下文。
- **工具语义要讲清楚**：Handoff工具到底只更新路由状态，还是同时执行了真实的副作用？比如`transfer_to_sales()`要不要顺带建一张支持工单，还是应该是完全独立的两个动作？
- **token效率**：在"上下文完整性"和"token成本"之间找平衡，对话越长，总结和选择性传递上下文就越重要。

## 值得记的点

- **这次最大的概念修正：LangChain的Handoffs比`TurnLoop.md`§4.1记的OpenAI Handoff范围更宽**——OpenAI那边Handoff严格等于"换一个新agent实例接管Turn Loop"（`current_agent`状态变量被整体替换）；LangChain这边把"同一个agent、只是动态换system prompt和工具集"（单代理中间件）也算作Handoffs的一种实现方式，甚至是**官方推荐的默认做法**。这意味着"Handoff"这个词在不同厂商语境下的颗粒度不一样：OpenAI的Handoff默认就是"换agent身份"，LangChain的Handoff更底层，核心是"状态驱动的行为变化"，"换agent"只是这个更大概念下的一种具体实现（多代理子图）。
- **`AIMessage`+`ToolMessage`配对传递这条规则，是这次翻译里最具体的协议级细节**，直接呼应了这几天反复讨论过的"跨agent边界该传多少上下文"这个问题——跟OpenAI`custom_output_extractor`（父agent精确抠取子agent产出的一部分）、Claude Agent SDK"子agent只返回最终消息"，是同一个议题的第三种答案：**LangChain这里给的是协议层面的最小充分条件（只传触发handoff的那一对消息），而不是"整段历史"或"某个提取函数处理过的结果"**，思路更接近"够用就好，多传是负担"。
- **"handoffs术语由OpenAI创造"这条官方注脚，印证了`TurnLoop.md`§4.1里对OpenAI Handoff来源的记录是准确的**——LangChain自己也承认这是借用了OpenAI的命名，但实现内涵做了扩展。
