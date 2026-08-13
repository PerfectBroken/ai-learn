> 原文：[GPT-4.1 Prompting Guide](https://cookbook.openai.com/examples/gpt4-1_prompting_guide) — OpenAI Cookbook
>
> 逐节笔记，按原文小标题顺序走。示例prompt保留英文原文（功能性文本，翻译会破坏用途）。原文附录里有一份几百行的`apply_patch.py`参考实现代码——纯代码，没有需要翻译的教学内容，笔记里只记它解决的问题和格式设计思路，完整代码建议需要时直接去[原文](https://cookbook.openai.com/examples/gpt4-1_prompting_guide)或[GitHub源文件](https://github.com/openai/openai-cookbook/blob/main/examples/gpt4-1_prompting_guide.ipynb)拿。

## 这篇文档的定位

GPT-4.1相比GPT-4o在编程、指令遵循、长上下文这几方面有明显提升，这篇指南收集了OpenAI内部大量测试后得出的prompt技巧。核心论点和Anthropic那篇《Claude prompting best practices》其实是同一个方向：**GPT-4.1比前代模型更严格地按字面意思执行指令，不太会主动脑补用户意图**——所以想要模型"超预期"发挥，得直接说出来，不能指望它自己猜；但反过来，这也让模型变得高度可控：只要一句话把期望行为讲清楚，几乎总能把模型拉回正轨。原文强调AI工程本质上是一门实证学科，建议配合评估体系反复迭代，不要指望"一招鲜"。

## 一、Agentic工作流

原文提到，得益于训练时覆盖了多样化的agent问题求解轨迹，GPT-4.1配合OpenAI自己的agent harness在SWE-bench Verified上达到了非推理模型的最优水平（55%的问题被解决）。

### System prompt里的三个提醒

要充分发挥GPT-4.1的agent能力，原文建议在所有agent prompt里包含三类关键提醒（针对agentic编程场景优化，但可以套用到通用agent场景）：

1. **持续性（Persistence）**：让模型明白自己正进入一个多消息轮次，防止它过早把控制权交还给用户。示例：
   ```
   You are an agent - please keep going until the user's query is
   completely resolved, before ending your turn and yielding back
   to the user. Only terminate your turn when you are sure that
   the problem is solved.
   ```
2. **工具调用（Tool-calling）**：鼓励模型充分利用工具，降低它凭空猜答案的概率。示例：
   ```
   If you are not sure about file content or codebase structure
   pertaining to the user's request, use your tools to read files
   and gather the relevant information: do NOT guess or make up
   an answer.
   ```
3. **规划（Planning，可选）**：让模型在每次工具调用之间显式做文字规划和反思，而不是只靠一连串工具调用完成任务。示例：
   ```
   You MUST plan extensively before each function call, and
   reflect extensively on the outcomes of the previous function
   calls. DO NOT do this entire process by making function calls
   only, as this can impair your ability to solve the problem and
   think insightfully.
   ```

原文给出的实测数据：这三条提醒让内部SWE-bench Verified得分**提升了近20%**。整体效果是把模型从"像聊天机器人一样等指令"的状态，转变为一个更"主动进取"的agent，自主推进交互进程。

### 工具调用的实现方式

相比前代模型，GPT-4.1在"如何有效使用通过API的`tools`字段传入的工具"这件事上训练得更充分。原文明确建议：**一定要用API的`tools`字段传工具，不要手动把工具描述塞进prompt文本里再自己写解析器**——这是最大程度减少错误、让模型在工具调用轨迹上保持"分布内"（in distribution）的最佳方式。原文给出的实测数据：用API解析的工具描述比手动注入schema到system prompt，SWE-bench Verified的通过率**提升了2%**。

工具命名要清楚地表明用途，`description`字段要写清楚详细的说明；每个参数也要靠好的命名和描述来确保被正确使用。如果工具比较复杂想给使用示例，建议在system prompt里单独开一个`# Examples`小节放示例，而不是塞进`description`字段（`description`应该保持详尽但相对简洁）。

### Prompt引导的规划与思维链

GPT-4.1不是推理模型（不会在回答前生成内部思维链），但开发者可以通过前面提到的"规划"prompt组件，引导模型在回答中生成显式的、分步骤的计划——相当于让模型"把想法说出来"。原文的SWE-bench Verified实验里，引入显式规划让通过率提升了**4%**。

### 示例：SWE-bench Verified的完整agent prompt

原文给出了一份实际用来拿到SWE-bench Verified最高分的完整agent system prompt（篇幅较长，核心是一套"高层问题解决策略"的8步流程：深入理解问题 → 探查代码库 → 制定详细计划 → 增量式实现修复 → 按需调试 → 频繁测试 → 迭代直到根因修复且全部测试通过 → 全面反思与验证），配合一个自定义的`apply_patch`工具（用于对文件执行diff/patch，具体格式见下文"附录"部分）。这套模式可以套用到任何agentic任务上，完整prompt文本较长，建议需要时直接看[原文](https://cookbook.openai.com/examples/gpt4-1_prompting_guide)。

## 二、长上下文

GPT-4.1支持**100万token**的输入上下文窗口，适合结构化文档解析、重排序、在有大量无关内容干扰下挑出相关信息、基于上下文做多跳推理等长上下文任务。

**最佳上下文规模**：在"大海捞针"（needle-in-a-haystack）评测上，GPT-4.1在整个100万token的窗口内都表现良好；在混合了相关和不相关代码/文档的复杂任务上也表现出色。但如果任务需要检索的条目越来越多，或者需要对整个上下文的状态做复杂推理（比如图搜索这类），长上下文性能会有所下降。

**调节对上下文的依赖程度**：需要考虑任务是该依赖模型自身的世界知识，还是只依赖提供的上下文去回答。原文给了两种典型prompt写法：

```
// 只用内部知识
- Only use the documents in the provided External Context to
answer the User Query. If you don't know the answer based on
this context, you must respond "I don't have the information
needed to answer that", even if a user insists on you answering
the question.

// 内部+外部知识都用
- By default, use the provided external context to answer the
User Query, but if other basic knowledge is needed to answer,
and you're confident in the answer, you can use some of your own
knowledge to help answer the question.
```

**Prompt内容的排布顺序**：长上下文场景下，指令和上下文的摆放位置会明显影响效果。理想情况下应该把指令**同时放在提供的上下文前面和后面**——这比只放在上面或只放在下面效果更好。如果只想放一次，那放在上下文**前面**比放在后面效果更好。（这一点和Claude那篇里"长文本放最上面、query放最后"的建议看起来有出入，属于两家模型各自实测出的经验结论，不是同一套规则。）

## 三、思维链（Chain of Thought）

GPT-4.1不是推理模型，但引导它"逐步思考"（即思维链，CoT）依然能有效帮它把问题拆成更容易管理的小块、逐一解决、提升整体输出质量，代价是更高的输出token带来的成本和延迟。模型本身已经训练得擅长agentic推理和真实世界问题求解，所以通常不需要太复杂的提示就能表现良好。

原文建议先从这样一句基础的思维链指令开始，放在prompt末尾：

```
First, think carefully step by step about what documents are
needed to answer the query. Then, print out the TITLE and ID of
each document. Then, format the IDs into a list.
```

在此基础上，应该通过审查自己实际案例和评估里的失败样本来改进CoT prompt，针对系统性的规划和推理错误加更明确的指令。原文指出错误通常来自三类原因：误解用户意图、收集/分析的上下文不充分、分步思考不充分或有误——针对这些问题用更明确、更有倾向性的指令去应对。

原文还给了一个更完整的示例，要求模型先做"查询分析"（拆解澄清query在问什么）、再做"上下文分析"（对每份候选文档做相关性分析和分级：high/medium/low/none，且优化召回率而非精确率——宁可多召回不相关的，也不能漏掉真正相关的），最后做"综合"（总结medium及以上相关度的文档）——这种"先分析、按等级筛选、再综合"的三段式结构，本质上是把"怎么做检索式推理"这件事从模型的隐式行为变成了显式可审计的步骤。

## 四、指令遵循

GPT-4.1的指令遵循表现出色，开发者可以借此精确地塑造和控制针对特定场景的输出。但正因为模型更字面化地遵循指令，开发者可能需要显式地写清楚"该做什么/不该做什么"；针对其他模型调校过的旧prompt未必能直接套用到GPT-4.1上，因为现在指令会被更严格地执行，之前那些隐含规则不再会被model强力推断出来。

### 推荐的开发/调试流程

1. 先写一个总的"Response Rules"或"Instructions"小节，用要点列出高层次的指导原则
2. 想改某个更具体的行为时，专门加一个小节写细节（比如`# Sample Phrases`）
3. 如果有希望模型遵循的具体步骤，用有序列表列出来，并要求模型照做
4. 如果行为还是不符合预期：
   - 检查是否存在冲突、描述不足或错误的指令/示例——如果指令有冲突，GPT-4.1倾向于遵循**prompt末尾更靠后**的那条
   - 补充能演示期望行为的示例，并确保示例里演示的重要行为在规则里也有对应说明
   - 通常不需要用全大写或"贿赂/小费"这类激励话术；建议先不用这些，只在确实必要时才用——如果旧prompt已经带了这类技巧，可能会导致GPT-4.1对它过度敏感

### 常见失败模式

原文提到这些失败模式不是GPT-4.1独有，但值得记录以便排查：

- 要求模型"必须"执行某个特定行为，有时会带来副作用——比如说"你必须先调用工具再回复用户"，模型在信息不足时可能会编造工具输入参数，或者传空值硬调工具；加一句"如果信息不足以调用工具，向用户询问所需信息"能缓解这个问题
- 给了固定的话术示例（sample phrases）后，模型可能会逐字重复使用这些话术，对用户来说显得很机械重复；需要明确要求模型按需变换措辞
- 没有具体指令时，模型可能倾向于额外解释自己的决策，或者输出比期望更多的格式化内容；需要给出指令甚至示例来缓解

### 示例：客服agent

原文给了一个完整的虚构客服agent system prompt，用来演示上述最佳实践——规则的多样性、具体程度、用额外小节展开细节、以及一个融合了所有前述规则的完整示例。核心结构是：固定的问候语开场 → 涉及事实性问题（公司、产品、账户）前必须先调用工具查证，不能凭自己的知识回答，信息不足时要反问用户 → 用户要求时升级转人工 → 明确列出的禁止话题（政治、宗教、有争议时事、医疗/法律/财务建议、私人对话、公司内部运营、对他人或公司的批评）→ 适当使用但不能在同一对话里重复的固定话术 → 每次回复都要遵循的输出格式（涉及事实性陈述必须附引用，格式为`[NAME](ID)`）→ 附一个完整的示例对话演示前述所有规则如何配合工作。完整prompt文本和配套的工具定义代码，建议直接看[原文](https://cookbook.openai.com/examples/gpt4-1_prompting_guide)。

## 五、通用建议

### Prompt结构

原文给了一个可以作为起点的prompt结构模板：

```
# Role and Objective

# Instructions

## Sub-categories for more detailed instructions

# Reasoning Steps

# Output Format

# Examples
## Example 1

# Context

# Final instructions and prompt to think step by step
```

按需增减小节，通过实验找到最适合自己场景的结构。

### 分隔符（Delimiters）选择

原文对几种常见分隔符给出了对比结论：

1. **Markdown**：建议作为起点——用markdown标题划分主要章节和子章节（支持到H4级以上的更深层级），用行内反引号或代码块精确包裹代码，用标准的有序/无序列表列举条目。
2. **XML**：表现也很好，GPT-4.1对XML内信息的遵循度有提升——XML方便精确地包裹一段内容（有明确的起止边界）、给标签加元数据、支持嵌套。原文示例是用XML把示例嵌套进`<examples>`小节，每个示例带`<input>`和`<output>`。
3. **JSON**：结构化程度高，模型（尤其在编程场景）理解得很好，但相对冗长，且需要处理字符转义带来的额外开销。

对于"往输入上下文里塞大量文档/文件"这类场景，原文给了三种格式各自的实测表现：
- **XML**表现好，比如`<doc id='1' title='The Fox'>The quick brown fox jumps over the lazy dog</doc>`
- Lee等人提出的一种**ID+标签**格式（[论文链接](https://arxiv.org/pdf/2406.13121)）表现同样好，比如`ID: 1 | TITLE: The Fox | CONTENT: The quick brown fox jumps over the lazy dog`
- **JSON表现明显较差**

模型对多种格式的结构理解都很稳健，原文建议凭判断选择"最能让信息清晰突出"的格式——比如如果你检索到的文档本身就包含大量XML内容，那再用XML做分隔符效果就会打折扣，因为分隔符和内容本身混在一起不再"突出"。

### 注意事项（Caveats）

- 在少数场景下观察到模型不太愿意生成非常长、重复性强的输出（比如逐条分析几百个条目）。如果你的场景确实需要这样，要用很强的措辞要求模型完整输出，也可以考虑拆分任务或换更简洁的方案。
- 观察到极少数并行工具调用出错的情况。建议自己测试一下，如果遇到问题，可以考虑把[`parallel_tool_calls`](https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls)参数设为`false`。

## 六、附录：生成与应用文件diff

开发者反馈"生成准确、格式良好的diff"是驱动编程类agent任务的关键能力。GPT-4.1家族在diff生成能力上相比前代GPT模型有大幅提升。虽然只要给清晰的指令和示例，GPT-4.1能生成任意格式的diff，但原文开源了一种经过大量训练验证的推荐diff格式，尤其方便刚上手的开发者省去自己设计diff格式的摸索过程。

### 核心设计：V4A diff格式

这个格式的关键特点是**不依赖行号**，而是靠上下文（默认改动前后各3行）来唯一定位要修改的代码位置：

```
*** Begin Patch
*** Update File: path/to/file
@@ class BaseClass
@@     def search():
-        pass
+        raise NotImplementedError()
*** End Patch
```

- 每处改动前后默认展示3行上下文；如果改动之间距离很近（3行以内），后一处改动的前置上下文不需要和前一处的后置上下文重复
- 如果3行上下文不足以在文件内唯一定位这段代码，用`@@`操作符标出这段代码所属的类或函数名
- 如果同一个类/函数内这段代码重复出现次数太多，连一个`@@`加3行上下文都无法唯一定位，可以用多个`@@`语句逐层跳转到正确位置（比如先`@@ class BaseClass`再`@@ def method():`）

原文附了一个自定义的`apply_patch`工具定义（`type: function`，接收一个`input`字符串参数，内容就是上面这种patch文本），以及一份**完整的Python参考实现**（`apply_patch.py`，负责解析这种patch文本格式并实际应用到文件上，包含patch解析器、上下文匹配、模糊匹配容错等逻辑）——这份代码本身没有教学性的散文内容，纯粹是给开发者拿来直接用的工具实现，完整代码见[原文](https://cookbook.openai.com/examples/gpt4-1_prompting_guide)或[GitHub源文件](https://github.com/openai/openai-cookbook/blob/main/examples/gpt4-1_prompting_guide.ipynb)。

### 其他有效的diff格式

原文提到，如果想尝试其他diff格式，实测中Aider多语言基准测试用的**SEARCH/REPLACE**格式，以及一种不带内部转义的**伪XML**格式，成功率都很高。这两种格式共享两个关键特点：**不使用行号**，并且**同时给出要被替换的精确代码和替换后的精确代码**，两者之间有清晰的分隔符。

---

**小结**（金字塔顶层）：这篇指南和Anthropic那篇的核心主张高度一致——**GPT-4.1比前代更字面化地执行指令，需要开发者把隐含期待显式写出来**；在这个共同前提之上，GPT-4.1这篇更侧重三块具体的工程实践：agent prompt里"持续性/工具调用/规划"三件套提醒能带来实测20%的分数提升、长上下文里指令要"首尾各放一次"、以及一套不依赖行号、专门为降低diff生成出错率设计的V4A格式。
