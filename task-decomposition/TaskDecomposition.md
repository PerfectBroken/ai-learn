# 任务分解策略

Layer 3的最后一章。主题：主agent收到一个任务后，怎么推理、拆解成子任务、进一步派发给子agent。这一章最初是按"要不要拆/怎么拆/委派prompt怎么写/失败后怎么重新规划"四小节搭起来的，材料学到后期发现"怎么拆"这一节内部其实藏着四种性质不同的执行拓扑，硬塞在一节里不利于横向对比——于是重新组织成"背景决策层（要不要拆）+ 四种执行拓扑 + 横切层（委派prompt/失败重规划）"这个结构，是跟用户逐轮核对Magentic-One和Dynamic Workflow"是不是同一种拓扑思路，只是执行手段不同"这个问题之后，共同定下来的。

## 目录

- [1 背景](#1-背景)
- [2 要不要拆——复杂度评估](#2-要不要拆复杂度评估)
- [3 四种执行拓扑一览](#3-四种执行拓扑一览)
- [4 拓扑一：单agent自管TODO](#4-拓扑一单agent自管todo)
- [5 拓扑二：多agent委派](#5-拓扑二多agent委派)
  - [5.1 并发子模式](#51-并发子模式)
  - [5.2 顺序子模式](#52-顺序子模式)
- [6 拓扑三：Dynamic Workflow（脚本编排）](#6-拓扑三dynamic-workflow脚本编排)
- [7 拓扑四：多agent动态轮流调度+重规划](#7-拓扑四多agent动态轮流调度重规划)
- [8 横切层：委派prompt与失败重规划](#8-横切层委派prompt与失败重规划)
  - [8.1 委派prompt怎么写](#81-委派prompt怎么写)
  - [8.2 失败后怎么重新规划](#82-失败后怎么重新规划)
- [9 参考资料](#9-参考资料)

## 1 背景

**这一点也容易搞错，需要专门澄清**："任务分解"看起来像是伴随multi-agent系统天然出现的能力，但查了真实时间线后发现——它作为一个被显式讨论、被结构化实现的技术问题，比"multi-agent协作"这个更大的概念出现得还要早一点，而且最早做出来的不是后来在multi-agent编排上最出名的几家。

查到的最早显式机制，是**2023年3月28日**Yohei Nakajima提出的"Task-Driven Autonomous Agent"（BabyAGI的原型）——三个独立函数循环运行：执行当前任务、基于目标和上一次结果生成新任务、把任务列表重新排序。这套机制在今天看非常粗糙（纯靠prompt文本解析，没有复杂度评估、没有失败后重新规划、也不支持并行），但"用一份外部化、可追踪的任务列表驱动agent"这个思路，从这里就定下来了。同期的AutoGPT（仓库创建于**2023年3月16日**）走的是相近但独立的路线。

从这个粗糙的起点，到工程上第一次拿出可验证机制的节点，中间隔了将近两年——**2024年11月**，微软AutoGen的Magentic-One论文第一次给"任务分解+失败恢复"配上了完整的机制（Task Ledger/Progress Ledger两份账本、失速计数器、重新规划流程），而且用消融实验量化了这套机制的价值（去掉后性能下降31%）。这中间学术界还有Plan-and-Solve（2023年5月提交arXiv）、ReWOO（2023年5月提交arXiv）、LLMCompiler（2023年12月提交arXiv）等论文探索更结构化的规划方案——**这几篇这次只验证了提交日期，没有深入读机制细节，如实留一笔账，不能编**。

值得一提的是，"任务分解"被某家公司的官方文档正式命名成一个独立的workflow模式，是相当晚的事——**2024年12月**，Anthropic在《Building Effective AI Agents》里把这个模式叫作"Orchestrator-workers"，比BabyAGI晚了快21个月。

**当前进度快照**：把这条时间线拉到现在看，会发现一个更有意思的现状——本章学到的几家，没有一家同时具备"能真正并行扇出"和"运行时能重新规划"这两种能力：Claude Code的Dynamic Workflows和刚开源不久、内部设计明确照着Claude Code思路做的DeepSeek Harness，把分解决策一次性冻结进模型现写的脚本里，换来了更强的并发表达力，但脚本一旦开始跑，编排层面就不会再有新的推理介入；AutoGen的Magentic-One反过来，运行时每一步都能重新评估、失速了还能整个重新规划，但天生只能一次调度一个agent，做不了真正的并发。这个"鱼与熊掌不可兼得"的现状，就是本章接下来要仔细拆开讲的内容。

**四种执行拓扑的划分依据**：不是"用了几个agent"，是"这次分解决策**在什么时候、由谁**做出的"——单agent拓扑里agent自己现场决定下一步；多agent委派拓扑里主agent（或用户）决定派给谁；Dynamic Workflow里决策被脚本作者一次性冻结进代码；Magentic-One式的动态调度里，决策是每一步都重新评估、还能被修正的。这条主轴贯穿整章，判断一份新材料该归进哪一类、要不要收录，都靠它。

## 2 要不要拆——复杂度评估

这是四种拓扑之上的前置判断——横切所有拓扑，回答的是"该不该启动某种形式的分解"，不是"拆完之后长什么样"。

**核心机制：不是靠模型自己拿捏，是把量化的扩展规则直接写进提示词里**。Anthropic原文明确指出"智能体很难判断不同任务的适当努力程度"——这是个真实存在的失败模式（早期版本会"为简单查询生成50个子智能体"），解法是在提示词里嵌入显式的扩展规则：

| 任务复杂度 | 分配的资源 |
|---|---|
| 简单事实查找 | 1个agent，3-10次工具调用 |
| 直接比较 | 2-4个子agent，每个10-15次调用 |
| 复杂研究 | 10+个具有明确分工的子agent |

这条规则起两个作用：帮首席智能体高效分配资源，同时**防止在简单查询上过度投入**（原文点名这是早期版本"常见的失败模式"）——复杂度评估的价值不只是"保证复杂任务有足够资源"，同等重要的是"防止简单任务被过度拆分浪费token"，是双向的约束。评估复杂度的具体机制是**扩展思考（extended thinking）**：首席智能体用它来"规划其方法，评估哪些工具适合任务，确定查询复杂度和子智能体数量，并定义每个子智能体的角色"——复杂度判断不是一次隐式的内部打分，是模型在一段可见的思考过程里显式推理出来的。

**Claude Code**（详见[Dynamic Workflows（Claude Code）学习笔记.md](Dynamic%20Workflows（Claude%20Code）学习笔记.md) §4、§7）：`workflowSizeGuideline`是另一种量化复杂度旋钮——`small`<5个agent/`medium`(默认)<15个/`large`<50个，明确是"给Claude的建议不是硬上限"，运行时另有16并发/1000总量的硬上限兜底。跟Anthropic写死在提示词里的经验规则不同，这是一个可随时调整的配置项。另外`TodoWrite`工具"三个以上不同动作才建todo"的阈值，跟LangChain`TodoListMiddleware`的"3步阈值"是两家独立收敛到的同一个数字；更有意思的是新模型（Opus 4.8/Sonnet 5等）**默认不给todo工具**，因为不写外显todo也能追踪多步工作——暗示"要不要显式分解"这件事本身也在随模型能力演进而变化。

**LangChain**（详见[To-do List Middleware（LangChain）学习笔记.md](To-do%20List%20Middleware（LangChain）学习笔记.md) §2）：翻源码确认"3步阈值"的确切出处——`WRITE_TODOS_TOOL_DESCRIPTION`原文"If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool"，跟Claude Code的"3个以上不同动作"几乎一字不差。**这次材料里唯一一处把"分解本身的代价"讲给模型听的地方**——system prompt原话"Writing todos takes time and tokens, use it when it is helpful...But not for simple few-step requests"，Anthropic的复杂度规则和Claude Code的size guideline都只讲"该配多少资源"，没有哪家像这里一样直接告诉模型"这个分解动作本身要花钱，别滥用"。

**DeepSeek Harness**（详见[Dynamic Workflows（DeepSeek Harness）学习笔记.md](Dynamic%20Workflows（DeepSeek%20Harness）学习笔记.md)）：跟Claude Code`workflowSizeGuideline`（软性建议）不同，Harness的`maxTotalAgents`是请求里可以直接传的一个**硬顶**——虽然脚本本身看不到、也改不了这个值，但调用方可以按运行场景直接调低总量上限，是配置层面而不是提示词层面的复杂度约束。

**OpenAI**（来源：《A Practical Guide to Building Agents》第16页"When to consider creating multiple agents"）：给了两条具体判据——**Complex logic**（prompt里if-then-else条件分支太多、模板难以维护时，按逻辑段拆给不同agent）、**Tool overload**（不是工具数量本身，是工具之间的相似度/重叠度；实测有的实现能扛住15个界限清晰的工具，有的用不到10个重叠工具就撑不住，判断标准是"改工具描述/参数还是解决不了混淆"）。这条判据跟前面几家是同一类东西——量化/半量化的复杂度门槛，只是维度换成了"逻辑分支复杂度"和"工具集重叠度"。原文态度也很明确："Our general recommendation is to maximize a single agent's capabilities first...so often a single agent with tools is sufficient"——先把单agent的能力用到头，不是默认拆。

**Claude Code补充：一份场景式（非量化）的决策清单**（详见[Sub-agents任务分解相关摘录（Claude Code）学习笔记.md](Sub-agents任务分解相关摘录（Claude%20Code）学习笔记.md) §3）：用**主对话**——任务需要频繁来回迭代打磨；多阶段共享大量上下文；只是快速的针对性小改动；延迟敏感。用**subagent**——任务会产出不需要留在主上下文的冗长输出；想强制限定工具权限；工作本身自包含、能总结成摘要返回。**这跟前面几家判据的形式不同**——不是数字门槛，是场景列举，说明同一个"要不要拆"的问题，各家给判据的**形式**本身也不统一。

## 3 四种执行拓扑一览

| 拓扑 | 决策发生的时机 | 决策者 | 典型执行形状 | 代表案例 |
|---|---|---|---|---|
| **一、单agent自管TODO** | 运行时、逐步 | agent自己 | 单agent按状态机走完一份自建列表，默认顺序，允许有限并行 | LangChain `TodoListMiddleware` |
| **二、多agent委派** | 运行时（并发子模式）或授权时（顺序子模式常由用户点名） | 主agent 或 用户 | 派生独立subagent，一次性并发扇出，或按序链式执行 | Anthropic多agent研究系统、Claude Code "Chain/Run parallel research" |
| **三、Dynamic Workflow** | 脚本编写那一刻，**一次性冻结** | 主agent（写脚本时） | 脚本代码持有循环/分支/中间结果；脚本执行阶段不再有编排层面的LLM决策 | Claude Code Dynamic Workflows、DeepSeek Harness |
| **四、多agent动态轮流调度+重规划** | **每一步实时评估** | Orchestrator（逐步） | 一次只指挥一个agent发言，失速则重写整个计划 | AutoGen Magentic-One |

**拓扑三和拓扑四最容易被误认为同一类**（都是"多agent+看起来智能的编排"），但两者站在"决策活性"这条轴的两端：拓扑三决策一次性冻结、换来能表达并行/复杂分支等更宽的执行形状；拓扑四决策逐步现场做、能处理写计划时完全没预料到的失败模式，但表达形状天生受限于"一次只选一个agent发言"，做不了真正的并发扇出。这条差异不是实现细节，是这一章"谁在什么时候做的分解决策"这条主轴的直接体现，因此两者在本章保持独立分类，不合并。

## 4 拓扑一：单agent自管TODO

`TodoListMiddleware`（详见[To-do List Middleware（LangChain）学习笔记.md](To-do%20List%20Middleware（LangChain）学习笔记.md)）回答的是一个**跟拓扑二完全不同的问题**——不是"分给谁做"，而是"**单个agent自己怎么给自己的工作拆步骤**"。同一个"任务分解"话题下，"分解后交给别人执行"和"分解后自己按步骤执行"是两个独立的问题，容易被混为一谈。

机制上：`write_todos`工具**每次调用是整份列表替换**（不是增量patch），且被`after_model`钩子**代码级禁止并行调用**——这是提示词约束之外少见的、真正靠代码强制的分解相关约束。三态生命周期（`pending`/`in_progress`/`completed`）由system prompt原文约束推进方式："mark todos as completed as soon as you are done with a step"（禁止批量事后补标）、"unless all tasks are completed, you should always have at least one task in_progress"（不能出现"没有任何任务在进行中"的空窗期）。默认是顺序推进，但允许有限并行——工具描述原文明确"you can have multiple tasks in_progress at a time **if they are not related to each other and can be run in parallel**"，判据是"互相不相关+能并行"，不是简单地"可以有多个in_progress"。

## 5 拓扑二：多agent委派

**触发这个拓扑的前提机制**（详见[Sub-agents任务分解相关摘录（Claude Code）学习笔记.md](Sub-agents任务分解相关摘录（Claude%20Code）学习笔记.md) §1）：如果已经存在预先配置好的专职subagent，Claude Code的自动委派靠的是**任务描述跟subagent`description`字段的语义匹配**，不是复杂度打分——这是委派决策的另一个维度，判断的不是"要不要拆"，是"这次任务该不该交给某个现成的专家"。

### 5.1 并发子模式

Anthropic这套系统是**动态**分解的代表：首席智能体在收到查询后**运行时**分析、制定策略、生成子智能体，不是提前写死的固定步骤链——研究这类开放性任务本质上是路径依赖的，没法提前硬编码一条固定路径。驱动这个动态决策的是**扩展思考**（见第2节）——同一次推理同时完成"评估复杂度"和"决定怎么拆"两件事，不是分两步做的。并行派发上，首席智能体一次并行启动3-5个子智能体，而不是串行。

**Claude Code补充**（详见[Sub-agents任务分解相关摘录（Claude Code）学习笔记.md](Sub-agents任务分解相关摘录（Claude%20Code）学习笔记.md) §2）：官方"Run parallel research"模式——对独立调研，同时派生多个subagent并行工作，各自独立探索，最后Claude综合发现，"最适合调研路径互相不依赖的场景"。原文附警告：subagent完成后结果都要返回主对话，多个subagent都返回详细结果会大量消耗主上下文；需要长期并行跑或装不进一个上下文窗口的工作，该用独立session配合跨session消息传递，不是硬塞进同一个对话里的多个subagent。

### 5.2 顺序子模式

**Claude Code**（详见[Sub-agents任务分解相关摘录（Claude Code）学习笔记.md](Sub-agents任务分解相关摘录（Claude%20Code）学习笔记.md) §2）：官方"Chain subagents"模式——对多步骤工作流，依次使用多个subagent，每个完成后把结果和相关上下文传给下一个。**这个例句要单独核对**：官方给的例子"先用code-reviewer subagent找性能问题，再用optimizer subagent去修"里，用户已经点名了具体哪两个subagent、按什么顺序，Claude只是照做，"拆成几步、每步派给谁"不是Claude现场推理出来的。但"Chain subagents"这个模式**本身**是中性的——标题那句"ask Claude to use subagents in sequence"只是笼统指示，不强制用户必须把话说满；用户完全可以只给一个笼统指令，把"具体拆几步、每步谁来做"留给Claude自己判断。**更准确的定位是：这是一种"用户的prompt辅助/引导agent完善任务流程"的中间形态**——用户负责点出"这里需要链式分解"这个大方向和边界，具体怎么拆可以用户说清楚，也可以留给Claude自己判断，取决于这次prompt给到多细。官方选的这个具体例子刚好是"用户说得比较满"的那一端，不能代表整个模式都排除了模型自己决策的情况。

## 6 拓扑三：Dynamic Workflow（脚本编排）

**Claude Code**（详见[Dynamic Workflows（Claude Code）学习笔记.md](Dynamic%20Workflows（Claude%20Code）学习笔记.md) §1-3，本章对"静态vs动态"讲得最直接的材料）：官方四路对比表把"谁掌握plan"作为核心区分维度——subagents/skills/agent teams都是Claude逐轮决定接下来做什么，结果进Claude的上下文；workflows是**把plan整个搬进代码**，脚本自己拿着循环、分支和中间结果，Claude的上下文只看到最终答案。真实JS API：`agent()`派生单个子agent，`pipeline()`对列表逐项扇出，是最直接的"map式分解"原语。官方给了六种典型分解模式（逐项审计+对抗验证/反复修复直到通过/隔离副本迁移/逐项审查后合并/多源调研后综合/分轮搜索直到无新发现）。

**Resume语义揭示了一个分解粒度的设计考量**：按agent启动顺序回放，中途停在扇出中间代价最大——已启动但没跑完的agent B要重跑，即便已完成的C/D只是因为在B之后启动，也要陪着重跑。**任务分解得越细，暂停恢复时保住的进度反而越多**——这是设计分解粒度时容易被忽略的实际考量。

**DeepSeek Harness补充**（详见[Dynamic Workflows（DeepSeek Harness）学习笔记.md](Dynamic%20Workflows（DeepSeek%20Harness）学习笔记.md)）——一份直接对着Claude Code逐条写"哪里不一样、为什么"的内部设计决策记录，"脚本约定"一节明确写"Claude Code-compatible"。三处刻意的分歧点：

1. **误用hook要"炸得响"，不能悄悄降级成`null`**——Claude Code参数写错会降级成`null`，跟"子任务正常失败"分不清；Harness让`WorkflowError{fatal:true}`直接杀死整个脚本，靠`instanceof`对着脚本自己vm realm之外定义的类做判定，脚本没法伪造fatal来绕过。
2. **`meta`拆成独立JSON参数，不写进脚本体**——Claude Code的写法要求host先执行一部分脚本才能读出meta，是隔离漏洞；Harness把meta单独作为参数传，脚本主体保持drop-in可复用。
3. **放弃resume能力，换脚本能碰时钟/随机数的确定性自由**——Claude Code默认后台执行+支持`resumeFromRunId`按调用顺序回放缓存，代价是禁止脚本读时钟；Harness选择前台同步执行、不做resume。两家在"要确定性可重放"还是"要脚本写起来更自由"之间做了相反的选择。

**"脚本会不会写错"这个问题，答案是没有静态保证，靠的是分层的快速失败+模型自我纠错**：脚本语法/meta格式在任何子agent真正跑起来之前就同步校验完；语法过了但hook用错参数，运行时立刻`fatal`杀脚本。两类错误都变成这次工具调用的`isError`结果原样喂回模型，模型靠的是跟其他任何工具调用失败一样的读错误-改重试循环——**这套系统只能防"用错了这套自定义API"，防不住"API都用对了但整体设计逻辑有问题"，这是它保证边界的诚实上限**。

**边界澄清**：Claude Code Dynamic Workflows的"保存workflow复用"（存成`.claude/workflows/`下的命令，之后直接调用，不用模型重新生成脚本）不属于本章讨论范围——一旦复用，"要不要拆、怎么拆"这个决策就不再是模型针对当次任务现场做出的，退化成了跟`Building Effective AI Agents学习笔记.md`里"Workflow"（开发者预先定死的固定代码路径）同一类东西。**这不是各家通用能力**——DeepSeek Harness的设计文档把"保存/打包的workflow"明确列进了"Deferred (documented non-goals)"，原文点名"a `.deepseek/workflows/` registry, slash-command API"是故意暂不做的，目前只有Claude Code一家确认支持。

## 7 拓扑四：多agent动态轮流调度+重规划

**Microsoft AutoGen Magentic-One**（详见[Magentic-One（AutoGen）学习笔记.md](Magentic-One（AutoGen）学习笔记.md)，官方user guide+技术报告+源码三重验证）：Orchestrator维护两份账本——**外层循环**管**Task Ledger**（事实四分类：已知事实/待查事实/待推导事实/教育性猜测+一份自然语言、逐条bullet-point的计划，技术报告强调这份计划"更像是分步执行的一个提示hint，不需要被严格照着执行"）；**内层循环**管**Progress Ledger**（每步用结构化JSON回答五个问题：任务完成没/是否在循环/是否在推进/该谁发言/给什么指令，每个判断都强制带`reason`）——**这就是本章"决策每一步实时评估"这句话的具体机制**：内层循环每一步都要重新调用一次LLM去判断"该谁发言"，不是一次性写死的执行顺序。

**失速判定靠一个升降双向的计数器**（源码验证，不是论文散文描述能看出来的细节）：没进展或在循环就`+1`，否则`-1`（下限0）——容错偶发小卡顿，不会因为中间一步不顺就立刻触发重新规划。**超过阈值后走两步固定prompt**：先做根因分析（"上一轮到底哪里出了问题"）→再重新定计划（"避免重复同样的错误"），且明确要求"至少更新一条教育性猜测"——这是一次真正的"计划被修正"，不是提前设想好的重试分支被触发。**消融实验量化了这套机制的价值**：GAIA验证集上，去掉完整ledger机制（换成简单的GroupChat轮流发言），性能下降**31%**。

阈值这次翻源码发现论文（≤2）和当前开源默认值（`max_stalls=3`）**不一致**，如实记录未强行统一；另外团队级还有一个独立的`max_turns`（默认20）总量上限，跟失速计数器是两套不同机制，跟"子Agent终止条件"章节学过的"总量上限vs失速检测是两个维度"结论一致，只是这次作用在整个团队上。

**跟拓扑三的核心差异**（详见第3节表格）：Magentic-One内层循环本质上是**一次只选一个agent发言**，天生顺序调度，没有"并行扇出"这个概念；这跟Dynamic Workflow能用`parallel()`/`pipeline()`做真正并发，是两条相反的设计取舍——**表达能力和决策活性，这两条轴上两者是反过来的**。

## 8 横切层：委派prompt与失败重规划

这两个问题不属于任何一种拓扑，是拓扑之上的工艺细节——委派prompt怎么写主要适用于拓扑二/四（真正把工作派给"另一个"agent的场景）；失败后怎么重新规划原则上适用于所有拓扑，但目前查到的具体机制集中在拓扑三、四。

### 8.1 委派prompt怎么写

Anthropic原文结论很直接："没有详细的任务描述，智能体会重复工作、留下空白、或未能找到必要的信息。"委派prompt要包含四个要素：**目标**、**输出格式**、**关于使用哪些工具和来源的指导**、**清晰的任务边界**。

**反面案例（原文实测踩过的坑）**：一开始允许首席智能体给简单指令，比如"研究半导体短缺"——这类指令太模糊，导致子智能体互相踩线：一个子智能体探索了2021年汽车芯片危机，另外两个子智能体重复调查2025年当前供应链，"没有有效的分工"。委派prompt写得不够具体，代价不是"效率低一点"，是直接产生冗余劳动和信息空白，问题不会在执行阶段被自动纠正。

**委派完成后的收尾环节——CitationAgent**：所有子智能体的发现汇总给首席智能体后，还有一个专门的`CitationAgent`负责处理最终报告、把每条声明溯源到具体引用位置，这是"分解-执行-汇总"这条链路里容易被忽略的最后一环。

### 8.2 失败后怎么重新规划

Anthropic原文对这一点只有一句话："LeadResearcher综合这些结果并决定是否需要更多研究——如果需要，它可以创建额外的子智能体或完善其策略。"确认了"结果不够就继续/调整策略"这个反馈环确实存在，但没有交代任何具体机制。

**Magentic-One给出了目前最完整的答案**（详见第7节）——升降双向的失速计数器、根因分析+重新定计划的两步固定prompt、消融实验量化了机制的价值（去掉ledger性能降31%）。

**Claude Code Dynamic Workflows给了另一种实现路径**（详见[Dynamic Workflows（Claude Code）学习笔记.md](Dynamic%20Workflows（Claude%20Code）学习笔记.md) §3、§5）：官方"反复修复直到检查通过"/"分轮搜索直到没有新发现"两种分解模式，判据都是**"连续N轮无进展就停"**——跟Magentic-One的失速判据（`is_progress_being_made`）性质完全一致，一个靠脚本层面显式记录产出，一个靠agent自我评估打分，说明**"进展停滞"（而不是"资源耗尽"）是判断"要不要继续"的一个跨厂商通用信号**，只是拓扑三是把这个判据提前编码进脚本里（写脚本时就设定好"连续两轮无新发现"），拓扑四是运行时活的自我评估——同一个信号，落在决策活性这条轴的两端，跟第3节表格的结论完全对得上。

## 9 参考资料

**已有笔记，本章重新提炼/回填，不重译**

- `multi-agent-orchestration/How we built our multi-agent research system学习笔记.md`——复杂度扩展规则、委派prompt四要素、并行派发，目前最系统的一份材料
- `multi-agent-orchestration/Agent orchestration（OpenAI）学习笔记.md`——"Orchestrating via LLM vs via code"角度，价值已被Claude Code/DeepSeek Harness的拓扑三材料充分覆盖，不再单独回填

**本章精读**

- Claude Code官方文档，[Orchestrate subagents at scale with dynamic workflows](https://code.claude.com/docs/en/workflows.md) + [Sub-agents](https://code.claude.com/docs/en/sub-agents.md)（任务分解相关摘录）——**已精读**，四路对比表"谁掌握plan"、`agent()`/`pipeline()`分解原语、六种典型分解模式、`workflowSizeGuideline`量化复杂度旋钮、按启动顺序回放的resume语义、Chain/Run parallel research两种官方命名模式、自动委派的语义匹配机制、要不要用subagent的决策清单
- LangChain官方文档，[Prebuilt middleware — To-do list](https://docs.langchain.com/oss/python/langchain/middleware/built-in#to-do-list) + 源码`langchain_v1/langchain/agents/middleware/todo.py`——**已精读**，"3步阈值"确切出处、完整工具描述+system prompt原文、"分解本身有代价"的成本意识提示词、代码级禁止并行调用
- Microsoft AutoGen，[Magentic-One user guide](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html) + [技术报告](https://arxiv.org/abs/2411.04468)（arXiv 2411.04468）+ 源码`_prompts.py`/`_magentic_one_orchestrator.py`/`_magentic_one_group_chat.py`——**已精读**，Task Ledger/Progress Ledger机制、升降双向的失速计数器、消融实验（去掉ledger性能降31%）
- DeepSeek，[`deepseek-ai/deepseek-harness`](https://github.com/deepseek-ai/deepseek-harness)（MIT协议，开发者预览版，非商业产品）内部设计文档`.agents/notes/implemented/feature/2026-07-05-dynamic-workflows.md` + 接口文档`docs/subsystems/workflow.md` + 源码`packages/workflow/`——**已精读**，本章计划外新增的第五个来源，逐条对着Claude Code写明"哪里不一样、为什么"的设计决策记录
- OpenAI，《A Practical Guide to Building Agents》（PDF）——**已精读**，第16页"Complex logic"/"Tool overload"两条判据，Manager/Decentralized两分类经核对后不完全对应本章的拓扑二/拓扑三/拓扑四划分（Manager≈拓扑二并发子模式，Decentralized≈Handoffs，均不等同于Dynamic Workflow或Magentic-One），已在第2节收录判据本身，分类部分不采用

**投票精选：候选材料的处理结果**

上一轮deep-research多agent投票选出的5篇候选里，OpenAI的两篇（PDF、Cookbook）已精读，核实其"Manager/Decentralized"分类跟本章拓扑不完全对应后只摘取了判据部分；Claude Agent SDK《Subagents》确认是`multi-agent-orchestration/Subagents in the SDK（Claude Code）学习笔记.md`的同一页面（URL重定向验证），跳过；Claude Code《Subagents》产品文档已按本章需要摘译（[Sub-agents任务分解相关摘录（Claude Code）学习笔记.md](Sub-agents任务分解相关摘录（Claude%20Code）学习笔记.md)）；Claude Code《Common Workflows》尚未处理，待定。

**暂缓引入**

- CrewAI——未深入调研，先不引入，视本章骨架搭起来后是否还缺独立视角再决定

**明确排除的范围**

- Claude Code Track todos——文档实质内容是"外部应用代码怎么观察Claude内部todo工具调用"，属于可观测性/SDK集成问题，不是分解推理问题，已移出本章（笔记暂存在项目根目录，等Layer 4可观测性正式开始学再安置）
