# Agent orchestration（OpenAI Agents SDK）

官方文档：[Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)

## 编排是什么

> "Orchestration refers to the flow of agents in your app. Which agents run, in what order, and how is the next step decided?"

两种主要编排方式：

1. **让LLM自己做决策**——靠LLM的智能去规划、推理、决定下一步该做什么
2. **通过代码编排**——流程由你的代码决定

原文明确说这两种方式**可以混用**，各有取舍，下面分别展开。

## 一、通过LLM编排

**Agent = 配备了指令、工具和handoffs的LLM**。给定一个开放式任务，LLM能自主规划怎么完成它——用工具采取行动/获取数据，用handoffs把任务委托给子agent。原文举了个研究agent的例子，可以配备：

- 网络搜索（在线查资料）
- 文件搜索和检索（搜索专有数据/已连接的数据源）
- 电脑操作（在电脑上执行动作）
- 代码执行（做数据分析）
- Handoffs到擅长规划、写报告等的专门agent

### 核心SDK模式——两种，官方给了一张对比表

| 模式 | 怎么运作 | 最适合的场景 |
|---|---|---|
| **Agents as tools**（子agent当工具） | 管理agent（manager agent）**一直掌控着对话**，通过`Agent.as_tool()`调用专家agent | 想让**一个agent拥有最终答案**、合并多个专家的输出、或者想把SDK的guardrails统一收在一个地方执行 |
| **Handoffs**（交接） | 分诊agent（triage agent）把对话**路由**给专家，这个专家**变成这一轮剩下时间里的活跃agent** | 想让专家**直接**回复用户、保持提示词聚焦、或者想让handoff直接切换活跃指令，不需要manager再复述一遍结果 |

**原文给的选择标准，直接翻译**：当一个专家应该帮忙处理一个**有边界的子任务**、但不应该接管面向用户的对话时，用**agents as tools**；当"路由"这件事本身就是工作流的一部分、并且你希望被选中的专家**接管这一轮剩下的部分**时，用**handoffs**。

**这两种模式也可以组合用**：一个分诊agent可以先handoff给某个专家，这个专家自己还可以再把其他窄范围的子任务当工具调用别的agent。

**这个对比表里最关键的一句区分，是"谁在掌控对话、结果怎么流回来"**——跟`TurnLoop.md`§4已经学过的"子agent当工具"内部同步/异步分歧是同一个层面的问题：**Agents as tools模式下，manager agent的Turn Loop从头到尾没有被"交出去"，子agent的结果始终是以`tool_result`的形式流回manager，manager拿到结果后还要自己组织最终回复**；**Handoffs则是真正意义上的"控制权转移"——一旦触发handoff，原来的agent就不再是"活跃agent"了，用户看到的直接回复变成了新agent的输出，不再经过manager转述**。Handoffs这个机制本身`TurnLoop.md`§4.1已经详细学过（三分支循环+"驱动身份中途切换"），这次的重点是**Agents as tools**这个之前没有单独展开过的模式，以及两者放在一起对比时体现出的这条"控制权在谁手上"的分界线。

**这套模式最重要的五条战术，原文列了五条**：

