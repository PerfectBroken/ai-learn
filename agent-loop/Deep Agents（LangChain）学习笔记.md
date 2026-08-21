# Deep Agents（LangChain `deepagents`包）

来源：
1. 原始博客（提出"deep agent"概念）：Harrison Chase（LangChain创始人），《Deep Agents》，langchain.com/blog/deep-agents，发布于2025-07-30
2. 官方文档（当前最新版）：docs.langchain.com/oss/python/deepagents/overview
3. API参考：reference.langchain.com/python/deepagents
4. 源码仓库：github.com/langchain-ai/deepagents

> **重要背景，先纠正一个容易产生的误解**：`deepagents`**不是**一个跟LangGraph平级、另起炉灶的独立开源agent框架。它是LangChain团队在我们上一章刚学完的`create_agent`基础上，包了一层"预置好系统提示、规划工具、子agent机制、虚拟文件系统"的**更主观（opinionated）的成品agent**。官方文档原话："`deepagents` is a standalone library built on top of LangChain's core building blocks for agents, and it uses the LangGraph runtime for durable execution, streaming, human-in-the-loop, and other features."（`deepagents`是一个独立的库，但构建在LangChain核心构建块之上，使用LangGraph运行时来实现持久执行、流式传输、人在回路等功能）。所以它的agent loop骨架，大概率就是我们上一章学的`create_agent`那套`model↔tools`循环+middleware节点，只是**预置了几个官方写好的middleware**（文件系统、子agent、任务规划等），不是一套全新的loop设计。这一点会在下面读的时候反复印证，读完后我们可以专门去查源码验证这个猜测。

---

## 一、为什么需要"Deep"Agent——原始博客的核心论点（Harrison Chase，2025-07-30）

### 1.1 "浅层"agent的问题

> "Using an LLM to call tools in a loop is the simplest form of an agent. This architecture, however, can result in 'shallow' agents that fail to plan and act over longer, more complex tasks."

翻译：用LLM在一个循环里调用工具，是agent最简单的形式。但这种架构容易产生"浅层（shallow）"agent——在更长、更复杂的任务上，规划和行动能力不足。

作者提到，这个探索主要是被Claude Code启发的：Claude Code的哪些特性让它成为一个通用工具？这些特性能不能被抽象、泛化到其他领域？

### 1.2 什么agent算"deep"

当前主流的agent架构确实就是"在循环里跑，调用工具"——这个核心算法本身没有变。但Deep Research类应用、Manus、Claude Code这类"能在更长时间跨度上规划和执行复杂任务"的agent，作者称之为"deep agents"（因为它们能对一个主题做深入研究）。

**这些agent"深"在哪里？作者给出四个要素**（核心算法完全一样，差异全在这四点）：

1. **详细的系统提示（Detailed System Prompt）**
   Claude Code被重新构造出来的系统提示很长，包含大量关于"怎么用工具"的详细说明，还有少样本示例（few-shot）来说明特定场景下该怎么表现。作者强调："Prompting still matters!"（提示词依然很重要）。

2. **规划工具（Planning Tool）**
   Claude Code用一个待办列表（to-do list）工具。有意思的是——原文强调这个工具"doesn't really do anything"（这个工具本身不做任何实际的事），本质上是个空操作（no-op）。它纯粹是一种"上下文工程（context engineering）"策略，用来让agent保持在正确的轨道上。规划——哪怕只是通过一个空操作的工具调用完成——是deep agent在长时间跨度任务里表现更好的重要组成部分。

3. **子Agent（Sub Agents）**
   Claude Code能生成子agent，把任务拆分下去；你也可以自定义子agent以获得更细的控制。这带来"上下文管理和提示词捷径（context quarantine and prompt shortcuts）"的效果。Deep agent做深入研究，主要就是靠派出专门针对单一任务的子agent，让它们在自己的范围里深入下去。

4. **文件系统（File System）**
   Claude Code能读写文件系统，不只是为了完成任务，也用来记笔记；它同时充当agent和所有子agent之间协作的共享工作区。Manus是另一个深度依赖文件系统当"记忆"用的deep agent例子。deep agent运行很久、会积累大量需要管理的上下文，有个方便的文件系统来存（以后再读）能帮上大忙。

### 1.3 开源实现：`deepagents`包

作者在博客里提到，为了让大家更容易在自己的垂直领域里构建deep agent，他利用一个周末的时间打磨了一个开源包`deepagents`（`pip install deepagents`），内置组件正好对应上面四个要素：

- 受Claude Code启发、但改得更通用的系统提示
- 一个空操作的待办列表规划工具（跟Claude Code的做法一样）
- 生成子agent的能力，也可以指定自己的子agent
- 用LangGraph已有的state概念模拟出的"虚拟文件系统"

可以传入自定义提示（会被插进更大的系统提示里作为额外说明）、自定义工具、自定义子agent，来定制自己的deep agent。

---

## 二、官方文档：Deep Agents现在长什么样（2026年最新版）

博客是2025年中提出概念时的早期设计；下面是当前`docs.langchain.com`上描述的、更成熟的架构，四要素已经演化成四个更工程化的组件层。

### 2.1 一句话定位

> Deep Agents是构建LLM驱动的智能体和应用的最简方式——内置文件系统上下文管理、子agent生成、长期记忆；任务规划、技能（skills）等可选功能可以按需扩展。

### 2.2 最小示例

```python
from deepagents import create_deep_agent

def get_weather(city: str) -> str:
    """Get weather for a given city."""
    return f"It's always sunny in {city}!"

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    tools=[get_weather],
    system_prompt="You are a helpful assistant",
)

agent.invoke(
    {"messages": [{"role": "user", "content": "what is the weather in sf"}]}
)
```

