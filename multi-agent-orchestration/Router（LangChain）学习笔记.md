# Router（LangChain）

官方文档：[Router](https://docs.langchain.com/oss/python/langchain/multi-agent/router)

## 1 定义

**Router架构里，一个路由步骤对输入分类，把它指向专门的agent。**适用于拥有不同"垂直领域"的场景——每个领域各自需要一个专属agent、有独立的知识域。

流程：查询 → Router（分类） → 零个或多个专门agent（可并行） → 结果综合 → 组合答案。

**主要特征三条**：Router负责拆解查询；零个或多个专门agent被并行调用；结果被合成为一份连贯的响应。

## 2 什么时候用

有不同的垂直领域、需要并行查询多个信息源、并且想把结果合成成一份组合响应时，用Router模式。

## 3 基础实现——单代理路由 vs 多代理并行路由

### 3.1 单代理路由（用`Command`）

```python
from langgraph.types import Command

def classify_query(query: str) -> str:
    """用LLM给查询分类，确定合适的agent"""
    ...

def route_query(state: State) -> Command:
    """按查询分类路由到合适的agent"""
    active_agent = classify_query(state["query"])
    return Command(goto=active_agent)
```

### 3.2 多代理并行路由（用`Send`）

```python
from typing import TypedDict
from langgraph.types import Send

class ClassificationResult(TypedDict):
    query: str
    agent: str

def classify_query(query: str) -> list[ClassificationResult]:
    """用LLM分类，确定要调用哪些agent"""
    ...

def route_query(state: State):
    """按分类结果路由到相关agent"""
    classifications = classify_query(state["query"])
    return [Send(c["agent"], {"query": c["query"]}) for c in classifications]
```

**这两段代码的区别很直白**：`Command(goto=...)`一次只能指向**一个**目标agent，是单选；`classify_query`返回一个列表、配合`Send`给列表里每一项分别派发一份工作，是可以**同时命中多个**agent的多选路由。

## 4 无状态 vs 有状态

- **无状态路由**：每个请求独立路由，调用之间没有记忆。
- **有状态路由**：跨请求维持对话历史。

## 5 Router vs Subagents——两种模式都能把工作分派给多个agent，区别在"怎么决定分派给谁"

原文的对比句："一个专门的路由步骤（通常是单个LLM调用或基于规则的逻辑）对输入分类并分派到agent。Router通常不维持对话历史。"——Subagents这边则是"主agent动态决定调用哪些子agent，维持上下文，可以跨多轮调用多个子agent"。

**这组对比换个说法就是**：Router是"**一次性分类，分完就完事**"，天然偏无状态；Subagents是"**一个完整的agent持续管理调用决策**"，天然带着状态和跨轮记忆——这跟`Subagents（LangChain）学习笔记.md`第1节里"Supervisor vs Router"那条区分是同一件事的两次表述。

## 6 有状态实现——想让Router也有记忆，要付出什么代价

### 6.1 工具包装法——最简单的做法：把整个router流程包成一个工具，塞进一个有状态的对话agent里

```python
@tool
def search_docs(query: str) -> str:
    """跨多个文档源搜索"""
    result = workflow.invoke({"query": query})
    return result["final_answer"]

conversational_agent = create_agent(
    model,
    tools=[search_docs],
    prompt="You are a helpful assistant. Use search_docs to answer questions."
)
```

**这个做法的本质**：router本身还是无状态的（`workflow`每次都从头跑），但外面套了一层有状态的`conversational_agent`，"记忆"这件事完全交给外层agent处理，router自己什么都不用改。

### 6.2 完整持久化——真的让router本身有记忆

如果想让router步骤本身记住之前发生过什么，得用持久化存储消息历史；路由到某个agent时，从状态里取出之前的消息，选择性地并入这次agent调用的上下文。

**官方专门给了一条警告，这是这篇文档里最值得记的一点**："有状态router需要自定义历史管理。**如果router跨轮在不同agent之间切换，不同agent可能有不同的语气或提示词，会导致对话体验割裂**。可以考虑用Handoffs或Subagents模式作为替代。"——**这条警告直接点出了Router模式的一个结构性短板**：Router的设计初衷就是"每次独立分类分发"，一旦想让它承担"跨轮对话"这种需要一致性的职责，反而会暴露出"不同agent语气不统一"这种体验问题，官方自己都建议这种情况下别硬凑，换Handoffs或Subagents。

## 值得记的点

- **`Send` vs `Command(goto=...)`这组对比，是这次翻译里最实用的一条代码级知识**——单目标路由用`Command`，多目标并行路由用`Send`，这是LangGraph自己的原语，之前在`Persistence（LangGraph）学习笔记.md`里学超级步骤/并行节点的时候提到过"可能并行"的节点执行，`Send`就是触发这种并行分发的具体手段。
- **"Router跨轮切换agent会导致语气不统一"这条警告，是三篇LangChain文档里唯一一处明确指出某个模式的"体验上的坏味道"**，不是性能/成本层面的权衡（像`Multi-agent overview`那篇的调用次数/token对比），是**用户能直接感知到的割裂感**——这提醒了一件事：多agent架构选型不能只算"调用次数/token"这种可量化的账，"用户体验一致性"这种软指标同样是决策依据，而且往往是Router这种"无状态、一次性分类"模式最容易踩的坑。
- **Router和Subagents的核心区别，落到一句话就是"决策是一次性的分类动作，还是一个持续存在、会记事的agent"**——这条区分线索贯穿了这三篇LangChain文档，也是判断"这次任务该用Router还是Subagents"最快的判断标准，比套用"多跳/并行化"这些抽象维度更直观。