1. **投资高质量的提示词**——讲清楚有哪些工具可用、怎么用、agent必须遵守什么约束。
2. **监控你的应用并持续迭代**——看哪里出错了，回头改提示词。
3. **让agent能自我反省、自我改进**——比如放进一个循环里跑，让它自己批评自己；或者提供错误信息，让它自己改进。
4. **用在某一件事上做得特别好的专门agent，而不是指望一个通用agent什么都擅长**。
5. **投资[evals](https://platform.openai.com/docs/guides/evals)**——这能让你训练agent持续改进、把任务做得更好。

## 二、通过代码编排

**这种方式更确定（deterministic）**，在速度、成本、性能这几个维度上更可预测。常见模式，原文列了四种：

- **用[结构化输出](https://platform.openai.com/docs/guides/structured-outputs)生成能被代码检查的格式规整的数据**——比如让agent把任务分到几个类别里，再根据类别代码里挑下一个agent。
- **把多个agent串起来，把上一个的输出转成下一个的输入**——比如把"写一篇博客"这个任务拆成一串步骤：做调研→写大纲→写正文→自我批评→改进。
- **在`while`循环的每一次迭代里，先跑任务agent产出结果，再跑一个评估agent（evaluator agent）来评估这个结果、给反馈；评估agent说通过了才停下来**。
- **用`asyncio.gather`这类Python原语并行跑多个agent**——当你手上有多个互相不依赖的任务时，这样做能提速。

原文提到官方仓库[`examples/agent_patterns`](https://github.com/openai/openai-agents-python/tree/main/examples/agent_patterns)里有一批这类模式的示例代码，没有展开细节，只是指了路。

## 三、深挖：`Agent.as_tool()`——Agents as tools模式的具体实现（来源：[tools.md#agents-as-tools](https://openai.github.io/openai-agents-python/tools/#agents-as-tools)）

原文一句话定位："In some workflows, you may want a central agent to orchestrate a network of specialized agents, instead of handing off control. You can do this by modeling agents as tools."——**不移交控制权，把专门agent包装成工具**，这正是Agent orchestration那篇对比表里"Agents as tools"这一行的具体实现方式。

### 3.1 基础用法

```python
spanish_agent = Agent(name="Spanish agent", instructions="You translate the user's message to Spanish")
french_agent = Agent(name="French agent", instructions="You translate the user's message to French")

orchestrator_agent = Agent(
    name="orchestrator_agent",
    instructions="You are a translation agent. You use the tools given to you to translate. If asked for multiple translations, you call the relevant tools.",
    tools=[
        spanish_agent.as_tool(tool_name="translate_to_spanish", tool_description="Translate the user's message to Spanish"),
        french_agent.as_tool(tool_name="translate_to_french", tool_description="Translate the user's message to French"),
    ],
)
```

`.as_tool()`直接挂在一个已经定义好的`Agent`实例上，调用时传`tool_name`/`tool_description`，就把整个agent变成了orchestrator的一个可调用工具——**这是这几家里语法上最直接的"把agent变成工具"写法**，不需要额外包一层适配代码。

### 3.2 子agent的状态默认不继承父agent，除非显式共享`session`

原文原话："The state options configure the nested agent run started by the tool call; the parent run's conversation state is not inherited automatically. To share client-managed history between the parent and nested runs, explicitly pass the same `session` to both."

**这一点直接呼应了我们`session-persistence`那一章学过的OpenAI Sessions机制**——被当作工具调用的子agent，本质上还是发起了一次独立的`Runner.run()`，它的对话历史默认跟父agent的run是**两条独立的线**，要共享历史必须显式把同一个`session`对象传给父子两边。这跟Claude Agent SDK子agent"默认零上下文、只能通过prompt传递信息"的设计是同一个大方向（子agent默认隔离），但OpenAI这边给了一个明确的"手动开后门"选项（共享`session`），Claude那边目前没有对应的"手动共享父agent历史"机制。

`as_tool()`支持的运行时配置项：`max_turns`、`run_config`、`hooks`、`previous_response_id`、`conversation_id`、`session`、`needs_approval`。

### 3.3 结构化输入——默认只接受一个字符串，但可以换成完整的Pydantic schema

默认情况下`Agent.as_tool()`期待的输入是`{"input": "..."}`这种单字符串对象；但传`parameters`（一个Pydantic model或dataclass类型）可以换成结构化输入：

```python
class TranslationInput(BaseModel):
    text: str = Field(description="Text to translate.")
    source: str = Field(description="Source language.")
    target: str = Field(description="Target language.")

translator_tool = translator_agent.as_tool(
    tool_name="translate_text",
    parameters=TranslationInput,
    include_input_schema=True,
)
```

### 3.4 审批关卡——子agent调用本身也能被卡在人工审批那一关

`Agent.as_tool(..., needs_approval=...)`走的是跟`function_tool`**完全同一套**审批流程：需要审批时run会暂停，待审批项出现在`result.interruptions`里，用`result.to_state()`拿到状态、调用`state.approve()`/`state.reject()`之后再恢复。**这说明在OpenAI Agents SDK的设计里，"调用一个子agent"和"调用一个普通函数工具"在权限治理层面被当成同一类事情对待**，不是特殊化处理。

### 3.5 自定义输出提取——不一定要拿子agent的"最终回答"，可以精确抠出其中一部分

原文列了三个典型用途：从子agent的聊天历史里提取特定信息（比如一段JSON）、转换/重新格式化最终答案（Markdown转纯文本/CSV）、在答案缺失或格式错误时校验并提供兜底值。做法是给`as_tool`传`custom_output_extractor`：

```python
async def extract_json_payload(run_result: RunResult) -> str:
    for item in reversed(run_result.new_items):
        if isinstance(item, ToolCallOutputItem) and item.output.strip().startswith("{"):
            return item.output.strip()
    return "{}"

json_tool = data_agent.as_tool(tool_name="get_data_json", custom_output_extractor=extract_json_payload)
```

**这一点是跟Claude Agent SDK的一个明显差异**：Claude那边"子agent只把最终消息返回给父agent"是固定行为（前面`Subagents in the SDK`笔记里记过），OpenAI这边则允许你在拿到子agent结果之后、送回orchestrator之前，**用代码精确抠出其中你想要的那一部分**（哪怕不是最终那句话），灵活度更高。

**但这个机制不是"确定性保证"，要澄清一下边界，不能说得太乐观**：官方示例代码里那个提取函数（"倒着遍历`run_result.new_items`，找第一个以`{`开头的工具调用输出"）本身还是一条启发式规则，只是把匹配对象从"子agent自由生成的最终文本"换成了"结构化的工具调用输出列表"——**这是缩小了自然语言的不确定性作用面，不是消除了它**。子agent到底会不会调用该调用的工具、调用几次、顺序对不对，这一层的非确定性`custom_output_extractor`完全管不到；如果子agent压根没走到该走的那条路径，或者产出了多个看起来都符合条件的候选，这个提取函数照样会抓错或者落到兜底值（`return "{}"`）。**真正站得住的差异点，收窄成一句更准确的表述**：它能让父agent的代码触达子agent运行过程中**任意一步的结构化产出**（不局限于最后一句话），而不是"消除了LLM输出的不确定性"。

### 3.6 流式嵌套agent运行 & 3.7 条件性工具启用（简记）

- **`on_stream`回调**：给`as_tool`传一个`on_stream`函数，能实时监听子agent运行过程中的流式事件（`raw_response_event`/`run_item_stream_event`/`agent_updated_stream_event`），同时最终还是拿到完整的final output——传了这个参数会自动让子agent以streaming模式跑。
- **`is_enabled`动态启用/禁用**：接受布尔值、同步函数、异步函数（签名`(context, agent) -> bool`），可以根据运行时上下文（用户偏好/环境dev-vs-prod/A-B测试）动态决定某个"agent-as-tool"这次要不要出现在LLM可见的工具列表里——**这跟我们`tool-design`/`tool-discovery`那两章学过的"按场景动态过滤工具"是同一个思路，在这里落到了"子agent工具"这个具体场景上**。原文特别提醒：`is_enabled`只控制"这个工具对LLM可不可见/能不能被调度"，**不能替代基于工具参数或访问资源本身的授权校验**，那部分要在工具实现内部做，或者用tool input guardrails/人工审批来管。

## 值得记的点

- **这篇文档最核心的贡献，是把"LLM自主编排"和"代码硬编排"两条路清楚地并列起来、且明说可以混用**——不像很多资料把"agent系统"默认等同于"LLM自己决定一切"，这篇一上来就说这是两种**正交的**选择，不是非此即彼。
- **"评估agent（evaluator agent）"这个模式，是这篇文档里第一次遇到的一个具体、有名字的角色**——用一个独立的agent去评估另一个agent的产出、给反馈，直到评估通过才停止循环，这跟"多agent"的另一种用法（不是分工，是自我校验/质量把关）有关，值得留意后面读别家文档时会不会也出现类似角色。
- **Agents as tools vs Handoffs**这组对比，是这次翻译里最有价值的部分，把"控制权在谁手上"这条分界线讲得很清楚，直接补上了`TurnLoop.md`§4.1只学了Handoffs、没有单独学过Agents-as-tools这个对照面的空白。
- **`Agent.as_tool()`是这三家（Claude/OpenAI/OpenClaw）里语法上最直接的"子agent当工具"实现**——直接在已定义的`Agent`实例上调一个方法，参数就是工具名/描述，不需要额外包装层。跟Claude Agent SDK对比，两个明显差异点：①子agent状态默认不继承父agent，但OpenAI给了"显式传同一个`session`"这个手动共享选项，Claude没有对应机制；②OpenAI的`custom_output_extractor`能让父agent的代码触达子agent运行过程中任意一步的结构化产出、不局限于"最终消息"，但这依然只是缩小了自然语言不确定性的作用面（从"最终文本"收窄到"结构化工具输出"），不是消除了它——子agent会不会走到该走的路径、会不会调用该调用的工具，这一层的非确定性代码管不到。
- **子agent调用能被纳入跟普通函数工具完全同一套的审批/动态启用机制**（`needs_approval`、`is_enabled`）——说明OpenAI Agents SDK在"权限治理"和"工具可见性管理"这两层设计上，压根没有把"调用一个子agent"和"调用一个普通函数"区别对待，是同一套机制在两种不同"工具"上的复用。
