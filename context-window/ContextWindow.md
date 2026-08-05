## 目录
- [1 Context Window是什么](#1-context-window是什么)
  - [1.1 Context Window 中Token数量有上限](#11-context-window-中token数量有上限)
    - [1.1.1 模型一次"看得见"的token有总量上限，此上限在模型训练时就已经决定](#111-模型一次看得见的token有总量上限此上限在模型训练时就已经决定)
    - [1.1.2 硬件约束：算力和显存决定了新模型敢把原生上下文训多长](#112-硬件约束算力和显存决定了新模型敢把原生上下文训多长)
  - [1.2 为什么只能"追加写入"，不能"中间插入"——KV Cache的强约束](#12-为什么只能追加写入不能中间插入kv-cache的强约束)

## 1 Context Window是什么

> **Context Window是模型单次推理时，能够纳入注意力计算范围的token总量上限——输入和输出共用同一个额度，不是两个独立空间；窗口之外的内容对模型不可见。**

| 来源 | 原文定义 |
|---|---|
| Wikipedia | "the maximum amount of text or other tokenized input available to the model at one time when generating output"；并且明确"usually measured in tokens"，"anything outside that window is not directly available unless it is summarized, retrieved, or provided again" |
| [Anthropic Claude](https://platform.claude.com/docs/en/build-with-claude/context-windows) | "The 'context window' refers to all the text a language model can reference when generating a response, including the response itself." 并强调这不同于训练语料，是模型的"working memory"（工作记忆） |
| [OpenAI](https://developers.openai.com/api/docs/guides/conversation-state) | "The context window is the maximum number of tokens that can be used in a single request. This max tokens number includes input, output, and reasoning tokens." |
| [Google Gemini](https://ai.google.dev/gemini-api/docs/long-context) | "the total number of input and output tokens the model can handle in a single request"，类比是"short term memory"（短期记忆） |

四家表述不同，但对齐的核心事实完全一致。

具体到agent场景，context window随对话轮次演变大概是这样的：

![img_agent_context_window_composition.png](img_agent_context_window_composition.png)


这个窗口要满足的约束，接下来分两节展开：

- **1.1 Context Window 中Token数量有上限**——不是随便定的数字，由训练时的位置编码范围+当下的算力显存共同决定
- **1.2 只能追加、不能在中间插入**——KV Cache的因果掩码性质决定的强约束

### 1.1 Context Window 中Token数量有上限

#### 1.1.1 模型一次"看得见"的token有总量上限，此上限在模型训练时就已经决定

Context Window指的是模型单次推理时，能够纳入注意力计算范围的token总数上限（输入+输出加在一起）——超过这个数字，最前面的内容要么被截断丢弃，要么模型压根不知道怎么处理。

这个上限不是厂商随便定的一个数字，直接由训练时设定的**位置编码范围**决定，回顾一下[transformer/Transformer.md 3.1节](../transformer/Transformer.md#31-embedding)提到过的RoPE位置编码：模型是靠RoPE学会"token之间相对距离"这套模式的，但它只在训练数据实际出现过的距离范围内"练习"过。

**"位置"为什么能被理解成"角度"、RoPE具体怎么把position变成旋转角度**，这部分是Transformer本身的机制，已经移到[transformer/Transformer.md 3.2节"位置编码"](../transformer/Transformer.md#32-位置编码)里了（配了两张图：一张用示意数字讲清楚"相对距离不变、夹角就不变"这个RoPE的核心数学性质，一张用真实句子"今天天气不错。"和DeepSeek真实tokenizer/RoPE参数复现同样的过程）。这里直接承接那边的结论往下讲：**YaRN要处理的问题，正是"相对距离一旦超过训练时见过的范围，这个旋转角度还成不成立"**。

拿一个真实例子来看（DeepSeek-V4-Pro官方config.json）：

```json
"max_position_embeddings": 1048576,
"rope_scaling": {
    "type": "yarn",
    "factor": 16,
    "original_max_position_embeddings": 65536
}
```
**它真正训练时见过的位置范围只有65,536个token，宣传的1M（1,048,576）上下文，是靠YaRN技术把这套位置模式"拉伸"了16倍算出来的**（65,536 × 16 = 1,048,576，对得上）。直觉上理解：模型学会的是"相距在6.5万以内的token关系是什么样的"，YaRN做的事情是把"相距100万"的两个token，在数学上重新映射/压缩到模型训练时熟悉的范围内，让模型不至于面对完全没见过的"超远距离"模式。这也是为什么"官方宣称的上下文长度"和"模型真正擅长处理的长度"经常不是一回事——1.1.2节会展开这一点在算力上的连锁反应，之后学到"有效上下文"时还会再回来讲效果层面的差异。

**YaRN这个"低成本拉伸"具体是怎么实现的**，直觉上可以想象RoPE用一组转速不同的"钟表指针"给每个位置编码角度：转得快的指针（高频维度），在训练的6.5万个位置里已经转了成千上万圈，任何角度都见过、见惯了，直接让它按原速接着转到100万那么远，也不会遇到陌生角度；转得慢的指针（低频维度），训练时可能连一整圈都没转完，如果照原速接着转到100万，会转到一个训练时完全没见过的全新角度——所以YaRN按每个维度的"转速"分成三档处理：转得够快的（论文和DeepSeek config里定义为"转了超过32圈"，也就是`beta_fast=32`）保持原速不变，转得太慢的（"连1圈都不到"，`beta_slow=1`）强制按缩放倍数（DeepSeek是16倍）压慢转速，中间速度的做线性混合过渡。这不是描述性的比喻，是能算出精确数字的，拿DeepSeek-V4-Pro官方config里`beta_fast=32, beta_slow=1, factor=16`这几个真实参数，代入YaRN论文（[arXiv:2309.00071](https://arxiv.org/abs/2309.00071)）的公式，画出来是这样：

![img_yarn_scaling.png](img_yarn_scaling.png)

上图两部分对应同一件事的两个角度：

- **上图**：横轴r(d)是"这个维度在训练长度内转了多少圈"，纵轴是这个维度的转速被打了多少折。三个区域和转折点（α=1、β=32）都是DeepSeek真实用的参数，不是示意数字。标出的d=0、d=25、d=31是从DeepSeek真实的RoPE子空间（`qk_rope_head_dim=64`）里选出来的三个真实维度，按公式算出各自转了多少圈：d=0转了10430圈（深处保留区，转速不打折），d=25转了7.82圈（过渡区，转速打27%的折扣），d=31只转了1.39圈（最接近插值区，转速被压到7.4%）。
- **下图**：把"转速打折"换算成"这个维度在位置1,048,576时，感觉自己好像走到了原来的第几个位置"——d=0完全没被拉回，等效位置还是1,048,576本身（因为它压根不需要被拉回）；d=25被拉回到约28万；d=31被压缩了13.45倍，等效位置约7.8万，已经很接近训练边界6.5万了。

有个真实发现值得注意：**即便是DeepSeek这个RoPE子空间里"转得最慢"的维度（d=31），r(d)也只到1.39，还没有真正跌破α=1、完全落进"纯插值区"**——这是从真实config反推出来的结果，不是凑出来的整数，说明DeepSeek这套参数下，绝大部分维度其实都处在"部分保留、部分压缩"的过渡地带，只有极少数维度会被压到接近YaRN设定的16倍压缩上限。

这个折中在真实模型的架构设计里能看到更直接的证据：DeepSeek-V4用"hybrid local + long-range design"替代了纯粹的注意力设计，config里能看到`"sliding_window": 128`这类局部注意力配置；Kimi K3的config里则有`"linear_attn_config"`这类线性注意力层——这些都是架构师主动在"压低长上下文的硬件成本"上做的取舍，进一步印证了硬件能力在实实在在地往回压"context window能设多长"这个决策，不是训练团队想训多长就能训多长。


#### 1.1.2 硬件约束：算力和显存决定了新模型敢把原生上下文训多长

**结论先说**：你**硬件能力（算力+显存）决定了"新模型敢把原生上下文训练到多长"这个天花板；而具体训多长一旦定下来，又会反过来跟参数量、训练数据量抢占同一笔训练算力预算，进而限制这个模型最终能做到多"大"**。

也就是说，不是"上下文窗口决定模型大小"和"硬件决定上下文窗口"这两件平行的事，而是"硬件→上下文窗口选择→模型大小"这一条单向的传导链。

**先看硬件天花板到底有多硬**——回顾一下[Transformer.md 2节](../transformer/Transformer.md#2-时间维度prefill-与-decode)：context越长，KV Cache占的显存越大，prefill阶段的计算量也越大：

![img.png](img.png)

以"1M上下文 + GPT-4o规模模型"这个场景为例：光是KV Cache就要占**516GB显存**——而单张NVIDIA H200的显存只有141GB，连这一份缓存都放不下，只能靠多卡拆分/换入换出来凑，代价是一次prefill要**30分钟**；换成NVIDIA GB200 NVL72这种72卡互联、显存合计13.4TB、算力360 PFLOPS的机柜级硬件，同样的1M上下文prefill只要**1.6~3.1秒**。**同一个"1M上下文"的目标，硬件级别不同，可用性和成本差了两个数量级**——这就是"硬件能力决定新模型敢把原生上下文订多长"最直接的证据：如果你手上只有H200这个级别的硬件，把原生上下文订到1M在工程上是不现实的（不是训不出来，是慢到没法用、贵到没法商用）。

**再看这笔硬件预算，是怎么反过来挤占"模型能做多大"的**——训练阶段的attention计算量同样随context长度增长（增长速度取决于是否用了稀疏/局部注意力，朴素实现下接近平方增长），如果在整个预训练全程都用长context跑，这笔额外算力开销会实打实地挤占本可以用来堆参数量、堆训练数据的预算。回顾1.1.1，这正是DeepSeek-V4-Pro选择只原生训练到65,536、而不是直接原生训练到1M的原因——如果从头到尾都在100万长度上做预训练，攻克这笔算力需求会大幅推高整个训练成本，挤占了本可以用于扩大模型规模的预算；用"短原生训练+YaRN低成本拉伸"的方案，本质上就是在"硬件能负担的算力"和"想要更大的模型规模"之间找到的折中。

**所以完整的结论是**：Context Window的上限，是"训练时刻意选择的位置编码范围"（1.1.1）在"当下硬件能负担的算力/显存"（本节）约束下做出的一个折中选择——硬件划定了新模型能考虑的上下文范围天花板，而具体选在这个天花板下的哪个点，又会反过来跟模型规模互相争抢同一笔训练预算。这不是一个可以随便改大的软件参数，是一整条从硬件到架构设计再到训练预算分配的真实决策链。

### 1.2 为什么只能"追加写入"，不能"中间插入"——KV Cache的强约束

这一点直接由[Transformer.md 3.4节](../transformer/Transformer.md#34-transformer如何实现的kv-cache)讲过的因果掩码决定：**一个token的K、V，只取决于它自己和它前面的token**。用一个具体例子看会更清楚：

![img_context_window_append_vs_insert.png](img_context_window_append_vs_insert.png)

上图三行分别是：原始已缓存序列 → 追加到末尾会发生什么 → 插入到中间会发生什么。每个token下面标出了它的K/V实际"看到"（依赖）哪些前缀token。

**追加到末尾**（序列变成 A B C D E F，F在位置6）：A到E的K、V依赖关系一个字符都没变，之前算好缓存的K、V继续有效，只需要新算F自己的K、V——这就是能命中缓存的情况。

**插入到中间**（在B、C之间插进一个X，序列变成 A B X C D E）：C原来的K、V是基于"前面是A,B"算出来的，插入X之后，C的前缀变成了"A,B,X"（多了一个X），而且C的位置编号也从3变成了4——不管是"看到的前缀内容"还是"自己的位置索引"，两者都变了，原来缓存的K、V在数学上已经不成立，必须重算。C之后的D、E同理，位置和前缀全变，全部要重算。

**结论：插入点之后所有token的缓存全部作废，等于把这部分重新做了一遍prefill**——这也是为什么第一节Token经济学里讲的"缓存命中"（[TokenEconomics.md 3.2节](../token-economics/TokenEconomics.md#32-缓存策略设计缓存命中到底省了什么计算)），前提永远是"新内容追加在已有内容后面"，不会有模型支持"往对话历史中间插入一段内容"这种操作——不是产品设计上懒得做，是KV Cache的数学性质决定了这么做完全不划算，插入即崩缓存。
