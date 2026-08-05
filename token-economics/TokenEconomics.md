## 目录
- [1 Token到底是什么](#1-token到底是什么)
  - [1.1 核心直觉：BPE按统计频率合并，不认识"词"](#11-核心直觉bpe按统计频率合并不认识词)
  - [1.1.1 统计数据：大语料下的平均token消耗率](#111-统计数据大语料下的平均token消耗率)
  - [1.1.2 实测案例](#112-实测案例)
- [2 Token价格](#2-token价格)
  - [2.1 真实Agent场景下的平均token消耗](#21-真实agent场景下的平均token消耗)
- [3 Token成本优化策略](#3-token成本优化策略)
  - [3.1 模型路由：用便宜模型节约Token成本](#31-模型路由用便宜模型节约token成本)
  - [3.2 缓存策略设计：缓存命中到底省了什么计算](#32-缓存策略设计缓存命中到底省了什么计算)

## 1 Token到底是什么

### 1.1 核心直觉：BPE按统计频率合并，不认识"词"

Token不是"一个字"，也不是"一个词"，是模型训练时统计出来的高频子词片段（分词算法叫BPE，Byte Pair Encoding）。

运作方式大致是：先把句子拆成单字/字节，然后反复找"当前相邻的字里，哪一对在训练时被学到过合并规则、且优先级最高"，就把那一对合并成一个token，循环往复，直到没有更多可合并的规则。

关键点：这个过程完全不理解语义或词边界，只看训练语料里字节对出现的统计频率。所以：

- 同一个"词"在不同上下文里可能被切成不同数量的token（切分是上下文相关的，取决于当前相邻字节对触发了哪条合并规则）
- 越常见的词组合（训练语料里高频共现）越容易被打包成一个token，但"常见"与否不能靠人的语感判断
- **不能靠字符数或语义直觉估算token数，唯一可靠的办法是拿真实tokenizer实测**

不同模型的tokenizer训练语料不同，切法也会完全不同（下面案例里能看到新旧两代OpenAI tokenizer对中文的效率差异巨大）。

#### 1.1.1 统计数据：大语料下的平均token消耗率

前面的案例都是单句，样本太小、偶然性大（比如"今天"在不同句子里切法都不一样）。要得到有代表性的平均值，需要在大语料上统计，单句无法说明整体规律。

**用完整语料整体编码后统计（同一份语料，分别跑不同tokenizer）：**

| Tokenizer / 所属模型 | 分词器类型 | 词表大小 | 平均每个英文单词消耗token数 | 平均每个汉字消耗token数 |
|---|---|---|---|---|
| `o200k_base` / GPT-4o | 字节级BPE | 20万级 | 1.325 | 1.020 |
| `cl100k_base` / GPT-3.5、GPT-4旧一代 | 字节级BPE | 10万级 | 1.330 | 1.579 |
| DeepSeek-V4-Pro官方tokenizer | 字节级BPE | 129,280 | 1.348 | **0.779** |
| Kimi-K3官方tokenizer | tiktoken式BPE | 163,840（163,584基础+256保留位） | 1.350 | **0.922** |

**语料来源（均为真实公开文本，非人工编造）：**
- 英文语料：Project Gutenberg公开的《爱丽丝梦游仙境》+《ni远大前程》全文，约114万字符，21.6万个英文单词
- 中文语料：中文维基百科10篇不同主题条目（人工智能、上海市、经济学、二战、音乐等），约14.3万个汉字
统计脚本：[stat_tokenizer_efficiency.py](stat_tokenizer_efficiency.py)

### 1.1.2 实测案例

以下均为真实tokenizer实测结果（Python `tiktoken` / `tokenizers`库）。同一批句子，分别用三款tokenizer实测：

| 文本 | 字符数 | cl100k_base（GPT-3.5/GPT-4旧一代） | o200k_base（GPT-4o现役） | DeepSeek-V4-Pro官方tokenizer |
|---|---|---|---|---|
| `The weather is nice today.` | 26 | 6 token：`The` ` weather` ` is` ` nice` ` today` `.` | 6 token：`The` ` weather` ` is` ` nice` ` today` `.` | 6 token：`The` ` weather` ` is` ` nice` ` today` `.` |
| `今天天气不错。` | 7 | **8 token**：`今` `天` `天` `�` `�` `不` `错` `。`<br>（`�`为未对齐的UTF-8字节碎片） | 5 token：`今` `天天` `气` `不错` `。` | **4 token**：`今天` `天气` `不错` `。` |
| `我爱你姑娘` | 5 | **9 token**：`我` `�` `�` `你` `�` `�` `�` `�` `�`<br>（大量字节碎片） | 4 token：`我` `爱` `你` `姑娘` | **2 token**：`我爱你` `姑娘` |
| `I love you girl` | 15 | 4 token：`I` ` love` ` you` ` girl` | 4 token：`I` ` love` ` you` ` girl` | 4 token：`I` ` love` ` you` ` girl` |
| `我家大姑娘今天读大学。` | 11 | **14 token**：`我` `家` `大` `�`×5 `今` `天` `读` `大` `学` `。`<br>（"姑娘"两个字被拆成5个字节碎片，"今天""大学"也被拆成单字） | 8 token：`我` `家` `大` `姑娘` `今天` `读` `大学` `。` | **7 token**：`我家` `大` `姑娘` `今天` `读` `大学` `。` |

我们可以发现：

- **英文句子三款tokenizer结果完全一致**（6 token / 4 token），验证了前面统计出的结论：英文BPE合并规则已经收敛，新旧tokenizer、不同厂商之间差异很小。
- **中文句子差异巨大，且这次能直接看到旧tokenizer的问题所在**：cl100k_base对中文经常产生`�`字节碎片（把一个汉字的UTF-8编码拆到两个甚至更多token里，因为它的词表里没有给这些汉字分配完整token，只能退化到字节级编码），token数比字符数还多；o200k_base已经不会切出字节碎片，但合并粒度偏保守（很多常见字仍单独成token）；DeepSeek-V4-Pro合并粒度最激进，常见词组（"今天""我爱你""我家"）经常被整体打包，token数全面最低。
- **同一句话换tokenizer，切法完全不同**（比如"今天"在o200k_base里被拆成"今"+"天天"，在DeepSeek-V4里整体合并）——这印证了1.1节的核心结论：**token切分没有"标准答案"，只有"这个模型实际怎么切"，必须用目标模型自己的tokenizer实测，不能套用别的模型的经验值。**

## 2 Token价格
先看表：

| 模型 | Context window<br>（输入上限） | Max output<br>（输出上限） | Input价格<br>（cache miss） | Cache命中价 | Output价格 | 打满input<br>未命中缓存花费 | 打满input<br>命中缓存花费 | 打满output花费<br>（1000 in + max output） | Claude Code平均请求<br>期望花费<sup>②</sup> |
|---|---|---|---|---|---|---|---|---|---|
| Claude Opus 5 | 1M tokens | 128K tokens | $5.00 /M | $0.50 /M | $25.00 /M | $5.00 | $0.50 | $3.21 | $0.1069 |
| Claude Sonnet 5 | 1M tokens | 128K tokens | $2.00 /M<sup>①</sup> | $0.20 /M | $10.00 /M | $2.00 | $0.20 | $1.28 | $0.0428 |
| GPT-5.6 Sol | 1.05M tokens | 128K tokens | $5.00 /M | $0.50 /M | $30.00 /M | $5.25 | $0.53 | $3.85 | $0.1093 |
| GPT-5.6 Luna | 1.05M tokens | 128K tokens | $0.20 /M | $0.02 /M | $1.20 /M | $0.21 | $0.021 | $0.15 | $0.0044 |
| DeepSeek-V4-Pro | 1M tokens | **384K tokens** | $0.435 /M | $0.003625 /M | $0.87 /M | $0.435 | $0.0036 | $0.33 | $0.0061 |
| DeepSeek-V4-Flash | 1M tokens | **384K tokens** | $0.14 /M | $0.0028 /M | $0.28 /M | $0.14 | $0.0028 | $0.11 | $0.0021 |
| Kimi K3 | 1M（1,048,576）tokens | 官方未公开 | $3.00 /M | $0.30 /M | $15.00 /M | $3.15 | $0.31 | — | $0.0642 |

<sup>②</sup> 按Claude Code真实平均请求（77,800 input token、480 output token、84%缓存命中率）套用各模型定价算出的期望花费，计算方法和详细过程见[AgentRequestExpectedCost.md](AgentRequestExpectedCost.md)。

数据来源：[Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)、[Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing)、[OpenAI models/pricing文档](https://developers.openai.com/api/docs/pricing)、[DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing)、[Kimi K3 pricing](https://platform.kimi.ai/docs/pricing/chat-k3)。

- **同样档位的模型，中美厂商价格能差几十倍**：一次打满输入且完全没命中缓存的极端请求，GPT-5.6 Sol要$5.25，DeepSeek-V4-Pro只要$0.435，差了12倍；打满output的极端请求上，Claude Opus 5是DeepSeek-V4-Pro的近10倍。
- **缓存命中能把input成本压到原来的1/10到1/150**：DeepSeek-V4-Pro打满1M输入，命中缓存只要$0.0036，比没命中的$0.435便宜120倍；Claude系是10倍（$0.50 vs $5.00）——这说明"要不要设计好缓存策略"这件事，在DeepSeek这类厂商身上收益是数量级的，不是锦上添花。
- **output永远比input贵**（Claude、GPT系是5倍左右，DeepSeek是2倍），这也是为什么"打满output"这一列的数字，往往比"打满一整个context window的input"还要贵——output token的绝对数量虽然远小于input上限，但单价高出太多。

### 2.1 真实Agent场景下的平均token消耗

上面的"打满input/output"都是理论上限，不是真实用量。作为agent工程师更该关心的是：**一次真实的agent请求，实际平均要花多少token？** 这个数字决定了你该用哪张表格去估算账单。查了几家主流coding agent的公开数据：

| Agent工具 | 平均input token/请求 | 平均output token/请求 | input:output比例 | 数据来源与可信度 |
|---|---|---|---|---|
| Claude Code | 约77,800 | 约480 | 约163:1 | 第三方实测：追踪1,289次真实请求、共100.9M token，[方法论公开](https://docs.bswen.com/blog/2026-03-10-claude-code-token-usage-per-request/)，其中84%的input命中了缓存 |
| Cursor | 单文件任务8,000~25,000；多文件session可达50,000~150,000 | 1,000~5,000 | 约10:1（行业统计口径，含cache） | 行业博客聚合数据，没有公开原始样本量，可信度弱于Claude Code那份 |
| OpenAI Codex CLI | 只查到"系统上下文2,000~5,000 token/轮"，没有查到完整的平均input/output拆分 | 没查到 | 没查到 | 官方和第三方都没有公开清晰的平均值统计，这里不编数字 |

几个关键发现，直接推翻了"1000 in + 1000 out"这种估算的可用性：

- **真实agent请求的input远比想象中大**：Claude Code平均一次请求要读将近8万token的上下文（文件内容、工具定义、历史对话），是"1000 token"假设的近80倍。这是因为agent每一步操作（读文件、跑命令、看报错）都要把之前的全部上下文重新发一遍给模型，不是从零开始的单轮问答。
- **output占比小到可以忽略**：Claude Code这份数据里，output只占总token的0.6%，input占99.4%（每生成1个token的代码，要重新读166个token的上下文）。Cursor的数据也是同样的量级（output仅占0.6%~7%，取决于是否把cache算进分母）。**这意味着agent场景下，真正决定账单的是input总量和缓存命中率，不是output单价**——这和之前"output比input贵5倍"的结论并不矛盾，只是output的绝对数量太小，贵5倍也扛不住input多两个数量级。
- **缓存命中率是agent真实成本的第一变量**：Claude Code这份数据里84%的input命中了缓存，官方说明缓存能省74%的成本（不加缓存约$310，加了缓存约$82，同样的使用量）。结合上面表格"打满input命中/未命中缓存"差120倍的DeepSeek数据，可以得出一个agent工程实践的核心结论：**优化agent成本，第一优先级是让input尽量命中缓存（复用上下文、少做无关变更），而不是纠结选哪个output更便宜的模型**。

## 3 Token成本优化策略

前两节讲的是"token定价是什么样"，这一节开始讲"怎么花更少的钱办同样的事"。第一个、也是收益最直接的杠杆是模型路由。

### 3.1 模型路由：用便宜模型节约Token成本

**核心思路**：不是所有任务都需要最贵的旗舰模型。先用一个便宜/快的判断器（可以是小模型，也可以是规则）给每个请求的任务复杂度分类，简单任务发给便宜模型，只有复杂/高风险任务才升级到贵模型——本质是拿"判断成本"去换"执行成本"的下降。行业里通常把这套机制叫**LLM Routing**或**Model Cascading**。

**这门生意能成立，靠的是模型间巨大的价差**——这一点我们在第2节已经自己用真实数据验证过了：同一个真实workload（Claude Code的平均请求），最便宜的DeepSeek-V4-Flash（$0.0021/次）和最贵的GPT-5.6 Sol（$0.1093/次）能差52倍。行业报告里给出的价差量级更夸张，最便宜可用模型和最强模型之间能到100倍左右——量级上和我们自己算出来的数字是吻合的，不是道听途说。

**真实做这件事的项目，有扎实数据支撑的案例**：

| 项目/公司 | 性质 | 关键数据 |
|---|---|---|
| RouteLLM | 加州伯克利LMSys实验室 + Anyscale，开源，[ICLR 2025发表](https://github.com/lm-sys/RouteLLM) | 在MT-Bench评测上，用矩阵分解路由器只把14%的请求发给强模型（其余86%发给便宜模型），成本降低85%，同时保住了GPT-4 Turbo 95%的回答质量——这是目前查到的最扎实、可复现的一份数据 |
| Not Diamond | 商业化产品 | 训练了一个跨60+模型的学习型路由器，新模型发布后会重新训练路由策略 |
| Martian | 2024年拿了900万美元A轮融资专做模型路由，技术被Accenture用在自己的多模型平台"Switchboard"上（服务超10亿美元的GenAI项目） | 2026年公开信息显示已经把重心转去做AI可解释性研究，专做"路由"这个方向未必是一门好独立生意，具体原因没有查到一手信息，只做提醒不下定论 |

行业报告给出的总体收益量级：**调优过的路由层能带来40%~85%的账单降幅，且不明显牺牲回答质量**。

**这个机制的核心权衡**：路由本身需要先花一次"判断成本"（哪怕很小），如果判断器不够准，把本该用强模型的任务误判成简单任务发给了便宜模型，省下的钱可能远不够弥补"答错了要返工"的代价——所以路由策略的核心难点不是"要不要做"，是"怎么判断准"，这也是RouteLLM这类项目真正的技术含量所在（不是简单的if/else规则，而是训练出来的分类器）。

Sources：[LLM Model Routing in 2026 - digitalapplied.com](https://www.digitalapplied.com/blog/llm-model-routing-2026-cost-quality-optimization-engineering-guide)、[RouteLLM GitHub](https://github.com/lm-sys/RouteLLM)、[Not Diamond](https://www.notdiamond.ai/)

### 3.2 缓存策略设计：缓存命中到底省了什么计算

前面把缓存命中/未命中的价差当成一个既定事实在用（DeepSeek命中缓存能便宜120倍），这一节回答"为什么能便宜这么多"——答案要回到[transformer/Transformer.md](../transformer/Transformer.md)里已经学过的机制，不是新知识，是把Prefill/Decode和Causal Masking这两块拼到token经济学的账本上。

**缓存命中依赖的底层机制，回顾一下[3.4节](../transformer/Transformer.md#34-transformer如何实现的kv-cache)讲过的因果掩码**：一个token的K、V只取决于它自己和它前面的token，跟后面接了什么完全无关。所以只要两次请求的前N个token完全一样，这N个token在每一层算出来的K、V在数学上必然完全相同——**这不是专门为省钱设计的功能，是自回归架构的因果掩码天然带来的副作用**。

**命中缓存时，一次请求的计算流程被拆成了两半**（对比没有缓存时"整个context从头做一遍prefill"）：

```
context = 前N个token（和上次请求完全重复的前缀）+ 新增M个token

没有缓存：
  N+M个token全部 → Embedding → 逐层[QKV投影 → causal attention → FFN] → 得到N+M个token的隐藏状态

命中缓存：
  前N个token的K、V（每一层）── 直接从显存里的缓存读出来，不重新算
  新增M个token         ── Embedding → 逐层[QKV投影 → FFN]（只对这M个token做）
  attention这一步不能省：新的M个token的Q，依然要和"缓存的N个K/V + 自己这M个的K/V"做点积
    → 但这只是一次矩阵乘法读取，不是重新生成K/V
```

**被跳过的是"对前N个token做QKV投影（Linear矩阵乘）+ 跑FFN"这两步**，而且是逐层都要跳过一次——这两步都是"每个token独立算一次"的计算，跟token数量线性相关，context越长、层数越多，省下来的计算量越大（比如Claude Code那种平均7.8万input token的agent请求，如果命中缓存，相当于免掉了7.8万个token在几十层网络里反复做矩阵乘的计算量，只需要跑新增的几百个token）。**没有被跳过的是attention本身**——新token依然要去"看"全部历史K、V，但这一步的计算量远小于重新生成这些K、V。

这个机制直接解释了几个之前只讲了"是什么"、没讲"为什么"的定价现象：

- **为什么cache read只要base input价格的10%左右**（Claude是0.1倍）——因为对应的真实计算量确实只剩一小部分（新token的QKV投影+FFN，加上一次attention读取），不是促销折扣，是计算量实打实下降带来的成本下降。
- **为什么cache write反而比base input更贵**（Claude是1.25倍~2倍）——因为"写入缓存"这次请求，要做的事是"完整prefill一遍"（这部分和不缓存时一样贵）**外加**"把算出来的K、V额外存一份进缓存"，多出来的存储开销让它比普通input还贵一点。
- **为什么缓存只保留5分钟或1小时，不是永久**——因为KV Cache活在GPU显存里（官方原话是"held in memory only, not stored at rest"），显存是硬约束资源，不可能给每一个出现过的前缀都无限期占着显存，只能设一个TTL，过期清掉；这也是为什么"隔了很久没操作、再回来发一条消息"的第一次请求，几乎必然cache miss——缓存已经被清空了。
- **为什么会有"路由到有缓存的集群"这个设计**：K、V张量是具体存在某台服务器的显存里的，不是全局共享的，所以请求必须被送到持有对应缓存的那台机器才能命中——[官方文档](https://code.claude.com/docs/en/prompt-caching)证实了这一点，部分实现会用session ID做"粘性路由"，把同一个会话的后续请求尽量发到同一台服务器。

**对agent工程实践的启示**：既然缓存命中省的是"前缀部分的QKV投影+FFN计算"，那么设计prompt/context结构时，**把不变的部分（system prompt、工具定义、CLAUDE.md这类固定文件）放在前面，把每次请求都会变的部分（用户当前这句话）放在最后**，才能让前面这一大段始终作为"完全相同的前缀"被命中——这也是Claude Code、Cursor这类agent工具实际的做法，回顾2.1节，Claude Code真实数据里84%的input都命中了缓存，靠的正是这种"固定内容前置、变化内容后置"的context组织方式。
