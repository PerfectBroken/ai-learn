## 目录
- [1 Transformer-整体架构](#1-transformer-整体架构)
- [2 时间维度：Prefill 与 Decode](#2-时间维度prefill-与-decode)
- [3 单次前向流程：从Embedding到输出Token](#3-单次前向流程从embedding到输出token)
  - [3.1 Embedding](#31-embedding)
- [4 五大厂商大模型对比（2026年7月）](#4-五大厂商大模型对比2026年7月)

## 1 Transformer-整体架构
![img_transformer.png](img_transformer.png)

## 2 时间维度：Prefill 与 Decode

一次推理请求会经历两个特征完全不同的阶段：

| 维度 | Prefill（预填充） | Decode（解码）                                                                                             |
|---|---|------------------------------------------------------------------------------------------------------------|
| 处理对象 | 一次性处理完整输入context的所有token（system prompt、工具定义、历史对话、检索结果等都算在内，不只是用户单轮prompt） | 每次只生成1个新token，自回归、逐个进行                                                                     |
| 计算特征 | **计算密集型**：对整个context做大矩阵乘法（QKV投影、注意力、FFN），并行度高，GPU算力利用率高 | **存储密集型**：每步计算量很小（只算1个token），但要反复读写不断增长的KV Cache，瓶颈在显存带宽而非算力     |
| 关键产物 | 生成并缓存每个context token的K、V（即KV Cache），供后续decode复用 | 每步新增1个token的K、V追加进KV Cache；用当前token的Q查询全部历史K、V                                       |
| 延迟表现 | 首token延迟(TTFT)主要由prefill决定，**是输入context的总长度决定耗时** | 每个输出的token延迟主要由KV矩阵大小决定，输入context总长度决定KV矩阵大小，输入context越长单个token耗时越高 |

## 3 单次前向流程：从Embedding到输出Token

### 3.1 Embedding
把输入token映射成 d_model 维向量，叠加位置编码（如RoPE），得到每个token的初始表示。
映射成向量后同义词的token向量很相近，模型无需再关注所有语言的所有文字，而是只关心向量内部的具体含义。
需要注意的是，能把同义词映射为相近的向量是由与训练完成的，未经过预训练的向量函数无法完成这个功能。
![img_transformer_embedding.png](img_transformer_embedding.png)

2. **计算QKV矩阵**：用三个独立的Linear矩阵（W_Q、W_K、W_V）对每个token的embedding做投影，得到Query、Key、Value三组向量。
3. **自注意力计算**：Q与所有K做点积得到打分，除以√d_k缩放后经Softmax归一化成注意力权重，再对V做加权求和，得到每个token"融合上下文信息"后的新表示。
4. **多头机制**：把上一步拆成h个头并行计算（每个头有自己独立的W_Q/W_K/W_V子矩阵，投影到更低维子空间），让不同头分别关注不同类型的关系；h个头的输出拼接后，经一次Linear（W_O）压回d_model维——**多头到这里就已经合并完毕**。
5. **合并多头后的FFN**：合并后的向量经残差连接+LayerNorm，送入该层的FFN（两层Linear+非线性激活，先升维再降维）。FFN是position-wise的：同一层内所有token位置共享同一套FFN参数，但**不同层之间的FFN参数各自独立、不共享**——这是模型参数量与"记忆"的主要载体。
6. **多层机制**："多头注意力（含合并）+ FFN"构成一个block，重复N次。层与层之间是**串行接力**：前一层输出直接作为下一层输入，不存在"多层结果最后汇总"，每层的注意力和FFN都用各自独立参数，逐层把表示提炼得更抽象。
7. **最终Linear + Softmax**：堆叠完N层后，取最后一层的输出，经过整个模型**唯一一次**的LM head Linear，把d_model维投影到vocab_size维得到logits，再经**唯一一次**Softmax转成概率分布，最后采样/argmax选出新token。

## 4 五大厂商大模型对比（2026年7月）

对比国内 DeepSeek、智谱(GLM)、月之暗面(Kimi)，以及 OpenAI、Anthropic(Claude) 共5家的顶尖款与常用款模型。

> 这个行业价格和榜单变化非常快（几乎每周都有新模型/调价），下表是基于各家官方文档 + Artificial Analysis Intelligence Index 榜单核实的 2026年7月数据，**用之前建议去下方文档链接核对一次**，尤其是智谱的价格官网做了前端动态渲染，没能直接抓到拆分数字，用的是第三方交叉验证的估算值。

| 公司 | 档位 | 型号 | 上下文窗口 | 最大输出 | 输入价格($/百万token) | 输出价格($/百万token) | 性能评分¹ | API 文档 |
|---|---|---|---|---|---|---|---|---|
| **DeepSeek** | 顶尖款 | DeepSeek-V4-Pro | 1M | 384K | $0.435（缓存未命中）/ $0.0036（命中） | $0.87 | AA指数 44.3（V4 Pro Max档） | [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing) |
| **DeepSeek** | 常用款 | DeepSeek-V4-Flash | 1M | 384K | $0.14（未命中）/ $0.0028（命中） | $0.28 | 未单独收录，低于Pro档 | [api-docs.deepseek.com](https://api-docs.deepseek.com/quick_start/pricing) |
| **智谱 GLM** | 顶尖款 | GLM-5 | 200K | 128K | ≈$2.7（约¥20，官网未拆分，第三方估算） | ≈$3.2 | AA指数 51.1（GLM-5.2档） | [docs.bigmodel.cn](https://docs.bigmodel.cn/cn/guide/models/text/glm-5) |
| **智谱 GLM** | 常用款 | GLM-4.6 | 200K | 128K | ≈$0.7（约¥5，第三方数据，未在官网核实拆分） | 官网未拆分 | 略低于GLM-5，具体分未查到 | [docs.bigmodel.cn](https://docs.bigmodel.cn/cn/guide/models/text/glm-4.6) |
| **月之暗面 Kimi** | 顶尖款 | Kimi K3 | 1M（1,048,576） | 262K | $3.00（缓存未命中）/ $0.30（命中） | $15.00 | AA指数 57（对标 Opus 4.8 / GPT-5.5） | [platform.kimi.ai](https://platform.kimi.ai/docs/pricing/chat-v1) |
| **月之暗面 Kimi** | 常用款 | Kimi K2.6 | 262K | 262K | $0.95（未命中）/ $0.16（命中） | $4.00 | AA指数 44 | [platform.kimi.ai](https://platform.kimi.ai/docs/pricing/chat-v1) |
| **OpenAI** | 顶尖款 | GPT-5.6 Sol | 1M | — | $5.00 | $30.00 | AA指数 58.9 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) |
| **OpenAI** | 常用款 | GPT-5.6 Luna（或更常见的 GPT-5-mini） | 1M / ~400K | — | $1.00 / $0.25 | $6.00 / $2.00 | 未单独查到，低于Sol档 | [developers.openai.com](https://developers.openai.com/api/docs/pricing) |
| **Anthropic Claude** | 顶尖款 | Claude Opus 4.8 | 1M | 128K | $5.00 | $25.00 | 官方未发布单一跑分；同系 Fable 5（更贵档）AA指数59.9 | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/models/overview) |
| **Anthropic Claude** | 常用款 | Claude Sonnet 5 | 1M | 128K | $3.00（活动价$2，至2026-08-31） | $15.00（活动价$10） | 定位"近Opus质量，Sonnet成本" | [platform.claude.com](https://platform.claude.com/docs/en/about-claude/models/overview) |

¹ 性能评分统一采用 [Artificial Analysis Intelligence Index](https://artificialanalysis.ai)（综合推理/代码/知识类基准的加权指数，数值越高越强），是目前少数能跨厂商横向对比的第三方榜单之一，但**它不是唯一标准**——不同基准（LMArena Chat/Code Arena、SWE-bench、MMLU等）排名会有出入，具体到"哪个模型适合你的场景"建议结合具体任务实测。部分档位（如DeepSeek-V4-Flash、GLM-4.6、GPT-5.6 Luna、Claude Opus 4.8）没有查到该榜单的独立公开评分，已如实标注，不是漏填。

