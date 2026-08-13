## 目录
- [1 Claude / OpenAI / Kimi 官方提示词文档对比](#1-claude--openai--kimi-官方提示词文档对比)
  - [1.1 共同点（三家完全一致，业内共识）](#11-共同点三家完全一致业内共识)
  - [1.2 不同点：具体到怎么写prompt](#12-不同点具体到怎么写prompt)

## 1 Claude / OpenAI / Kimi 官方提示词文档对比

> 对比对象：[Anthropic_ClaudePromptingBestPractices_Notes.md](Anthropic_ClaudePromptingBestPractices_Notes.md)、[OpenAI_PromptEngineering_Overview_Notes.md](OpenAI_PromptEngineering_Overview_Notes.md)、[Moonshot_KimiPromptBestPractice_Notes.md](Moonshot_KimiPromptBestPractice_Notes.md)

结论先行：三篇文档在"怎么写好一次prompt"的核心方法论上高度重合、几乎没有分歧；真正的差异在于**覆盖的广度和面向的读者深度**——Claude这篇是围着单一厂商多代模型写的深度调校手册,面向已经在做复杂agent产品的开发者；OpenAI这篇是跨模型的通用工程方法论,偏"怎么把prompt工程落地到代码和成本管理里"；Kimi这篇最精简,面向刚上手API的开发者,只讲最基础的静态文本生成场景。

### 1.1 共同点（三家完全一致，业内共识）

- **清晰具体的指令是第一原则**：三家都强调"模型读不懂你的言外之意",越具体的指令效果越好
- **示例（few-shot）优于穷举式规则**：给几个多样化的输入输出示例,比试图写全所有规则或指望模型自己脑补更有效
- **用分隔符/XML/Markdown给prompt分区**：三家都建议用标签或标题把指令、背景、示例、任务分开,避免模型混淆
- **给模型设定角色/身份**：在system prompt里说清楚"你是谁",能让输出更聚焦
- **补充背景信息能提升相关性**：本质都是RAG思路——给模型它训练数据之外的信息,回答会更贴近场景
- **复杂任务要拆解**：三家都建议把大任务拆成小步骤或子任务,而不是指望模型一口气搞定
- **没有一招鲜,必须靠评估反复迭代**：三家都明确说这是实证学科,指南只是起点

### 1.2 不同点：具体到怎么写prompt

| 维度 | Claude（Anthropic） | OpenAI                                                                                                                                                                                                                                                        | Kimi（Moonshot） |
|---|---|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| **思考/推理怎么触发、prompt怎么写** | 用**自适应思考**机制（`thinking: {type: "adaptive"}`），模型自己根据`effort`参数+query复杂度决定要不要想、想多少，**不需要**在prompt里手写"请一步步思考"。想减少触发频率就写："Thinking adds latency and should only be used when it will meaningfully improve answer quality...When in doubt, respond directly."思考关闭时的兜底方案：用`<thinking>`和`<answer>`标签把推理过程和最终答案分开。 | **Prompt Engineering Overview**这篇是在选模型阶段就分流——"推理模型"和"GPT模型"是两类不同模型，选了推理模型后prompt只需给高层目标（"像对待资深同事"），选了GPT模型才需要把逻辑步骤明确写出来（"像对待初级同事"），本篇没给具体CoT模板。<br><br>具体的手写CoT技巧在**GPT-4.1 Prompting Guide**里：GPT-4.1不是推理模型，靠prompt显式引导"逐步思考"。基础版本是在prompt末尾加一句`"First, think carefully step by step about what documents are needed to answer the query. Then, print out the TITLE and ID of each document. Then, format the IDs into a list."`，再通过审查失败案例迭代改进；更完整的版本会显式定义一套"推理策略"（Reasoning Strategy），拆成"查询分析→上下文分析（含relevance rating分级）→综合"三步，把检索式推理的每一步都变成可审计的显式步骤。原文实测：引入显式规划能让SWE-bench Verified通过率提升4%。 | **完全没涉及这个维度**——通篇没有"思考""推理""思维链"相关的内容。 |
| **Agent自主性/持续性怎么写** | 双向都有具体模板：想让它更主动，用`<default_to_action>`包裹"By default, implement changes rather than only suggesting them...";想让它执行危险操作前先确认，用列出具体风险动作清单的模板（删文件、force push、改共享基础设施要确认）。 | 给了明确的**persistence**提示语模板："you are an agent - please keep going until the user's query is completely resolved...Do not stop after completing only part of the request."还配了一句要求"调用工具前先解释为什么"的**前言（preamble）**指令。          | **完全没涉及**——文档里没有"agent""自主执行""工具调用触发"这类内容。 |
| **给示例（few-shot）的具体格式** | 用`<example>`包一个示例，多个示例外层再套`<examples>`，官方给的经验数字是**3–5个**最佳。 | 在system消息的`# Examples`小节里，用自定义XML标签+`id`属性，比如`<user_query id="example-1">`配`<assistant_response id="example-1">`成对出现。                                                                                                                | 只说了"给一般性指导示例比穷举所有排列更高效"这个原则（few-shot优于zero-shot），**没有给出具体该用什么标签/格式来包裹示例**。 |
| **角色设定（身份）怎么写、写在哪** | System prompt里**一句话**即可见效，例句就是`"You are a helpful coding assistant specializing in Python."`，直接放在API的`system`字段。 | 在developer消息里专门开一个`# Identity`小节，要求写清楚assistant的**目的、沟通风格、高层次目标**，比Claude的"一句话"更强调结构化独立成段。                                                                                                                    | 说"在`messages`字段里加入角色设定"，**没有具体规定该写在哪个字段的哪个位置、要不要单独分节**，处理得比另外两家粗略。 |
| **控制输出长度/格式怎么写** | 强调"说该做什么、别说不该做什么"——比如不说"不要用markdown"，改说"用流畅的散文段落";还可以用自定义XML标签当格式指示符，比如把散文部分要求写进`<smoothly_flowing_prose_paragraphs>`标签里。 | 两篇OpenAI文档（Overview和GPT-4.1 Prompting Guide）**确实都没有**给出类似Kimi那种"精确字数不可靠、段落数/条目数更可控"的具体判断——GPT-4.1那篇"通用建议"章节里只有"Prompt结构模板"和"分隔符选择（Markdown/XML/JSON该怎么选）"，讲的是怎么组织prompt的输入结构，不是怎么控制输出的长度。这个维度目前只有Kimi给出了具体结论，如实标为空白，不强行对应。 | 给了一条很具体的经验提醒：**要求精确字数（比如"写800字"）模型做不准，但要求特定的段落数或项目符号数（"分3段"、"列5条"）模型能可靠地做到**——这是三家里唯一给出这种"哪种量化方式更可控"的具体判断。 |
| **长对话/上下文管理怎么写** | 讲得最细：给了完整的"你的上下文会被自动压缩，别因为担心token预算而提前收尾"这类prompt模板；多窗口工作流还给了具体指令示例，比如"先调用pwd""复查progress.txt和git日志"。 | 只讲"上下文窗口大小是多少token"这个容量规划层面，**没有给任何该怎么写prompt去管理长对话的具体模板**。                                                                                                                                                         | 提到"总结长对话"维持连贯性，但**没给具体的prompt写法**；反而在长文档场景给了一个具体算法——递归分块：先对每小节做局部摘要，再递归合并摘要，这是一个操作流程而不是prompt模板。 |
| **工具调用触发的具体写法** | 给了明确的对比范例：泛泛地说"Can you suggest some changes"模型只会给建议不动手；改成"Change this function to improve its performance"模型才会真的去改。还有`<default_to_action>`模板用来整体调高主动触发工具的倾向。 | **Prompt Engineering Overview**这篇没有专门讲这个维度。<br><br>具体写法在**GPT-4.1 Prompting Guide**的system prompt三件套提醒之一——**工具调用提醒**：要求模型遇到不确定信息时必须去用工具查证，不能瞎猜：`"If you are not sure about file content or codebase structure pertaining to the user's request, use your tools to read files and gather the relevant information: do NOT guess or make up an answer."`原文实测：这三条提醒合计能让SWE-bench Verified得分提升近20%。该文档还建议**一定要用API的`tools`字段传工具**，不要手动把工具描述塞进prompt文本里自己写解析器——这样能让模型在工具调用轨迹上保持"分布内"，实测比手动注入提升2%的通过率。 | **完全没涉及**——文档里没有工具调用相关的内容。 |

**规律**：Kimi这篇文档的"没提到"不是遗漏细节，而是整个维度都是空白（思考推理、agent自主性、工具调用触发这三块完全没写）——它的定位更接近"怎么写好一段静态文本生成的prompt"，而Claude和OpenAI两家已经把agent场景（工具、自主性、长任务）当成核心内容在讲了。这个覆盖范围的差异，本身就是三篇文档风格差异里最大的一条。

https://www.promptingguide.ai/techniques/consistency