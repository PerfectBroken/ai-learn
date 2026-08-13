> 原文：[Prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices) — Claude Platform Docs
>
> 这是逐节笔记（按原文小标题顺序走，不跳节），不是逐句机翻。示例prompt保留英文原文，因为它们是要直接复制进system prompt里用的功能性文本，翻译成中文反而破坏了用途。原文里每个"角色设定"示例都附了bash/Python/TypeScript/C#/Go/Java/PHP/Ruby八种语言的等价SDK调用代码——这八份代码除了语言语法不同，逻辑完全一样（都是把同一句系统提示词塞进`system`字段），笔记里只保留Python和curl两个代表，其余语言需要时去原文抄。

## 目录
- [这篇文档的定位](#这篇文档的定位)
- [一、各模型专属指南（只列结构，不展开）](#一各模型专属指南只列结构不展开)
- [二、通用原则（General principles）](#二通用原则general-principles)
  - [1. 清晰直接（Be clear and direct）](#1-清晰直接be-clear-and-direct)
  - [2. 补充背景信息来提升效果（Add context to improve performance）](#2-补充背景信息来提升效果add-context-to-improve-performance)
  - [3. 有效使用示例（Use examples effectively）](#3-有效使用示例use-examples-effectively)
  - [4. 用XML标签组织prompt结构（Structure prompts with XML tags）](#4-用xml标签组织prompt结构structure-prompts-with-xml-tags)
  - [5. 给Claude设定角色（Give Claude a role）](#5-给claude设定角色give-claude-a-role)
  - [6. 长上下文提示词（Long context prompting）](#6-长上下文提示词long-context-prompting)
  - [7. 模型自我认知（Model self-knowledge）](#7-模型自我认知model-self-knowledge)
- [三、输出与格式（Output and formatting）](#三输出与格式output-and-formatting)
  - [1. 沟通风格与详略程度](#1-沟通风格与详略程度)
  - [2. 控制回复的格式](#2-控制回复的格式)
  - [3. LaTeX输出](#3-latex输出)
  - [4. 文档创建](#4-文档创建)
  - [5. 从"预填回复"（prefill）迁移出来](#5-从预填回复prefill迁移出来)
- [四、工具使用（Tool use）](#四工具使用tool-use)
  - [1. 工具触发](#1-工具触发)
  - [2. 优化并行工具调用](#2-优化并行工具调用)
- [五、思考与推理（Thinking and reasoning）](#五思考与推理thinking-and-reasoning)
  - [1. 过度思考与过度周全](#1-过度思考与过度周全)
  - [2. 善用思考与交错思考能力](#2-善用思考与交错思考能力)
- [六、Agent系统（Agentic systems）](#六agent系统agentic-systems)
  - [1. 长跨度推理与状态跟踪](#1-长跨度推理与状态跟踪)
  - [2. 平衡自主性与安全性](#2-平衡自主性与安全性)
  - [3. 研究与信息收集](#3-研究与信息收集)
  - [4. 子agent编排](#4-子agent编排)
  - [5. 串联复杂prompt](#5-串联复杂prompt)
  - [6. 减少agent编程场景下的文件创建](#6-减少agent编程场景下的文件创建)
  - [7. 过度热心（Overeagerness）](#7-过度热心overeagerness)
  - [8. 避免只顾"过测试"和硬编码](#8-避免只顾过测试和硬编码)
  - [9. 减少agent编程中的幻觉](#9-减少agent编程中的幻觉)
- [七、能力专项小贴士（Capability-specific tips）](#七能力专项小贴士capability-specific-tips)
  - [1. 视觉能力提升](#1-视觉能力提升)
  - [2. 前端设计](#2-前端设计)
- [八、迁移注意事项（Migration considerations）](#八迁移注意事项migration-considerations)

## 这篇文档的定位

这是Anthropic官方提示词工程的**技巧总仓库**，覆盖Claude Fable 5 / Mythos 5 / Opus 5 / Opus 4.8 / Opus 4.7 / Opus 4.6 / Sonnet 5 / Sonnet 4.6 / Haiku 4.5这些当前在售模型。全文分三大块：

1. **各模型专属指南**（Fable 5、Sonnet 5、Opus 5、Opus 4.8 各有独立子页面，讲每一代模型行为上的差异和该怎么调整prompt）
2. **对所有当前模型通用的技巧**（本篇笔记的重点——通用原则、输出格式、工具使用、思考能力、agent系统）
3. **迁移注意事项**（从旧一代模型的prompt迁移过来要注意什么）

## 一、各模型专属指南（只列结构，不展开）

原文这四个小节（Claude Fable 5 / Claude Sonnet 5 / Prompting Claude Opus 5 / Prompting Claude Opus 4.8）本身都只有一段话，指向各自独立的详细子页面，并没有把具体内容铺在这篇总览里。笔记只记它们各自关注的差异维度，不做原文展开：

| 模型 | 子页面关注的差异点 |
|---|---|
| Claude Fable 5 / Mythos 5 | 相对Opus 4.8的行为差异；effort等级、指令遵循方式、长时间运行任务里的"进度声明"、记忆系统、以及一个叫`reasoning_extraction`的拒答类别 |
| Claude Sonnet 5 | 相对Sonnet 4.6的差异；回复长度、effort/思考深度的校准、工具触发时机、字面化的指令遵循、设计与前端默认行为 |
| Claude Opus 5 | 相对之前Opus模型的差异；回复长度与冗余度、给用户看的进度更新、书面交付物长度、任务范围与"过度自我验证"、子agent的控制、自我纠错行为 |
| Claude Opus 4.8 | 回复长度、effort/思考深度校准、工具触发时机、字面化指令遵循、子agent控制、设计与前端默认行为 |

如果你后续针对某个具体模型深入使用，可以单独让我再去查对应子页面。这里先只记概览。

## 二、通用原则（General principles）

这一节说的技巧对包括Fable 5 / Mythos 5在内的所有当前模型都适用。

### 1. 清晰直接（Be clear and direct）

核心论点：**Claude会严格按你写的字面意思执行，不会主动"脑补"你没说出口的期待**。如果你想要"超出预期"的效果，必须明确说出来，不能指望模型自己去猜你的言外之意。

原文给了一个很实用的检验标准，翻译过来大意是：**"金标准"——把你的prompt拿给一个对这项任务几乎没背景的同事看，让他照着执行；如果他会被搞糊涂，Claude大概率也会。**

具体建议：
- 明确说清楚你想要的输出格式和约束条件
- 如果步骤的顺序或完整性很重要，用编号列表或项目符号把步骤按顺序列出来

原文给的对比例子（仪表盘生成任务）：

```
效果较差：Create an analytics dashboard

效果更好：Create an analytics dashboard. Include as many relevant
features and interactions as possible. Go beyond the basics to
create a fully-featured implementation.
```

### 2. 补充背景信息来提升效果（Add context to improve performance）

论点：**告诉Claude"为什么"要这样做，比只给"要怎么做"的硬性规则效果更好**——Claude有能力从背景动机里泛化出恰当的行为，不需要你把每种情况都穷举成规则。

原文的对比例子（格式偏好）：

```
效果较差：NEVER use ellipses

效果更好：Your response will be read aloud by a text-to-speech
engine, so never use ellipses since the text-to-speech engine
will not know how to pronounce them.
```

后一种写法多了一句"为什么"（这段文字会被语音引擎朗读，省略号读不出来），Claude就能自己举一反三，理解到"凡是不利于朗读的符号都要避免"，而不是死记"不许用省略号"这一条孤立规则。

### 3. 有效使用示例（Use examples effectively）

论点：**示例（few-shot / multishot prompting）是引导Claude输出格式、语气、结构最可靠的手段之一**。少量但精心设计的示例能显著提升准确性和一致性。

给示例时要满足三个要求：
- **相关（Relevant）**：尽量贴近你真实的使用场景
- **多样（Diverse）**：覆盖边界情况，且要有足够的变化，避免Claude从示例里学到你不想要的"意外规律"
- **结构化（Structured）**：用`<example>`标签把每个示例包起来（多个示例再用`<examples>`包一层），让Claude能明确分清"这是示例"还是"这是指令"

原文给的经验数字：**3–5个示例效果最好**。另外可以直接让Claude帮你评估现有示例的相关性和多样性，或者让它基于已有示例再生成一些新的。

### 4. 用XML标签组织prompt结构（Structure prompts with XML tags）

论点：当一个prompt里混杂了指令、背景、示例、变量输入等多种内容时，**XML标签能帮Claude无歧义地区分它们**。把每类内容包在自己的标签里（比如`<instructions>`、`<context>`、`<input>`），能显著降低误解的概率。

最佳实践：
- 标签命名要**一致、有描述性**，整篇prompt里统一用法
- 内容有天然层级关系时可以**嵌套标签**（比如多个`<document>`都放在外层的`<documents>`里，每个`<document>`还可以带`index`属性）

### 5. 给Claude设定角色（Give Claude a role）

论点：在system prompt里设定一个角色，能**聚焦Claude在这个场景下的行为和语气**——哪怕只有一句话也有明显效果。

原文给的例子是把system设为：

```
You are a helpful coding assistant specializing in Python.
```

然后user提问"How do I sort a list of dictionaries by key?"。原文附了bash/CLI/Python/TypeScript/C#/Go/Java/PHP/Ruby九种语言的等价API调用示例，逻辑完全相同，只列Python代表：

```python
client = anthropic.Anthropic()

message = client.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    system="You are a helpful coding assistant specializing in Python.",
    messages=[
        {"role": "user", "content": "How do I sort a list of dictionaries by key?"}
    ],
)

print(message.content)
```

### 6. 长上下文提示词（Long context prompting）

处理大文档或数据密集型输入（2万token以上）时，prompt的结构安排会明显影响效果：

- **把长文本放在prompt最上面**：文档和输入内容放在query、指令、示例之前（也就是最靠前的位置）。原文引用了一个测试数据：**query放在最后，在复杂的多文档输入场景下能让回答质量提升最多30%**。
- **用XML标签给文档内容和元数据分层**：多文档场景下，每个文档用`<document>`包起来，内部再用`<document_content>`、`<source>`等子标签标注来源等元数据。原文给的示例结构：

```xml
<documents>
  <document index="1">
    <source>annual_report_2023.pdf</source>
    <document_content>{{ANNUAL_REPORT}}</document_content>
  </document>
  <document index="2">
    <source>competitor_analysis_q2.xlsx</source>
    <document_content>{{COMPETITOR_ANALYSIS}}</document_content>
  </document>
</documents>

Analyze the annual report and competitor analysis. Identify
strategic advantages and recommend Q3 focus areas.
```

- **让Claude先引用原文再回答**：处理长文档任务时，先让Claude把相关段落摘引出来，再执行任务。这样能帮它聚焦相关内容、忽略无关部分。原文举了一个"AI医生助理"的例子：先让模型把病历和问诊记录中和症状相关的句子摘进`<quotes>`标签，再基于这些摘引在`<info>`标签里列出诊断相关信息——这个"先摘引再推理"的模式本质上是逼模型做一次"检索定位"，再做"基于定位内容的推理"，减少它凭印象作答的空间。

### 7. 模型自我认知（Model self-knowledge）

如果你希望Claude在应用里能正确报出自己的身份，或者用到具体的API字符串，原文给的两个模板句：

```
The assistant is Claude, created by Anthropic. The current
model is Claude Opus 5.
```

```
When an LLM is needed, please default to Claude Opus 5 unless
the user requests otherwise. The exact model string for Claude
Opus 5 is claude-opus-5.
```

## 三、输出与格式（Output and formatting）

### 1. 沟通风格与详略程度

论点：**最新一代Claude的沟通风格比之前更简洁、更自然**，具体表现在三点：
- 更直接、更"落地"：给的是基于事实的进展汇报，而不是自我表扬式的更新
- 更口语化：略微更流畅、更接地气，不那么"机器味"
- 更不啰嗦：默认可能会跳过详细总结，除非你明确要求

这带来一个实际后果：Claude可能在调用完工具后不做口头总结，直接跳到下一步动作。如果你希望看到它的推理过程，可以加这句：

```
After completing a task that involves tool use, provide a
quick summary of the work you've done.
```

**例外**：Claude Opus 5在"详略"这一点上反而是个反例——它默认的用户可见回复反而比之前的模型更长，而且调高或调低`effort`参数**不能**可靠地改变可见回复的长度；要精简回复必须直接在prompt里明确要求简洁，而不是指望调参数。

### 2. 控制回复的格式

原文给了四种引导输出格式的有效手段：

1. **告诉Claude"该做什么"而不是"不该做什么"**——与其说"不要在回复里用markdown"，不如说"你的回复应该由流畅的散文段落组成"
2. **用XML格式指示符**——比如"把回复里的散文部分写在`<smoothly_flowing_prose_paragraphs>`标签里"
3. **让你的prompt本身的风格匹配你想要的输出风格**——如果输出格式还是不听话，可以试着让prompt自身的写法尽量贴近期望的输出风格（比如prompt里去掉markdown，输出里的markdown用量往往也会跟着减少）
4. **用详细的prompt明确表达具体的格式偏好**——原文给了一段较长的"避免过度使用markdown"的示例prompt，核心要求是：写报告、文档、技术说明等长文本时用完整段落的散文体，markdown主要留给行内代码、代码块和简单标题，避免不必要的粗体/斜体，除非确实是离散条目否则不要用列表，把要点自然融进句子里

### 3. LaTeX输出

最新一代Claude默认用LaTeX表示数学表达式、方程和技术说明。如果你想要纯文本，需要显式要求：

```
Format your response in plain text only. Do not use LaTeX,
MathJax, or any markup notation such as \( \), $, or \frac{}{}.
Write all math expressions using standard text characters
(e.g., "/" for division, "*" for multiplication, and "^" for
exponents).
```

### 4. 文档创建

最新一代Claude在创建演示文稿、动画、可视化文档方面指令遵循能力强，通常第一次就能产出可用的结果。原文给的建议prompt示例：

```
Create a professional presentation on [topic]. Include
thoughtful design elements, visual hierarchy, and engaging
animations where appropriate.
```

### 5. 从"预填回复"（prefill）迁移出来

**这是一个值得单独展开的重要变化**：从Claude 4.6系列模型和Claude Mythos Preview开始，**最后一轮的assistant预填（prefill，即提前给出一段部分assistant消息让Claude续写）已经不再支持**——带预填的请求会直接返回400错误。原文给出的理由是：模型的智能程度和指令遵循能力已经进步到大多数原本需要prefill的场景已经不再需要它了。旧模型仍然支持prefill，且这个限制只影响"最后一轮assistant消息"，对话中间插入assistant消息不受影响。

原文列了五种曾经依赖prefill的典型场景，以及各自的迁移方案：

- **控制输出格式**（强制JSON/YAML、分类标签等）→ 改用[Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)功能，直接要求模型遵循给定的schema；分类任务可以用带enum字段的工具，或者structured outputs
- **消除开场白**（比如用`Here is the requested summary:\n`跳过"好的，这是您要的摘要"这类套话）→ 在system prompt里直接要求"直接回答，不要有开场白，不要以'这是...'、'基于...'这类短语开头"；也可以让模型把内容输出到XML标签里、用structured outputs或工具调用；偶尔漏网的开场白可以在后处理阶段自己截掉
- **规避不必要的拒答**→ 现在Claude在"恰当拒答"上已经好很多，直接在user消息里说清楚意图，不用prefill也足够
- **续写**（继续未完成的生成、恢复被中断的回复）→ 把续写逻辑挪到user消息里，附上之前中断回复的结尾文本："你之前的回复被中断了，结尾是`[previous_response]`，请从中断处继续"；如果是错误处理/不完整回复处理的一部分且没有用户体验损失，直接重试请求也是一种办法
- **上下文"补水"和角色一致性**（周期性确保上下文被刷新或注入）→ 长对话场景下，把之前放在prefill里的提醒挪到user轮次里；如果这是更复杂agent系统的一部分，可以考虑通过工具来"补水"（暴露一个工具，基于轮次数等启发式规则鼓励模型调用它），或者在[上下文压缩](https://platform.claude.com/docs/en/build-with-claude/compaction)阶段处理

## 四、工具使用（Tool use）

### 1. 工具触发

论点：最新一代Claude训练得更擅长精确的指令遵循，因此**需要你更明确地指示它去调用工具**。如果你说"你能不能建议一些改动"，Claude有时真的只会给建议，不会动手去改，哪怕从上下文看你其实是想让它直接改。

原文的对比例子：

```
效果较差（Claude只会给建议）：Can you suggest some changes to
improve this function?

效果更好（Claude会直接改）：Change this function to improve
its performance.
```

如果想让Claude默认更主动地采取行动，可以在system prompt里加：

```
<default_to_action>
By default, implement changes rather than only suggesting them.
If the user's intent is unclear, infer the most useful likely
action and proceed, using tools to discover any missing details
instead of guessing. Try to infer the user's intent about
whether a tool call (e.g., file edit or read) is intended or
not, and act accordingly.
</default_to_action>
```

反过来，如果你想让模型更谨慎、默认不要贸然直接改动，除非明确要求才行动：

```
<do_not_act_before_instructions>
Do not jump into implementation or change files unless clearly
instructed to make changes. When the user's intent is ambiguous,
default to providing information, doing research, and providing
recommendations rather than taking action. Only proceed with
edits, modifications, or implementations when the user
explicitly requests them.
</do_not_act_before_instructions>
```

**一个值得注意的反向提醒**：Claude Opus 4.5和Opus 4.6对system prompt的响应比之前的模型更敏感——如果你之前写prompt是为了防止模型"该用工具却不用"（undertrigger），到了这两个模型上可能反而变成"该不用工具却乱用"（overtrigger）。解法是把措辞往回收：把"CRITICAL: You MUST use this tool when..."这种强硬措辞换成更平常的"Use this tool when..."。

### 2. 优化并行工具调用

最新一代Claude会**并行运行相互独立的工具调用**：研究时同时跑多个推测性搜索、一次性读多个文件来更快建立上下文、并行跑多条bash命令（甚至可能因此拖累系统性能）。

这个行为是可以通过prompt调节的。即使不加提示模型并行调用的成功率已经很高，但你可以进一步把它推到接近100%，也可以调节"激进程度"：

```
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no
dependencies between the tool calls, make all of the
independent tool calls in parallel. Prioritize calling tools
simultaneously whenever the actions can be done in parallel
rather than sequentially. For example, when reading 3 files,
run 3 tool calls in parallel to read all 3 files into context
at the same time. Maximize use of parallel tool calls where
possible to increase speed and efficiency. However, if some
tool calls depend on previous calls to inform dependent values
like the parameters, do NOT call these tools in parallel and
instead call them sequentially. Never use placeholders or guess
missing parameters in tool calls.
</use_parallel_tool_calls>
```

如果反而想让它降低并行度、更保守地顺序执行：

```
Execute operations sequentially with brief pauses between each
step to ensure stability.
```

## 五、思考与推理（Thinking and reasoning）

### 1. 过度思考与过度周全

Claude Opus 4.6比之前的模型（尤其在更高的`effort`设置下）会做更多**前期探索**——这通常有助于优化最终结果，但模型可能在没有被要求的情况下就主动收集大量背景信息，或者同时追着好几条研究线索跑。如果你之前的prompt是鼓励模型"更彻底"，在Opus 4.6上需要重新校准：

- **用更有针对性的指令替换宽泛的默认规则**：与其说"默认使用[某工具]"，不如说"当[某工具]能提升你对问题的理解时再使用它"
- **去掉过度提示**：之前触发不足的工具现在大概率已经能正常触发，"如果拿不准就用[某工具]"这类指令现在容易造成过度触发
- **把`effort`当作兜底手段**：如果Claude依然过于激进，可以调低`effort`设置

在某些情况下Opus 4.6可能会想得非常多，导致thinking token膨胀、拖慢响应。如果这不是你想要的，可以加显式约束：

```
When you're deciding how to approach a problem, choose an
approach and commit to it. Avoid revisiting decisions unless
you encounter new information that directly contradicts your
reasoning. If you're weighing two approaches, pick one and see
it through. You can always course-correct later if the chosen
approach fails.
```

如果需要给thinking成本设一个硬上限，原文提到用`budget_tokens`做extended thinking在Opus 4.6和Sonnet 4.6上仍然可用但**已被标记为deprecated**；Claude 4.7及之后的模型上设置`budget_tokens`会直接返回400错误。更推荐的做法是降低`effort`设置，或者用`max_tokens`配合[自适应思考](https://platform.claude.com/docs/en/build-with-claude/thinking)来设硬上限。

### 2. 善用思考与交错思考能力

Claude 4.6及之后的模型（以及Claude Mythos Preview）使用**自适应思考**（`thinking: {type: "adaptive"}`）——Claude会动态决定"要不要想"以及"想多少"。到了Claude Fable 5和Mythos 5，思考**始终开启**，自适应思考是唯一模式。

模型校准思考量的依据是两个因素：`effort`参数和query本身的复杂度——effort越高、query越复杂，思考量越大；简单query不需要思考时模型会直接作答。原文明确给出结论：**在内部评估中，自适应思考的表现稳定优于老式的extended thinking**，建议迁移到自适应思考以获得最优质的回复。

自适应思考尤其适合需要agent行为的负载：多步工具调用、复杂编程任务、长跨度的agent循环。老模型仍用手动的[extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)配合`budget_tokens`。

引导Claude思考行为的示例prompt：

```
After receiving tool results, carefully reflect on their
quality and determine optimal next steps before proceeding. Use
your thinking to plan and iterate based on this new information,
and then take the best next action.
```

自适应思考的触发行为也是可以用prompt调节的——如果模型思考得比你期望的更频繁（大型或复杂的system prompt容易出现这种情况），可以加：

```
Thinking adds latency and should only be used when it will
meaningfully improve answer quality - typically for problems
that require multistep reasoning. When in doubt, respond
directly.
```

如果没有用extended thinking，不需要做任何改动。在Opus 4.6～Opus 4.8和Sonnet 4.6上，不传`thinking`参数时思考默认关闭；在Opus 5和Sonnet 5上，不传`thinking`参数时思考默认**开启**（Opus 5只有在`effort`为`high`或更低时才能关闭思考）；在Fable 5和Mythos 5上，无论是否传`thinking`参数，思考都始终开启。

补充的几条经验规则：
- **更倾向于给宽泛指令而不是照搬人写的分步方案**——像"想清楚一点"这类指令往往比人手写的分步计划带来更好的推理效果，Claude的推理深度经常超过人类会规定的程度
- **few-shot示例对思考同样有效**——可以在few-shot示例里用`<thinking>`标签展示推理模式，Claude会把这种风格泛化到自己的extended thinking块里
- **手动思维链（CoT）prompting可以作为兜底方案**——思考关闭时，仍然可以通过要求模型逐步思考问题来引导，用`<thinking>`和`<answer>`这类结构化标签把推理过程和最终输出分开。在Opus 5上更推荐保持思考开启但调低effort，而不是用这个兜底方案——因为关闭思考时，Opus 5偶尔会把内部XML标签泄漏到可见输出里
- **让Claude自我核查**——在结尾加一句"完成前，请对照[验证标准]核对你的答案"，这对编程和数学类任务的报错捕捉尤其可靠。**Opus 5是个例外**：它不需要显式指令就能很好地自我验证，如果沿用为老模型调校的"要求验证"指令，反而会造成过度验证，增加token和延迟；迁移到Opus 5时应该直接删掉这类指令，而不是改写它

原文额外提醒：思考关闭时，Opus 4.5对"think"这个词及其变体特别敏感，这种情况下可以考虑换成"consider"、"evaluate"、"reason through"这类替代词。

## 六、Agent系统（Agentic systems）

### 1. 长跨度推理与状态跟踪

最新一代Claude处理长跨度推理任务时状态跟踪能力强——通过聚焦增量进展、每次专注推进少数几件事而不是试图一口气搞定所有事，来保持长会话中的方向感。这个能力尤其体现在**跨多个上下文窗口/多次任务迭代**的场景：Claude可以在一个复杂任务上先做一段、保存状态、再用一个全新的上下文窗口继续。

**上下文感知与多窗口工作流**：Sonnet 5、Sonnet 4.6、Sonnet 4.5、Haiku 4.5具备"上下文感知"能力，能在对话过程中追踪自己剩余的上下文窗口（也就是"token预算"），从而更有效地安排任务节奏和管理上下文。

如果你在一个会自动压缩上下文、或允许把上下文存到外部文件的agent框架里用Claude（比如Claude Code），建议把这个信息告诉Claude，让它据此调整行为——否则Claude有时会在接近上下文上限时自然而然地想要收尾。原文的示例prompt：

```
Your context window will be automatically compacted as it
approaches its limit, allowing you to continue working
indefinitely from where you left off. Therefore, do not stop
tasks early due to token budget concerns. As you approach your
token budget limit, save your current progress and state to
memory before the context window refreshes. Always be as
persistent and autonomous as possible and complete tasks fully,
even if the end of your budget is approaching. Never
artificially stop any task early regardless of the context
remaining.
```

[memory工具](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)可以和"上下文感知"配合使用，管理上下文切换。

**跨多个上下文窗口的工作流**，原文给了六条具体建议：

1. **第一个上下文窗口用不同的prompt**——第一个窗口专门用来搭框架（写测试、建初始化脚本），后续窗口再基于一份待办清单去迭代
2. **让模型以结构化格式写测试**——开工前先让Claude创建测试并用结构化格式记录（比如`tests.json`），这对长期迭代能力有帮助；要提醒模型"删除或修改测试是不可接受的，这可能导致功能缺失或引入bug"
3. **搭建"生活质量"工具**——鼓励Claude创建初始化脚本（比如`init.sh`）来优雅地启动服务、跑测试套件、跑linter，避免每次从新上下文窗口继续时重复劳动
4. **从零开始 vs 压缩，怎么选**——上下文窗口被清空时，考虑直接用全新的上下文窗口，而不是用压缩。最新一代Claude非常擅长从本地文件系统里重新发现状态，某些场景下这比压缩更划算。开始新窗口时要给出明确指令，比如："先调用pwd；你只能读写这个目录下的文件"、"复查progress.txt、tests.json和git日志"、"在实现新功能前先手动跑一遍基础的集成测试"
5. **提供验证工具**——随着自主任务时长增加，Claude需要在没有持续人工反馈的情况下自行验证正确性，Playwright MCP服务器或用于测试UI的computer use能力这类工具会有帮助
6. **鼓励充分利用上下文**——提示Claude在推进下一步前高效完成当前组件："这是一个很长的任务，清晰地规划工作会有帮助。鼓励你把整个输出上下文都用在这个任务上——只要注意不要在还有大量未提交工作时就耗尽上下文。持续系统性地工作，直到完成这个任务。"

**状态管理最佳实践**：
- 结构化数据（比如测试结果、任务状态）用JSON等结构化格式，帮Claude理解schema要求
- 进度笔记用无结构的自由文本即可，适合记录大致进展和上下文
- 用git做状态追踪——git提供了"做过什么"的日志和可以回滚的检查点，最新一代Claude在用git跨多个会话追踪状态这件事上表现尤其好
- 明确要求Claude追踪自己的进度、专注于增量式工作

### 2. 平衡自主性与安全性

如果不加引导，Opus 4.6可能会执行一些**难以撤销、或影响共享系统**的操作，比如删除文件、强制推送、向外部服务发帖。如果希望Opus 4.6在执行有风险的操作前先确认，可以加这样的引导：

```
Consider the reversibility and potential impact of your actions.
You are encouraged to take local, reversible actions like
editing files or running tests, but for actions that are hard
to reverse, affect shared systems, or could be destructive, ask
the user before proceeding.

Examples of actions that warrant confirmation:
- Destructive operations: deleting files or branches, dropping
database tables, rm -rf
- Hard to reverse operations: git push --force, git reset
--hard, amending published commits
- Operations visible to others: pushing code, commenting on
PRs/issues, sending messages, modifying shared infrastructure

When encountering obstacles, do not use destructive actions as
a shortcut. For example, don't bypass safety checks (e.g.
--no-verify) or discard unfamiliar files that may be
in-progress work.
```

（这段内容和你在自己CLAUDE.md里已经配置的"执行动作要谨慎"那套规则，思路是完全一致的。）

### 3. 研究与信息收集

最新一代Claude能有效地从多个来源查找并综合信息。要拿到最优的研究结果，原文建议：

1. **给出清晰的成功标准**——明确定义"什么样的答案算成功回答了这个研究问题"
2. **鼓励信息核实**——要求Claude跨多个来源核实信息
3. **复杂研究任务用结构化方法**：

```
Search for this information in a structured way. As you gather
data, develop several competing hypotheses. Track your
confidence levels in your progress notes to improve calibration.
Regularly self-critique your approach and plan. Update a
hypothesis tree or research notes file to persist information
and provide transparency. Break down this complex research task
systematically.
```

这种结构化方法能帮Claude有条理地处理大型语料库，并迭代式地自我批判研究发现——这一点跟你在Context Window章节学到的"Write（写便签/长期记忆）"机制是同一个思路的应用。

### 4. 子agent编排

最新一代Claude能**原生编排子agent**：能识别出哪些任务适合委派给专门的子agent，并且**在没有明确指令的情况下就会主动这样做**。

要利用这个行为：
1. **确保子agent工具定义完善**——工具描述里要写清楚
2. **让Claude自然地编排**——不需要显式指令，Claude会恰当地委派
3. **注意过度使用**——Opus 4.6对子agent有很强的偏好，可能在更简单直接的做法（比如直接调一次grep）就够用的情况下也去起子agent做代码探索；Opus 5委派子agent的倾向也比之前的模型更强

如果发现子agent被过度使用，可以加显式引导：

```
Use subagents when tasks can run in parallel, require isolated
context, or involve independent workstreams that don't need to
share state. For simple tasks, sequential operations, single-file
edits, or tasks where you need to maintain context across steps,
work directly rather than delegating.
```

### 5. 串联复杂prompt

有了自适应思考和子agent编排能力，Claude现在能在内部处理大部分多步推理。显式的prompt链（把任务拆成多次连续的API调用）仍然有用的场景是：**你需要检查中间输出、或者需要强制执行某个特定的流水线结构**。

最常见的链式模式是**自我纠错**：生成草稿 → 让Claude按标准审查 → 让Claude基于审查意见修改。每一步都是独立的API调用，所以你可以在任意节点做日志记录、评估或分支判断。

### 6. 减少agent编程场景下的文件创建

最新一代Claude在编程场景下有时会创建新文件用于测试和迭代——把文件（尤其是Python脚本）当作保存最终输出前的"临时草稿本"。使用临时文件对agent编程场景的结果通常有正面帮助。

如果你更希望尽量减少净新增文件，可以要求Claude自己清理：

```
If you create any temporary new files, scripts, or helper files
for iteration, clean up these files by removing them at the end
of the task.
```

### 7. 过度热心（Overeagerness）

Opus 4.5和Opus 4.6有过度工程化的倾向：创建多余文件、添加不必要的抽象、内置了没被要求过的灵活性。如果出现这种不想要的行为，需要加具体引导让方案保持精简：

```
Avoid over-engineering. Only make changes that are directly
requested or clearly necessary. Keep solutions simple and
focused:

- Scope: Don't add features, refactor code, or make
"improvements" beyond what was asked. A bug fix doesn't need
surrounding code cleaned up. A simple feature doesn't need extra
configurability.

- Documentation: Don't add docstrings, comments, or type
annotations to code you didn't change. Only add comments where
the logic isn't self-evident.

- Defensive coding: Don't add error handling, fallbacks, or
validation for scenarios that can't happen. Trust internal code
and framework guarantees. Only validate at system boundaries
(user input, external APIs).

- Abstractions: Don't create helpers, utilities, or abstractions
for one-time operations. Don't design for hypothetical future
requirements. The right amount of complexity is the minimum
needed for the current task.
```

（眼熟的话——这段内容和你CLAUDE.md里"不要添加超出任务范围的功能/重构/抽象"那条规则几乎是同一套原则，只是这里是Anthropic官方给出的推荐prompt模板。）

### 8. 避免只顾"过测试"和硬编码

Claude有时会过度专注于让测试通过，而牺牲了方案的通用性；或者用helper脚本这类变通手段去做复杂重构，而不是直接用标准工具。要避免这个行为、拿到能泛化的解法：

```
Please write a high-quality, general-purpose solution using the
standard tools available. Do not create helper scripts or
workarounds to accomplish the task more efficiently. Implement a
solution that works correctly for all valid inputs, not just the
test cases. Do not hard-code values or create solutions that
only work for specific test inputs. Instead, implement the
actual logic that solves the problem generally.

Focus on understanding the problem requirements and implementing
the correct algorithm. Tests are there to verify correctness,
not to define the solution. Provide a principled implementation
that follows best practices and software design principles.

If the task is unreasonable or infeasible, or if any of the
tests are incorrect, please inform me rather than working around
them. The solution should be robust, maintainable, and
extendable.
```

### 9. 减少agent编程中的幻觉

最新一代Claude的幻觉倾向更低，给出的答案更贴合实际代码。要进一步强化这一点、最小化幻觉：

```
<investigate_before_answering>
Never speculate about code you have not opened. If the user
references a specific file, you MUST read the file before
answering. Make sure to investigate and read relevant files
BEFORE answering questions about the codebase. Never make any
claims about code before investigating unless you are certain of
the correct answer - give grounded and hallucination-free
answers.
</investigate_before_answering>
```

## 七、能力专项小贴士（Capability-specific tips）

### 1. 视觉能力提升

Opus 4.5和Opus 4.6的视觉能力相比之前的Claude模型有提升，在图像处理和数据提取任务上表现更好，尤其是上下文里有多张图片的场景；这些提升也延伸到了computer use场景，模型能更可靠地解读截图和UI元素；这两个模型也可以通过把视频拆成逐帧图片来做视频分析。

一个被证实有效的进一步提升手段：**给Claude一个"裁剪"工具**（crop tool）或[agent skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)。测试显示，当Claude能对图像的相关区域"放大"查看时，图像相关评估的表现有稳定提升。Anthropic给出了对应的[裁剪工具recipe](https://platform.claude.com/cookbook/multimodal-crop-tool)。

### 2. 前端设计

Opus 4.5和Opus 4.6能构建复杂的、贴近真实场景的Web应用，前端设计能力强。但如果不加引导，模型容易默认走向通用套路，产出用户口中的"AI味"审美（"AI slop"）。原文给了一段较长的system prompt片段用来引导更好的前端设计，核心要求包括：字体选择要独特、避免Arial/Inter这类通用字体；配色要有整体一致的主题，用CSS变量保持一致性，主色调配合鲜明的点缀色比"温吞、均匀分布"的配色效果更好；动效要聚焦高影响力的时刻（比如一次精心编排的页面加载动画，比分散的微交互更能带来惊喜感）；背景要营造氛围和层次感，而不是默认纯色。同时要避免的"AI味"表现：滥用的字体家族（Inter、Roboto、Arial等系统字体）、老套的配色方案（尤其是白底紫色渐变）、可预测的布局和组件模式。

原文还提到，前端设计工作如果不通过API，Anthropic有一个叫[Claude Design](https://support.claude.com/en/articles/14604416-get-started-with-claude-design)的产品，提供画布和设计工具，可以交互式地生成和迭代设计稿。完整的技能定义可以参考[frontend-design skill](https://github.com/anthropics/claude-code/blob/main/plugins/frontend-design/skills/frontend-design/SKILL.md)。

## 八、迁移注意事项（Migration considerations）

从旧一代模型迁移到最新Claude模型时，原文给了六条建议：

1. **明确描述你想要的具体行为**，而不是笼统地提要求
2. **用修饰语给指令加"框架"**——加一些鼓励Claude提升输出质量和细节的修饰语，能更好地引导表现（前面"仪表盘"的例子就是这个思路）
3. **显式要求具体的功能特性**——想要动画、交互元素，需要明确说出来
4. **更新思考配置**——Claude 4.6系列模型用[自适应思考](https://platform.claude.com/docs/en/build-with-claude/thinking)（`thinking: {type: "adaptive"}`）取代了手动设`budget_tokens`的思考方式，用[effort参数](https://platform.claude.com/docs/en/build-with-claude/effort)控制思考深度
5. **从预填回复迁移出来**——Claude 4.6系列模型和Mythos Preview开始不再支持最后一轮的assistant预填，具体替代方案见上文"预填回复迁移"一节
6. **调校"防偷懒"类的prompt**——如果之前的prompt是为了鼓励模型更彻底或更积极地用工具，在Claude 4.6系列模型上需要把这类引导往回收，因为这些模型本身已经更主动，沿用老prompt容易造成过度触发

详细迁移步骤参考官方[Migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide)。

---

**小结**（金字塔顶层）：这篇文档最核心的一条主线贯穿全文——**最新一代Claude比之前的模型更严格地按字面意思执行指令，不再自动脑补言外之意**。这既意味着老prompt里那些"防止模型偷懒/触发不足"的强硬措辞现在大概率要往回收（否则会过度触发），也意味着你想要的任何"隐含期待"（格式、语气、主动程度、验证严格度）现在都必须显式写出来，不能再指望模型自己猜。