**注意函数签名跟上一章的`create_agent(model, tools, system_prompt=...)`几乎一模一样**——这是"它是`create_agent`的封装"这个判断的第一处直接证据。

### 2.3 四大组件（官方原话是"agent harness"，即"agent的成品外壳/脚手架"）

官方原文定位："It uses the same core tool-calling loop as other agent frameworks, but with built-in capabilities that make agents reliable for real tasks."（它和其他agent框架用的是同一套核心工具调用循环，区别在于内置了让agent在真实任务里可靠的一些能力）——**这句话本身就是对博客里"核心算法完全一样，差异在于外围能力"这个论点的最新版确认**。

四层能力：

#### ①执行环境（Execution Environment）——agent真正采取行动的地方

- **工具 + MCP**：`tools=`参数支持自定义函数、LangChain工具、任意MCP服务器的工具
- **虚拟文件系统**：内置`ls`/`read_file`/`write_file`/`edit_file`/`delete`/`glob`/`grep`/`execute`这几个工具，后端可插拔（内存state、本地磁盘、LangGraph store、自定义后端）；`read_file`还支持返回图片/视频/音频/文档等多模态内容块
- **文件系统权限**：通过`permissions=`参数声明式配置哪些路径能读/能写，规则按声明顺序"先匹配优先"，可以用来把子agent的权限收得比父agent更窄
- **代码执行**：两种方式——沙箱后端暴露`execute`工具（跑shell命令，装依赖、跑测试都行）；或者一个基于QuickJS的轻量JS解释器（`eval`工具，没有shell/文件系统/网络访问，适合做循环、批处理这类确定性计算）
- **流式**：新增`stream.subagents`，让每个委托出去的子任务都有自己独立的消息流/工具调用流/嵌套子agent流

#### ②上下文管理（Context Management）——控制agent知道什么、能跑多久、跨会话记住什么

- **技能（Skills）**：遵循"Agent Skills标准"，每个技能是一个带`SKILL.md`的目录，可以带脚本/模板/参考文档。**渐进式披露**：启动时只读`SKILL.md`的前言（frontmatter），真正需要用到某个技能时才读它的完整内容——这跟我们`skills/Skills.md`里记的、Claude Skills的"progressive disclosure"是同一个设计思路，可以对照着看
- **记忆（Memory）**：用`AGENTS.md`文件，通过`memory`参数传入。跟技能不同，记忆文件**总是**被加载（不是渐进式的），存在可配置的后端里（state/store/文件系统三选一），agent还能根据交互反馈更新自己的记忆
- **总结与上下文卸载**：把"输入上下文（系统提示+记忆+技能+工具定义）→ 压缩（内置卸载和总结）→ 隔离（子agent只返回最终结果）→ 长期记忆（虚拟文件系统跨线程存）"串成一条完整的上下文管理链路
- **提示缓存**：对Anthropic和Amazon Bedrock模型，`create_deep_agent`会自动对系统提示里"每轮都重复"的静态部分（基础指令、记忆、技能）加提示缓存，默认开启、不用额外配置

#### ③委托（Delegation）——把大问题拆成能并行的小单元

- **任务规划**：可选的`TodoListMiddleware`，给agent一个`write_todos`工具维护结构化任务列表（状态有`pending`/`in_progress`/`completed`）。**注意版本变化**：从v0.7开始这个规划中间件改成默认不启用（需要手动传入`middleware=[TodoListMiddleware()]`），早期版本是默认内置的
- **子Agent**：内置`task`工具，主agent可以据此临时创建子agent处理隔离的/长期运行的/并行的任务。官方强调了几个关键约束：
  - 每次调用都是全新的上下文（新agent实例）
  - 子agent自主运行直到完成
  - **单次握手（single round-trip）**：只向主agent返回一份最终报告
  - **无状态消息传递**：子agent是无状态的，不能往回发多条消息——这跟我们之前在Turn Loop里深挖过的"主agent的loop是等待子agent结果、还是只看到启动成功就继续"这个问题直接相关，值得读完后专门验证一下`deepagents`里`task`工具的调用是不是阻塞的

#### ④指导（Guidance）——人类对agent行为的运行时控制

- **人在回路**：跟LangGraph的中断机制集成，用`interrupt_on`参数配置——比如`interrupt_on={"edit_file": True}`会在每次`edit_file`调用前暂停，等人类批准/修改/拒绝。这跟我们上一章读过的`create_agent`里`HumanInTheLoopMiddleware.after_model`的HITL机制看起来是同一套底层能力，只是`deepagents`把它包成了一个更简单的参数

---

## 三、和上一章`create_agent`的关系（读完后重点验证的猜测）

结合博客原话（"核心算法完全一样"）和文档原话（"和其他框架用同一套核心工具调用循环"），目前的猜测是：

**`deepagents`的`create_deep_agent`本质上是调用`create_agent`，只是预先注册好了一批官方middleware**（大概率包括：管理虚拟文件系统的`FilesystemMiddleware`、管理子agent的`SubAgentMiddleware`、可选的`TodoListMiddleware`，外加一个预先写好的、受Claude Code启发的长系统提示），**图结构（`model`↔`tools`循环 + 各middleware的`before_*`/`after_*`节点）应该和我们上一章画的那张流程图是同一套骨架，不是另起炉灶的新loop**。

这个猜测我们留到你读完这份笔记之后，一起翻源码（`deepagents`仓库的`create_deep_agent`函数）验证——如果属实，这一章能省很多力气，因为loop本身的机制我们已经在`create_agent`那章弄清楚了，`deepagents`真正新增的知识点会集中在"文件系统后端怎么实现""子agent到底是不是阻塞调用""渐进式披露技能怎么读取"这几个具体功能点上，而不是loop设计本身。
