## 学习笔记：LangChain《Context Engineering for Agents》

原文：[Context Engineering for Agents](https://www.langchain.com/blog/context-engineering-for-agents)，作者The LangChain Team，发布于2025年7月2日。

**说明**：这不是逐句翻译，是按原文结构整理的中文学习笔记——保留关键英文原句的简短引用并标注出处，完整论述请点开原文自己读。文中提到的产品/论文例子，凡是之前在[ContextWindow.md 2.3节](ContextWindow.md#23-上下文工程的四种手段write--select--compress--isolate)已经下载源码逐一核实过的（Write/Select/Compress/Isolate各一个真实例子），会特别标出；其余例子只是转述原文说法，我没有再去逐一查证对应仓库/论文，读的时候留意这个区别。

---

### 0 引子：为什么会有"Context Engineering"这个说法

原文开篇把LLM类比成一种新的操作系统：模型是CPU，它的context window则相当于RAM——一种有限的"工作内存"。既然是有限资源，"往这块工作内存里放什么"自然就成了一个需要专门管理的工程问题。

原文引用了Andrej Karpathy的说法来定义这件事：context engineering是"the delicate art and science of filling the context window with just the right information for the next step"（往context window里填入恰好够用的信息，为下一步做准备，是一门精妙的艺术与科学）。

原文强调，Cognition（Devin背后的公司）和Anthropic都把context engineering视为构建可靠agent时的头等大事——因为真实agent经常需要跨越几十上百轮交互才能完成一个任务，每一轮都在往context里添加新内容，管不好就会失控。

原文还引用了独立研究者Drew Breunig总结的"长context会带来的四类问题"，这四个词值得记住，之后遇到agent行为异常可以按这四类去排查：

| 问题 | 含义 |
|---|---|
| **Context Poisoning**（上下文污染） | 一个幻觉或错误信息被写入context后，后续推理会反复引用这个错误内容，越滚越偏 |
| **Context Distraction**（上下文分心） | context太长，模型开始过度依赖历史内容而不是自己的训练知识去推理，表现变差 |
| **Context Confusion**（上下文混乱） | 塞进太多不相关的工具/信息，模型选错工具或答非所问 |
| **Context Clash**（上下文冲突） | context里前后出现了相互矛盾的信息或指令，模型无所适从 |

这四类问题合起来就是"为什么需要Write/Select/Compress/Isolate"这四招的动机——每一招都是在针对性地防止某一类问题发生。

---

### 1 Write：把信息存到窗口外

除了[ContextWindow.md](ContextWindow.md)里已经用`langmem`源码验证过的memory-write机制，原文还提到了两类真实例子：

**Scratchpads（便签）**：
- Anthropic的多agent研究系统里，LeadResearcher会把执行计划写进便签，防止对话超过200,000 token时被截断丢失
- 原文提到两种常见实现方式：agent通过工具调用主动写入一个文件；或者作为运行时state对象的一个字段，跟着整个session走

**Memories（跨会话长期记忆）**：
- 学术界的Reflexion论文：agent在任务失败后先做一次"反思"，把反思结果当作记忆存起来，供未来任务参考
- Generative Agents论文：周期性地把过去的一堆具体反馈/经历，合成整理成更抽象的记忆
- 真实产品：ChatGPT、Cursor、Windsurf都有跨会话自动生成记忆的机制（这条和之前验证过的`langmem`长期记忆思路是同一套逻辑，产品层面的具体实现原文未展开源码级细节）

---

### 2 Select：从全集里挑相关的拉进来

除了已验证的`langgraph-bigtool`语义检索工具的例子，原文还提到：

**Memory怎么选**：原文把记忆分成三类——episodic（具体的示例/往事）、procedural（该怎么做的指令/流程）、semantic（客观事实）。真实产品的做法：
- Claude Code用`CLAUDE.md`存放procedural记忆（规则/约定）
- Cursor、Windsurf用各自的rules文件做同样的事
- ChatGPT的一个真实痛点：记忆检索有时会"选错时机"触发，比如用户只是想生成一张图，却意外被注入了不相关的位置信息记忆，让用户觉得"记忆系统失控了"——这是Select没做好的典型反面案例

**工具怎么选**：原文提到把RAG的思路应用在"工具描述"这一层——对工具的描述文本做语义检索，只挑出跟当前任务相关的工具子集给模型，官方博客给的数字是这样做能让工具选择的准确率提升到3倍（原文未展开具体测试方法，我没有去复核这个倍数）

**知识/代码怎么选（RAG）**：原文用Windsurf的代码agent举例——在大代码库场景下，单纯用embedding做语义检索并不可靠，实际要综合AST解析、语义分块（semantic chunking）、grep/文件检索、知识图谱、重排序（reranking）等多种技术一起用，纯向量检索会漏掉很多真正相关的代码

---

### 3 Compress：窗口内的历史，想办法变小

除了已验证的`langmem` `summarize_messages`机制，原文还提到：

**Context Summarization（摘要）**：
- Claude Code的"auto-compact"：context用到95%时自动触发，把之前的用户-agent交互轨迹总结成摘要（这和ContextWindow.md里提到的Claude Code auto-compact是同一个功能，从两个不同角度都被引用到了）
- 原文提到摘要可以是递归式的（在已有摘要基础上不断续写）或分层式的（按不同粒度分层总结）
- 摘要不一定只发生在"整个对话快满了"这一个时机，也可以用在更小的局部——比如一次搜索工具调用返回了一大段结果，先把这段结果单独总结精简，再放进主对话；或者多agent交接任务的边界处，把交接内容压缩后再传给下一个agent
- Cognition提到他们用一个专门微调过的模型来做知识交接时的总结，目的是确保关键事件不会在压缩过程中被漏掉

**Context Trimming（裁剪）**：跟"总结"不同，裁剪是更简单粗暴的做法——用一些启发式规则直接删掉旧消息（不需要模型参与）。原文提到了一个专门的研究工具Provence，是训练出来专门做问答场景下上下文裁剪的模型。

---

### 4 Isolate：拆到独立的地方分开处理

除了已验证的`langgraph-supervisor`多agent例子，原文还提到了两类不同的隔离方式：

**Multi-agent隔离**（这是原文举例最多的一类）：
- OpenAI Swarm库的设计动机就是"关注点分离"（separation of concerns）：每个子agent都有自己专属的工具集、指令、以及独立的context window
- Anthropic自己的多agent研究系统做过真实验证：多个各自专注、视野狭窄的子agent并行工作，效果超过单个agent独自处理——但代价是token消耗大约是单agent的15倍左右，这是原文明确提到的真实成本数字

**Environment隔离**（这一类和"多agent"是不同维度，之前在ContextWindow.md里没有覆盖到）：
- HuggingFace的Deep Researcher项目：用一个`CodeAgent`生成可执行代码，代码放进一个沙箱（sandbox）里单独运行，只有最终的返回值才会被传回给LLM
- 这样做的好处是能把那些"token很贵但LLM不需要逐字看"的内容（比如图片、音频这类大对象）隔离在LLM的context之外，LLM只需要知道"运行结果是什么"，不需要把整个中间产物塞进window

**State隔离**：通过在agent的state schema里设计字段，某些字段会被暴露给LLM（进入它的context），另一些字段则只在程序内部流转、选择性地才会被用到——这本质上是把"agent能看到的" 和"程序内部记录的"分成两层，是一种更细粒度的隔离方式。

---

### 5 原文提到的LangGraph/LangSmith自家能力（了解即可，不是这篇笔记的重点）

原文最后一部分是LangChain公司在给自己的产品打广告，简单记录一下都提了什么，不展开：

- **可观测性基础**：LangSmith能追踪agent的执行轨迹和token用量，方便先诊断问题出在哪个环节，再决定用Write/Select/Compress/Isolate里的哪一招
- **Write**：LangGraph的checkpointing机制可以把整个agent state持久化下来，充当"便签"的角色；长期记忆则同时支持"文件式"（比如存用户画像/规则）和"集合式"存储，`langmem`库提供了对应的辅助工具（这部分我们已经在ContextWindow.md里读过`langmem`真实源码了）
- **Select**：图里每个node都能精细地控制自己能看到state里的哪些字段；长期记忆支持embedding检索；`langgraph-bigtool`库专门用来对付"工具多到不能全塞进prompt"的场景（同样已读过真实源码）
- **Compress**：因为LangGraph是比较底层的编排框架，开发者可以在任意一个node或者工具调用后面自己加总结/裁剪逻辑，官方也内置了一些消息列表管理的工具函数
- **Isolate**：state schema原生支持字段隔离；官方支持接入E2B、Pyodide这类沙箱环境；`langgraph-supervisor`、`langgraph-swarm`这类多agent库把"拆分给不同子agent"这件事封装成了现成的模式（`langgraph-supervisor`我们也读过真实源码了）

---

### 6 结论

原文的结尾没有什么新论点，就是把Write/Select/Compress/Isolate四条策略再强调一遍，主张"上下文工程"已经是构建可靠agent的一项必备技能，并且顺带说LangSmith+LangGraph能形成一个"发现问题→实施对应策略→测试效果→再迭代"的闭环工作流。

---

延伸阅读：四个策略里真正下载源码验证过实现细节的部分，在[ContextWindow.md 2.3节](ContextWindow.md#23-上下文工程的四种手段write--select--compress--isolate)，配了一张莫兰迪配色的示意图[img_context_engineering_four_pillars.png](img_context_engineering_four_pillars.png)。
