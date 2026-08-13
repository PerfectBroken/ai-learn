## 目录
- [1 采样参数是什么](#1-采样参数是什么)
  - [1.1 核心机制：从概率分布里怎么选下一个token](#11-核心机制从概率分布里怎么选下一个token)
  - [1.2 主要参数](#12-主要参数)
- [2 诞生背景：贪婪解码与纯随机采样各自的坑](#2-诞生背景贪婪解码与纯随机采样各自的坑)
- [3 解决了什么问题：确定性与多样性的权衡](#3-解决了什么问题确定性与多样性的权衡)
- [4 真实案例：五个agent框架怎么设置采样参数](#4-真实案例五个agent框架怎么设置采样参数)
  - [4.1 主对话agent层：清一色透传，不设框架默认值](#41-主对话agent层清一色透传不设框架默认值)
  - [4.2 OpenClaw：内部子任务的任务类型驱动动态规则](#42-openclaw内部子任务的任务类型驱动动态规则)
- [5 延伸：seed参数](#5-延伸seed参数)
- [6 章节定位](#6-章节定位)

## 1 采样参数是什么

### 1.1 核心机制：从概率分布里怎么选下一个token

模型每生成一个token，最后一步是对全词表算出一个概率分布——比如"今天天气"后面，词表里几万个候选token各自有一个概率（"很"45%、"不"20%、"真"15%、"有点"10%、其他10%）。**选哪个当下一个token，不是模型自己"决定"的，是调用API的人通过几个参数来控制的**——这组控制"怎么从概率分布里挑一个token"的参数，就是采样参数。它不改变模型算出来的概率本身，只改变"怎么从这堆概率里选一个词出来"这个动作。

### 1.2 主要参数

- **Temperature（温度）**：调整概率分布的"锐利/平缓"程度。温度低，分布被拉得更尖锐（高概率的词更容易被选中）；温度高，分布被拉平（低概率的词也有更大机会冒出来，输出更有意外性）。温度为0时基本等价于每次都选概率最高的那个（"贪婪解码"）。
- **Top-p（nucleus sampling，核采样）**：不看全部词表，只从"累积概率加起来刚好到p"的那一小撮高概率候选里选，把概率很低的长尾词直接砍掉不考虑。
- **Top-k**：更简单粗暴的版本，只保留概率最高的k个候选。
- 此外还有重复惩罚（repetition/frequency/presence penalty），用来抑制模型说车轱辘话。

**真实API数值（官方文档实测确认，非猜测）：**

| API | temperature范围 | 默认值 | 备注 |
|---|---|---|---|
| Claude Messages API | 0.0–1.0 | 1.0 | 官方原文明确写"即便temperature设成0，结果也不是完全确定的" |
| OpenAI Chat Completions / Responses API | 0–2 | 1 | — |

来源：[Claude Messages API文档](https://platform.claude.com/docs/en/api/messages)。

## 2 诞生背景：贪婪解码与纯随机采样各自的坑

早期语言模型生成文本，常用两种朴素做法：

1. **贪婪解码（greedy）**：每一步都选概率最高的那个词。问题是开放式生成（讲故事、聊天）时容易产生**退化文本**——重复、乏味，甚至陷入"the the the the"这种死循环。2019年Holtzman等人在论文《The Curious Case of Neural Text Degeneration》里专门研究了这个现象，并提出了**Nucleus Sampling（也就是top-p）**来解决它。
2. **完全按概率随机采样**：又太不可控，偶尔会抽中那些概率极低、几乎语法都不通的"长尾"词，把整段生成带崩。

Temperature这个概念更早，借自统计力学里的玻尔兹曼分布，Hinton在2015年知识蒸馏那篇论文里把它引入深度学习，后来成为控制生成"随机程度"的标准旋钮。Top-k是另一个更早提出的方案（Fan et al. 2018）。

## 3 解决了什么问题：确定性与多样性的权衡

一句话：**在"确定性/连贯"和"多样性/创造力"之间，把选择权交给调用者，而不是让模型自己固定死一种生成风格**。写代码、抽取JSON、解数学题这类要求精确复现的任务，用低temperature/低top-p，让输出接近确定性；写文案、头脑风暴，用高temperature，让输出更有变化和意外性。

需要注意的是：温度本身不直接决定对错，它决定的是"选到非最优候选的概率有多大"——温度越高，模型选中"看起来不错但不是最佳答案"的token的概率就越高，这在数学题、代码、结构化抽取这类只有一个正确答案的任务上，才会体现为"准确度下降"，这是一个间接影响，不是直接的线性关系。

## 4 真实案例：五个agent框架怎么设置采样参数

去查了五个真实开源/闭源agent框架的源码和文档（OpenAI Agents SDK、Claude Agent SDK、OpenClaw、LangGraph、GitHub Copilot），确认它们调用底层LLM API时采样参数具体怎么设置。

### 4.1 主对话agent层：清一色透传，不设框架默认值

| 框架 | 结论 | 来源 |
|---|---|---|
| **OpenAI Agents SDK** | `ModelSettings.temperature`默认值是`None`；发请求时`None`会被直接从请求体里省略，完全交给OpenAI API自己的默认值。没有"工具调用场景自动调低"之类的内置逻辑 | 源码：`src/agents/model_settings.py`、`openai_chatcompletions.py:687` |
| **OpenClaw（主对话agent）** | 每个agent可在配置里选填温度，不填就是`undefined`，同样走纯透传路径 | 源码：`config/types.agents.ts:164`、`embedded-agent-runner/extra-params.ts` |

### 4.2 OpenClaw：内部子任务的任务类型驱动动态规则

除了主对话agent，OpenClaw代码库里还有5处**专门为内部子任务**发起的独立LLM调用，温度全部硬编码——这是本次调研里唯一实锤的"任务类型驱动采样参数"规则：

| 用途 | 温度 | 为什么 | 源码位置 |
|---|---|---|---|
| exec自动审核（判断一条shell命令能不能自动放行） | **0** | 二元判断，要极致确定 | `src/agents/exec-auto-reviewer.ts:408` |
| 模型能力探测（启动时探测某模型支不支持工具调用） | **0** | 同上 | `src/agents/model-scan.ts:315,367` |
| 会话观察器（后台判断当前session状态要不要触发动作） | **0.2** | 判断类，但留一点余地 | `src/gateway/session-observer-completion.ts:81` |
| 进度播报（给用户看的自然语言进度文案） | **0.3** | 要生成自然语言，但不需要"创造力" | `src/auto-reply/reply/progress-narrator-model.ts:111` |
| TTS前置摘要（语音播报前压缩文本） | **0.3** | 同上 | `src/tts/tts-core.ts:141` |

规律很清晰：**纯判断/放行类任务→温度锁死0；需要生成自然语言但不追求多样性的任务→给一点点温度（0.2–0.3）但依然远低于默认值1**。主对话agent因为要应付各种开放式任务，反而是唯一"不主动设默认值，交给厂商"的一层。

## 5 延伸：seed参数

让同样的输入+同样的参数，尽量得到同样的输出——主要用途是agent的**测试/评估pipeline要能复现问题**，不然一个bug今天能重现明天就消失了，没法排查。

- **仅OpenAI支持**：Chat Completions/Responses API的`seed`参数，官方原话是"best effort"（尽力而为），不是100%保证，配了个`system_fingerprint`字段帮助追踪"后端模型有没有偷偷变过"
- **Claude不支持**：Messages API官方文档没有`seed`参数，配合前面提到的"即便temperature=0结果也不完全确定"，意味着**Claude目前没有任何官方途径保证输出可复现**

来源：[Claude Messages API文档](https://platform.claude.com/docs/en/api/messages)、[OpenAI Chat Completions API文档](https://developers.openai.com/api/docs/api-reference/chat/create)。
