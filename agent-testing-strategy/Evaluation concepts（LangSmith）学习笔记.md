# Evaluation concepts 学习笔记

来源：LangChain官方文档，LangSmith产品线，地址 https://docs.langchain.com/langsmith/evaluation-concepts 。本笔记不逐字翻译，是转述论证逻辑，关键定义用引用块标出。

**这篇文档跟前面几篇最大的不同**：Anthropic和OpenAI那几篇讲的主要是"怎么设计一次评估、怎么把评估结果转成harness改进"，这篇是**产品文档**——讲的是LangSmith这个具体工具把"评估"这件事拆成了哪些标准化的产品概念（dataset/example/experiment/run/thread/evaluator），以及这些概念怎么对应到开发流程的不同阶段。它还引入了一个前面几篇都没提过的关键维度：**离线评估和在线评估的区分**。

## 目录

- [1 要评估什么——先定义"好"是什么样子](#1-要评估什么先定义好是什么样子)
- [2 离线评估 vs 在线评估](#2-离线评估-vs-在线评估)
- [3 评估生命周期：三个阶段](#3-评估生命周期三个阶段)
- [4 核心评估对象](#4-核心评估对象)
- [5 Evaluators（评分器）](#5-evaluators评分器)
- [6 Reference-free vs Reference-based](#6-reference-free-vs-reference-based)
- [7 最佳实践](#7-最佳实践)
- [8 Evaluations vs Testing——一个容易混淆的区分](#8-evaluations-vs-testing一个容易混淆的区分)
- [9 速查表：离线 vs 在线](#9-速查表离线-vs-在线)
- [10 跟本章已学内容的对照](#10-跟本章已学内容的对照)

## 1 要评估什么——先定义"好"是什么样子

开篇的核心论点，跟《Demystifying evals》第一句话是同一个出发点：LLM输出是非确定性的，这让"回复质量好不好"变得很难判断，evals就是把"好"这个模糊概念拆解成可衡量的东西的方法。

**具体做法**：先把系统拆成关键组件（LLM调用、检索步骤、工具调用、输出格式化），给每个组件定义质量标准；**从人工整理5-10个"好"长什么样的例子开始**，这些例子既是ground truth，也决定了后续该用哪种评估手段。原文给了三类系统各自的例子：RAG系统看"检索到的文档相不相关""答案准不准、全不全"；Agent看"工具选得对不对、参数格式对不对、走的路径对不对"；聊天机器人看"回复有没有用、符不符合品牌调性、有没有真正解决用户意图"。

## 2 离线评估 vs 在线评估

这是这篇文档最核心的一层划分，前面读过的几篇Anthropic/OpenAI文章基本只讨论了"离线"这一半，这篇文档把"在线"这一半也系统讲清楚了。

**离线评估**用于**部署前测试**：benchmark式对比多个版本找最优、回归测试确认新版本没有变差、单元测试验证单个组件的正确性、backtest用历史数据测试新版本。离线评估的评测对象是数据集里的**example**——带参考输出的、事先整理好的测试用例，定义了"好"应该长什么样。

**在线评估**用于**生产监控**：实时追踪线上流量质量、检测异常模式/边缘案例、把生产反馈转化成离线数据集的素材来源。在线评估的评测对象是来自真实链路追踪的**run**和**thread**——真实的生产trace，**没有参考输出**。

原文点出这个区别带来的直接后果：

> This difference in targets determines what you can evaluate: offline evaluations can check correctness against expected answers, while online evaluations focus on quality patterns, safety, and real-world behavior.

翻译：评测对象不同，决定了能评估的内容也不同——离线评估能对着"标准答案"检查对不对，在线评估没有标准答案可比，只能关注质量模式、安全性、真实世界的行为表现。

## 3 评估生命周期：三个阶段

原文把离线/在线评估安排进了一条随应用成熟度演进的时间线：

**阶段一：开发阶段用离线评估**——正式上线前，用离线评估验证功能、对比不同方案、建立信心。

**阶段二：初次部署后用在线评估**——上线之后，用在线评估监控生产质量、发现意料之外的问题、收集真实世界的数据。

**阶段三：持续改进——两者配合成一个迭代反馈循环**：在线评估发现的问题会变成新的离线测试用例，离线评估验证修复是否有效，在线评估再确认修复在生产环境里真的生效了。**这个"在线发现问题→离线固化成用例→验证→在线确认"的循环，跟你上一篇学的Agent Improvement Loop notebook里"trace→反馈→eval→HALO诊断→Codex实现→新一轮trace"这个飞轮结构是同一类思路，只是LangSmith这里额外强调了"生产流量"这个离线评估天然缺失的信号来源**。

## 4 核心评估对象

离线评估和在线评估分别作用在不同的对象上。

**离线评估的对象**：

- **Dataset（数据集）**：一组用于评估应用的example集合。
- **Example（用例）**：一条测试输入+参考输出的配对，包含**Inputs**（传给应用的输入变量）、**Reference outputs**（可选，不会传给应用本身，只在评估打分时使用）、**Metadata**（可选，用于给数据集做筛选视图）。
- **Experiment（实验）**：某个具体应用版本在整个数据集上跑一遍评估的结果集合，记录每条example对应的输出、评分器打分、执行trace。同一个数据集上通常会跑多个experiment，对比不同的prompt或模型配置，LangSmith支持把多个experiment并排比较。

**在线评估的对象**：

- **Run（运行）**：一次部署应用的单次执行trace，包含实际输入、实际输出、所有中间步骤（工具调用、LLM调用等子run）、以及标签/用户反馈/延迟这类元数据。**跟离线的example不同，run没有参考输出**，在线评估器必须在不知道"正确答案"的情况下判断质量，只能依赖质量启发式规则、安全检查、无参考评估技巧。
- **Thread（会话）**：一组相关run构成的多轮对话集合。在线评估可以在thread这个层级运行，评估整段对话而不是单轮，能衡量跨轮次的连贯性、话题保持、整段交互下来用户满不满意这类"会话级"属性，这是单轮评估覆盖不到的维度。

## 5 Evaluators（评分器）

Evaluators是**workspace级别的资源**，负责给应用表现打分，同时服务离线和在线两种评估，根据能拿到什么数据自动调整输入。因为是workspace级别的，同一个evaluator可以挂到多个tracing project和dataset上重复使用，不用每次都重新配置。

**Evaluator的输入因评估类型而不同**：离线evaluator收到的是**Example**（数据集里的输入+参考输出+元数据）加上**Run**（应用在这条输入上实际跑出来的输出和中间步骤）；在线evaluator只收到**Run**（生产trace的输入+输出+中间步骤，没有参考输出）。

**Evaluator的输出**统一叫**Feedback**：一个（或一组）字典，包含`key`（指标名）、`score`或`value`（数值型指标用score，分类型指标用value）、`comment`（可选，打分的理由说明）。

**四种评估技术**，跟《Demystifying evals》的三分法（代码/模型/人工）对得上，但LangSmith把"模型"这一类又拆细了一层：

- **Human（人工）**：人工审查输出和执行trace，原文引用Hamel Husain的观点，认为这"往往是评估最有效的起点"。LangSmith提供**Annotation queues（标注队列）**，分Single-run（单run对着自定义评分项打分，可以用来给数据集攒新用例，也支持写自由格式的"断言"[assertion]供后续离线评估器复用）和Pairwise（两个run并排比较哪个更好，适合实验之间的快速A/B对比）两种队列类型。
- **Code（代码）**：确定性的规则函数，适合检查"回复结构是不是非空""生成的代码能不能编译""分类是否精确匹配"这类客观问题——对应《Demystifying evals》里的code-based grader。
- **LLM-as-judge（模型评判）**：用LLM给输出打分，评分规则和标准编码进prompt里，分**无参考**（检查是否含有攻击性内容、是否符合某个标准）和**有参考**（对照参考答案检查事实准确性）两种。原文提醒这类评分器需要仔细核查打分结果、反复调prompt，加入few-shot示例（在评分prompt里放几个"输入-输出-期望评分"的样例）通常能提升表现。
- **Pairwise（成对比较）**：不直接给单个输出打分，而是比较两个版本的输出哪个更好——可以靠启发式规则（比如哪个更长）、LLM、或人工评审。原文给的适用场景：**当直接给单个输出打分很难、但比较两个输出哪个更好相对容易时**（比如摘要任务，判断两篇摘要哪篇信息量更大，通常比给单篇摘要打一个绝对分数容易）。

## 6 Reference-free vs Reference-based

这是贯穿整篇文档的一条重要分类线，决定了一个evaluator能不能用在在线评估上：

**无参考evaluator（reference-free）**——不需要对照"预期输出"就能评估质量，因此离线、在线都能用：安全检查（毒性检测、PII检测、内容策略违规）、格式校验（JSON结构、必填字段、schema合规性）、质量启发式规则（回复长度、延迟、特定关键词）、无参考的LLM-as-judge（清晰度、连贯性、有没有帮助、语气）。

**有参考evaluator（reference-based）**——必须有参考输出才能用，因此**只能用在离线评估**：正确性（跟参考答案的语义相似度）、事实准确性（对照ground truth核查事实）、精确匹配（有已知标签的分类任务）、有参考的LLM-as-judge（拿输出跟参考答案比质量）。

原文给出的设计建议：无参考evaluator能同时用在离线测试和在线监控上，保持一致性；有参考evaluator能在开发阶段做更精确的正确性检查——两者不是互斥关系，是分别覆盖了评估策略里不同的那一半。

## 7 最佳实践

**构建数据集的三种思路**：**人工整理**（推荐的起点，做10-20个覆盖常见场景和边缘情况的高质量例子，定义"好"应该是什么样）；**历史trace**（生产上线之后，把真实trace转成用例——用户反馈差评的run、启发式规则挑出来的可疑run（比如延迟特别长、报错）、以及用LLM去检测哪些对话值得关注这三个来源）；**合成数据**（从已有的高质量人工例子当模板去生成更多例子）。

**数据集组织的两个机制**：

- **Splits（切片）**：把数据集里的example分成命名子组，常见模式有ML式的训练/验证/测试集切分（防止模型在训练数据上表现好、未见数据上表现差）、按类别切分（数据集横跨多种任务类型时分开评估）、分阶段发布（探索性的例子先隔离开，准备好了再并入主评估集）。原文特别提醒split和metadata的区别：split是评估用的高层级组织分组，metadata是单条example的信息标签（比如来源）；传统机器学习里一条example通常只属于一个split，但LangSmith允许一条example同时属于多个split，适合那种同时满足好几个评估类别的例子。
- **Versions（版本）**：example发生变化时LangSmith会自动创建数据集版本，可以给重要节点打tag，CI流程里可以锁定特定版本，避免数据集更新意外破坏已有的评估流程。

**人类反馈收集**：原文强调人类反馈往往是最有价值的评估信号，尤其是主观性强的质量维度，机制上通过Annotation queues做结构化收集（标记特定run供审查、在统一界面收集标注、把标注过的run转入数据集供以后评估用），跟行内标注（inline annotation）配合，多出分组、指定评分标准、配置审查者权限这些额外能力。

## 8 Evaluations vs Testing——一个容易混淆的区分

这一节原文给出了一个前面几篇文章都没明确讲过的概念澄清，值得单独记：

> **Evaluation measures performance according to metrics.** Metrics can be fuzzy or subjective, and prove more useful in relative terms. They typically compare systems against each other.
>
> **Testing asserts correctness.** A system can only be deployed if it passes all tests.

翻译：**评估（evaluation）**衡量的是"表现好不好"，指标可以是模糊的、主观的，通常更适合用来做相对比较（这个版本比那个版本好多少），而不是给出一个"过/不过"的硬性判断；**测试（testing）**断言的是"对不对"，是非黑即白的——系统必须通过所有测试才能部署。

两者不是互斥的：评估指标可以被转化成测试——比如回归测试可以断言"新版本在相关指标上必须不劣于基线版本"，这样一条本来是"模糊打分"的评估指标，就变成了一条"过/不过"的硬性测试条件。原文还提到一个工程上的实用建议：当系统运行成本较高时，测试和评估应该合并在同一次运行里跑，不要分开跑两遍浪费成本；LangSmith的评估也可以直接用pytest或Vitest/Jest这类标准测试工具来写。

## 9 速查表：离线 vs 在线

| | 离线评估 | 在线评估 |
| --- | --- | --- |
| 作用对象 | 数据集（Example） | Tracing Project（Run/Thread） |
| 能拿到的数据 | 输入、输出、参考输出 | 只有输入、输出 |
| 什么时候用 | 部署前、开发阶段 | 生产环境、部署后 |
| 主要用途 | benchmark对比、单元测试、回归测试、backtest | 实时监控、生产反馈、异常检测 |
| 评估时机 | 对整理好的测试集批量跑 | 对生产流量实时或准实时跑 |
| 设置位置 | Evaluation标签页（SDK/UI/Playground） | Observability标签页（自动化规则） |
| 数据要求 | 需要整理数据集 | 不需要数据集，直接评估真实trace |

## 10 跟本章已学内容的对照

- **术语基本能跟《Demystifying evals》对上号，但颗粒度更细**：LangSmith的`Example`≈`task`，`Experiment`≈跑完一批`trial`之后的结果集合，`Evaluator`≈`grader`，`Feedback`≈打分结果——但LangSmith多切出了`Dataset`（example的集合容器）和`Run`/`Thread`这两个"离线没有对应物、专属在线评估"的对象，这是主线蓝本没有覆盖到的部分。
- **"离线/在线"这条分类线，本质上是在给《Demystifying evals》里"evals跟其他理解agent表现方式怎么配合"那张对比表（自动化evals/生产监控/A-B测试/用户反馈/人工transcript审查/系统性人类研究）里的前两项，提供了一套具体的产品化实现**——LangSmith的"离线评估"对应那张表里的"自动化evals"，"在线评估"对应"生产监控"，而且明确指出了两者能用的evaluator类型不同（reference-free能两边用，reference-based只能离线用），这是一条主线蓝本没有细讲的具体约束。
- **"Evaluations vs Testing"这条区分，补上了本章目前一直含糊带过的一个措辞问题**——前面几篇笔记里"评估""测试"基本是混着用的（包括这一章标题本身就叫"Agent测试策略"），这篇文档给出了一个可操作的界限：评估给的是相对的、可能模糊的分数，测试给的是过/不过的硬判断，而"评估指标可以被转化成测试"这句话，说明这两者是同一套底层度量体系的两种不同呈现方式，不是两套独立的东西。

## 参考资料

- *Evaluation concepts*, LangSmith Docs, LangChain, https://docs.langchain.com/langsmith/evaluation-concepts
