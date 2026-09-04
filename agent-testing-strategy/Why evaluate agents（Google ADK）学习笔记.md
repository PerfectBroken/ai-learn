# Why evaluate agents 学习笔记

来源：Google Agent Development Kit（ADK）官方文档，地址 https://adk.dev/evaluate/ 。本笔记不逐字翻译，是转述论证逻辑和关键机制，短句用引用块标出；原文里几段较长的JSON schema示例做了结构化转述，不整段照搬。

## 目录

- [1 为什么传统测试对LLM agent不够用](#1-为什么传统测试对llm-agent不够用)
- [2 评估前的准备](#2-评估前的准备)
- [3 评估什么：轨迹 + 最终响应](#3-评估什么轨迹--最终响应)
- [4 ADK的三种评估方式](#4-adk的三种评估方式)
- [5 内置评估标准](#5-内置评估标准)
- [6 User simulation：动态模拟用户](#6-user-simulation动态模拟用户)
- [7 怎么跑评估](#7-怎么跑评估)
- [8 跟本章已学内容的对照](#8-跟本章已学内容的对照)

## 1 为什么传统测试对LLM agent不够用

开篇论点，跟《Demystifying evals》的出发点一致：传统软件开发里单元测试/集成测试能给出明确的"过/不过"信号；但由于模型本身的概率性，确定性的"过/不过"断言往往不适合评估agent表现，需要的是对**最终输出**和**agent的轨迹（trajectory，即到达这个解法所走的一连串步骤）**同时做质量评估——既要看agent的决策质量，也要看它的推理过程和最终结果。原文的定位建议：

> If you intend to progress beyond prototype, this is a highly recommended best practice.

翻译：如果你打算把agent从原型往前推进，自动化评估是一条强烈推荐的最佳实践。

## 2 评估前的准备

在自动化评估之前，先明确三件事：**定义成功**（对你的agent来说，什么样的结果才算成功）、**识别关键任务**（agent必须完成的核心任务是什么）、**选择相关指标**（用什么指标来衡量表现）。这几点会指导后续评估场景的设计，也会影响真实部署后怎么监控agent行为——**这跟《Demystifying evals》Step 2"写清晰无歧义的task"是同一层意思，只是这里放在了"准备阶段"单独强调**。

## 3 评估什么：轨迹 + 最终响应

跟评估一般的生成式模型不同（后者主要看最终输出），agent评估需要对**决策过程**有更深的理解，原文把它拆成两块：

**评估轨迹和工具使用**：agent在回应用户之前，通常会执行一系列动作——比如对照会话历史消歧义、查一份政策文档、搜索知识库、调用API保存一个工单，这一整套动作序列就是"轨迹"。评估的核心做法是把**实际轨迹**跟**预期轨迹**（ground truth，我们预期agent应该走的那一串步骤）做对比，借此发现过程里的错误和低效之处。

**评估最终响应**：评估agent最终输出的质量、相关性、正确性——这一块跟评估普通生成式模型的做法接近。

## 4 ADK的三种评估方式

ADK提供三种概念上相似、但适用场景不同的评估方式，核心差异是**能处理的数据量、以及测试频率**。

**Test files（测试文件）**——单元测试式，每个文件对应一次简单的agent-模型交互（一个session），适合agent开发过程中快速执行，聚焦简单场景。每个测试文件包含一个session，可以有多个turn（一次用户-agent交互）；每个turn记录**用户输入**、**预期的中间工具调用轨迹**、**预期的中间agent响应**（多agent系统里，主agent依赖子agent逐步推进时，子agent产生的这些中间自然语言响应通常不直接展示给终端用户，但对开发者来说很关键——它们能证明agent确实走对了路径，不是靠运气得到了对的最终答案）、以及**最终响应**这几部分内容。文件底层有正式的Pydantic数据模型撑着（Eval Set/Eval Case两个schema文件）。

**Evalset files（评估集文件）**——集成测试式，一个evalset能装下多个、可能很长的session，适合模拟复杂的多轮对话，因为跑起来更耗时，所以运行频率通常比unit test低。一个evalset文件包含多条"eval"，每条对应一个独立session，由一个或多个turn组成，字段含义跟test file里的一致；此外一条eval也可以定义一个"对话场景"，用来动态模拟用户交互（对应下面第6节的User simulation）。手动写evalset比较复杂，ADK提供了Web UI工具，能直接把已有session捕捉、转换成evalset里的eval用例。

**Conformance testing（一致性测试）**——回归测试式，`adk conformance test`命令验证agent的行为随时间推移是否保持一致，确保代码或模型的更新不会引入回归——做法是把当前agent的实际输出，拿去跟一份**预先录制、人工确认过的"金标准基线"**做比对。使用前要按固定的目录结构（`tests/类别/用例名/`下放`spec.yaml`测试规格、`generated-recordings.yaml`录制的基线交互、`generated-session.yaml`基线session数据）搭好测试目录，并用`adk conformance record`命令自动跑一遍场景、录制生成这些基线文件（不建议手写，因为背后的LLM请求和工具调用数据很复杂）。跑的时候有两种模式：**Replay模式**（默认，拿agent当下的真实LLM请求/响应/工具调用直接对比录制好的基线，抓意外的偏差）、**Live模式**（针对活跃环境跑基于评估的验证，原文标注这个模式还在开发中）。

## 5 内置评估标准

ADK内置了一批可直接使用的评估标准（criteria），覆盖从"工具轨迹精确匹配"到"LLM判定的响应质量"这个跨度，原文给的完整清单（含义直接对照）：

| 标准 | 衡量什么 |
| --- | --- |
| `tool_trajectory_avg_score` | 工具调用轨迹是否精确匹配 |
| `response_match_score` | 跟参考响应的ROUGE-1相似度 |
| `final_response_match_v2` | LLM判定的、跟参考响应的语义匹配度 |
| `rubric_based_final_response_quality_v1` | 基于自定义评分标准，LLM判定的最终响应质量 |
| `rubric_based_tool_use_quality_v1` | 基于自定义评分标准，LLM判定的工具使用质量 |
| `rubric_based_multi_turn_trajectory_quality_v1` | 基于自定义评分标准，LLM判定的多轮轨迹质量 |
| `hallucinations_v1` | LLM判定的响应是否有依据（对照上下文有没有编造内容） |
| `safety_v1` | 响应的安全性/无害性 |
| `per_turn_user_simulator_quality_v1` | LLM判定的用户模拟器质量 |
| `multi_turn_task_success_v1` | agent是否达成了整段对话的目标 |
| `multi_turn_trajectory_quality_v1` | 整段对话轨迹的总体质量 |
| `multi_turn_tool_use_quality_v1` | 对话过程中多次函数调用的质量 |

原文提醒：其中response quality/safety/multi-turn quality这几类需要接入Vertex Gen AI Evaluation Service API，要单独配置认证。如果不指定任何标准，默认用`tool_trajectory_avg_score`（要求工具使用轨迹100%匹配）和`response_match_score`（默认阈值0.8，允许自然语言表述有一定容错空间）这两条。

**选择建议**（原文给的对照，实用性比较强）：CI/CD流水线或回归测试场景优先用`tool_trajectory_avg_score`+`response_match_score`，因为速度快、结果可预测，适合频繁自动跑；有可信参考答案时用`final_response_match_v2`做语义等价判断，比精确匹配更灵活；没有参考答案但能定义"好回复的特征"（比如"简洁""语气友好"）时用`rubric_based_final_response_quality_v1`；想验证工具调用的推理过程本身对不对（比如"工具A必须在工具B之前被调用"）用`rubric_based_tool_use_quality_v1`；检测响应有没有编造内容用`hallucinations_v1`；检测有害内容用`safety_v1`；多轮对话整体是否达成目标用`multi_turn_task_success_v1`。

原文还有一条容易被忽略的限制：**需要预先知道"agent应该用什么工具/给出什么响应"的标准（`tool_trajectory_avg_score`、`response_match_score`、`final_response_match_v2`），不能跟下面的User Simulation一起用**——原因很直观：如果用户的每句话都是AI临场生成的，你没法提前写死一份"agent应该怎么回应"的标准答案。

## 6 User simulation：动态模拟用户

评估对话类agent时，固定一套用户prompt不总是现实的，因为真实对话的走向充满不确定性——原文举的例子：如果agent需要用户提供两个值才能完成任务，用户可能一次性给全，也可能分两次问一次答一次给。ADK允许在一个指定的"对话场景"里，用AI模型动态生成用户的每一句话，来测试agent在这种不确定走向下的表现，而不是死板地照着一份固定脚本走。

## 7 怎么跑评估

ADK提供四种运行评估的方式：

- **Web UI**（`adk web`）：交互式界面，能创建/编辑测试用例、用滑块配置评估阈值（工具轨迹分数、响应匹配分数）、跑完之后可以点开每条Pass/Fail结果看"实际输出 vs 预期输出"的并排对比；配套还有一个**Trace标签页**，可以按用户消息分组查看整条执行链路，每一行能展开看Event原始事件数据/Request发给模型的请求/Response模型返回的响应/Graph工具调用和agent逻辑的可视化流程图这四类细节——这是agent运行时可观测性能力，不只是评估阶段才能用。
- **Programmatically（`pytest`）**：把test file跑起来直接接入`pytest`，能整合进CI/CD流水线或更大的测试套件里。
- **CLI（`adk eval`）**：命令行直接跑一份evalset文件，效果跟Web UI里跑的评估等价，适合接进常规的构建生成和验证流程里；支持在同一条命令里从一个evalset文件/多个evalset文件、或者跑其中指定的几条eval（用逗号分隔eval名字、冒号分隔文件名和eval列表）。
- **`adk conformance`**：跑一致性测试，可以跑全部（不指定路径时自动找`tests/`目录）、跑某个分类、或者跑单个用例，支持加`--generate_report`生成Markdown格式的测试摘要报告。

## 8 跟本章已学内容的对照

- **"轨迹 vs 最终响应"这个二分法，跟《Demystifying evals》的术语基本对得上**：ADK的trajectory对应主线蓝本里的transcript（trace/trajectory是同义词），final response对应outcome；不同的是，ADK把"轨迹匹配"直接做成了一条**内置的、开箱即用的确定性评估标准**（`tool_trajectory_avg_score`），主线蓝本只是提出了这个概念，没有给出具体实现。
- **"test files / evalset files / conformance testing"这三层，正好对应《Demystifying evals》里"capability evals vs regression evals"这条区分，外加一层实现细节**：test files（单测，快速迭代用）和evalset files（集成测试，模拟复杂长会话）大致对应"capability eval"这一类（测agent能不能做到），conformance testing带着"金标准基线"做对比，对应的正是"regression eval"（测agent是不是还能稳定做到、有没有退步）——三层里conformance testing额外要求预先录制、锁定基线数据这套具体机制，是主线蓝本没有细讲的落地方式。
- **User Simulation这个概念，是这几篇里第一次被单独作为一种评估技巧提出来**——之前读过的几篇（Anthropic《Demystifying evals》讲对话agent时提到过"需要用第二个LLM扮演用户"，跟这里的user simulation本质是同一个想法，只是ADK把它做成了产品里可配置的一等功能，还专门标注了哪些评估标准能跟它搭配用、哪些不能。
- **评估标准表格本身是本章目前查到的、颗粒度最细的一份"评估器菜单"**——比LangSmith"Human/Code/LLM-as-judge/Pairwise"四分类、Anthropic"代码/模型/人工"三分类都更具体，直接给到了十几个可以按名字调用的具体指标，是"选哪种grader"这个决策从"选一个类别"下沉到"选一个具体指标"的一个实例。

## 参考资料

- *Why evaluate agents*, Agent Development Kit (ADK) Docs, Google, https://adk.dev/evaluate/
