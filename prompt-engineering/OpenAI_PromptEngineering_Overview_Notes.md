> 原文：[Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering) — OpenAI API文档
>
> 逐节笔记，按原文章节顺序走，本版比第一版更贴近原文逐句展开（不是只给summary），并保留原文的API/代码示例。原文每个示例都给了JavaScript/Python/Go/Java/C#/Ruby/CLI/curl八种等价写法，逻辑完全相同，笔记只保留Python和curl两个代表，其余语言需要时去[原文](https://developers.openai.com/api/docs/guides/prompt-engineering)抄。这篇是OpenAI**面向所有当前模型的通用方法论**文档，和你之前读的《GPT-4.1 Prompting Guide》不是同一篇——那篇是针对GPT-4.1这一代模型调优的专属指南，这篇讲的是"选模型、组织prompt结构、管理成本"这类跟具体某一代模型无关的工程实践。

## 开篇：基本用法

原文开门见山：用OpenAI API，你可以像用ChatGPT一样，让大语言模型根据一个prompt生成文本——模型几乎能生成任何形式的文本回应，代码、数学公式、结构化JSON数据、或者像人写的散文都可以。

原文给出了用[Responses API](https://developers.openai.com/api/reference/resources/responses)生成文本的最简示例：

```python
from openai import OpenAI

client = OpenAI()

response = client.responses.create(
    model="gpt-5.6",
    input="Write a one-sentence bedtime story about a unicorn.",
)

print(response.output_text)
```

```bash
curl "https://api.openai.com/v1/responses" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -d '{
        "model": "gpt-5.6",
        "input": "Write a one-sentence bedtime story about a unicorn."
    }'
```

模型生成的内容数组放在响应的`output`属性里。这个最简单例子里，`output`只有一项，长这样：

```json
[
  {
    "id": "msg_67b73f697ba4819183a15cc17d011509",
    "type": "message",
    "role": "assistant",
    "content": [
      {
        "type": "output_text",
        "text": "Under the soft glow of the moon, Luna the unicorn danced through fields of twinkling stardust, leaving trails of dreams for every child asleep.",
        "annotations": []
      }
    ]
  }
]
```

原文特别提醒一个容易踩的坑：**`output`数组里经常不止一项**！它可能包含工具调用、推理模型产生的推理token相关数据、以及其他条目——**不能想当然地假设模型的文本输出就一定在`output[0].content[0].text`这个固定位置**。为了方便，官方SDK在响应对象上提供了一个`output_text`属性，会把模型所有的文本输出聚合成一个字符串，可以当作快捷方式来用。

除了纯文本，模型也可以按JSON格式返回结构化数据——这个功能叫[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)（也就是你之前提到自己已经学过的"结构化输出"）。

## 一、选模型

通过API生成内容时，一个关键选择是用`model`参数指定哪个模型（完整模型列表见[模型文档](https://developers.openai.com/api/docs/models)）。原文给了几个选模型时要考虑的因素：

- **[推理模型（Reasoning models）](https://developers.openai.com/api/docs/guides/reasoning)**：生成内部思维链来分析输入prompt，擅长理解复杂任务和多步规划，但通常比GPT模型更慢、更贵
- **GPT模型**：速度快、成本效率高、智能程度也高，但需要更明确的指令来说明该怎么完成任务，才能发挥出最好效果
- **大模型 vs 小模型（mini/nano）**：在速度、成本、智能程度之间做权衡——大模型在理解prompt和跨领域解决问题上更有效，小模型通常更快、更便宜

原文的默认建议：拿不准选哪个时，[`gpt-5.6`](https://developers.openai.com/api/docs/models/gpt-5.6-sol)是通用文本生成和prompt迭代场景下一个稳妥的默认选择。

## 二、什么是提示词工程

**提示词工程**被定义为：为模型编写有效的指令，让它能稳定产出符合你要求内容的过程。

因为模型生成的内容本身是非确定性的，想拿到期望的输出，这件事天然是"手艺与科学的混合体"——但依然可以运用具体的技巧和最佳实践，稳定地拿到好结果。

原文提醒：有些提示词工程技巧对所有模型都适用（比如用消息角色），但不同类型的模型（推理模型 vs GPT模型）可能需要用不同方式来提示才能拿到最好的结果；哪怕是同一个模型家族内不同的模型快照版本，输出结果也可能不一样。所以随着你构建的应用越来越复杂，原文强烈建议：

- 给生产环境应用**锁定具体的[模型快照](https://developers.openai.com/api/docs/models)**（比如`gpt-4.1-2025-04-14`这样精确到版本），确保行为一致
- 搭建能衡量prompt行为的测试和评估套件，这样无论是你自己迭代prompt，还是换了/升级了模型版本，都能持续监控效果

## 三、消息角色与指令遵循的优先级

可以用`instructions`这个API参数，或者用**消息角色（message roles）**，给模型提供[不同权威等级](https://model-spec.openai.com/2025-02-12.html#chain_of_command)的指令。

`instructions`参数给模型提供高层次的行为指导——包括语气、目标、正确回应的示例。通过这个参数传入的任何指令，**优先级都高于`input`参数里的prompt内容**。

```python
from openai import OpenAI

client = OpenAI()

response = client.responses.create(
    model="gpt-5.6",
    reasoning={"effort": "low"},
    instructions="Talk like a pirate.",
    input="Are semicolons optional in JavaScript?",
)

print(response.output_text)
```

上面这个例子，大致等价于在`input`数组里传入下面这种带不同角色的消息：

```python
response = client.responses.create(
    model="gpt-5.6",
    reasoning={"effort": "low"},
    input=[
        {"role": "developer", "content": "Talk like a pirate."},
        {"role": "user", "content": "Are semicolons optional in JavaScript?"},
    ],
)
```

原文提醒一个容易忽略的细节：**`instructions`参数只对当前这一次生成请求生效**。如果你是用`previous_response_id`参数管理多轮对话状态，前几轮用过的`instructions`**不会**留在后续轮次的上下文里——每一轮都要重新传，不会自动延续。

[OpenAI model spec](https://model-spec.openai.com/2025-02-12.html#chain_of_command)描述了模型如何给不同角色的消息赋予不同的优先级：

| 角色 | 定位 |
|---|---|
| `developer` | 应用开发者提供的指令，优先级排在`user`消息**之前** |
| `user` | 终端用户提供的指令，优先级排在`developer`消息**之后** |
| `assistant` | 模型自己生成的消息 |

一次多轮对话可能由这几种类型的多条消息组成，还会混合你和模型提供的其他内容类型（详见[管理对话状态](https://developers.openai.com/api/docs/guides/conversation-state)）。

原文给了一个很直观的类比来理解`developer`和`user`的关系：**可以把它们想象成编程语言里的一个函数和它的参数**。

- `developer`消息提供系统的规则和业务逻辑，就像函数定义
- `user`消息提供应用`developer`消息里那些指令时所需的具体输入和配置，就像函数的参数

## 四、把prompt存进代码里做版本管理

原文建议：把生产环境用的prompt**直接存在应用代码里**，而不是创建可复用的"prompt对象"。代码管理的prompt能让你用上带类型的输入、代码审查、测试，以及你正常的部署流程来改变模型行为。

原文特别提到一个即将生效的变化：**OpenAI正在弃用API里的"可复用prompt对象"功能**——从2026年6月3日起会淡化prompt创建功能，`v1/prompts`计划在2026年11月30日下线（详见[弃用页面](https://developers.openai.com/api/docs/deprecations#2026-06-03-reusable-prompts)的最新时间表）。

针对新的提示词工程工作，原文给了几条具体建议：

- 把prompt构建逻辑放在靠近它所支撑的功能的一个小模块里
- 对客户数据、文件、任务选项这类动态值，用带类型的函数参数或schema
- 把生成好的`instructions`和`input`直接传给[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- 改动生产prompt之前，先准备有代表性的测试fixture、测试用例和评估检查
- 通过你自己的部署系统来上线prompt改动，需要分阶段发布时用feature flag或配置项控制

如果你现有的集成已经在用带prompt ID或版本号的已保存prompt，原文指向了一份[prompt对象迁移指南](https://developers.openai.com/api/docs/guides/prompting/migrate-from-prompt-object)，帮你把这类prompt挪进代码里。

## 五、用Markdown和XML组织消息格式

写`developer`和`user`消息时，可以结合用[Markdown](https://commonmark.org/help/)格式和[XML标签](https://www.w3.org/TR/xml/)，帮模型理解prompt和背景数据里的逻辑边界。

Markdown标题和列表能标出prompt里不同的区块，向模型传达层级关系，同时也能让你自己开发时读prompt更方便。XML标签能划清"一段内容从哪开始、到哪结束"的边界（比如一份用作参考的支撑文档），XML属性还可以给prompt里的内容定义元数据，供你的指令引用。

原文给出的典型`developer`消息组织顺序（实际最优内容和顺序可能因模型而异）：

- **Identity（身份）**：描述assistant的目的、沟通风格、高层次目标
- **Instructions（指令）**：告诉模型该怎么生成你想要的回应——该遵循什么规则、该做什么、绝对不能做什么。这一节可以按需要拆出很多小节，比如模型该怎么[调用自定义函数](https://developers.openai.com/api/docs/guides/function-calling)
- **Examples（示例）**：给出可能的输入，配上模型该给出的期望输出
- **Context（背景）**：给模型提供生成回应可能需要的额外信息，比如训练数据之外的私有/专有数据，或者其他你确定会特别相关的数据。这部分内容通常最好放在prompt靠后的位置，因为不同的生成请求可能需要带不同的背景信息

原文给了一个完整的例子，演示怎么用Markdown和XML标签构造一条带独立分区和配套示例的`developer`消息：

```text
# Identity

You are coding assistant that helps enforce the use of snake case
variables in JavaScript code, and writing code that will run in
Internet Explorer version 6.

# Instructions

* When defining variables, use snake case names (e.g. my_variable)
  instead of camel case names (e.g. myVariable).
* To support old browsers, declare variables using the older
  "var" keyword.
* Do not give responses with Markdown formatting, just return
  the code as requested.

# Examples

<user_query>
How do I declare a string variable for a first name?
</user_query>

<assistant_response>
var first_name = "Anna";
</assistant_response>
```

对应的API调用（把这份prompt文本作为`instructions`传进去）：

```python
from openai import OpenAI

client = OpenAI()

with open("prompt.txt", "r", encoding="utf-8") as f:
    instructions = f.read()

response = client.responses.create(
    model="gpt-5.6",
    instructions=instructions,
    input="How would I declare a variable for a last name?",
)

print(response.output_text)
```

```bash
curl https://api.openai.com/v1/responses \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.6",
    "instructions": "'"$(< prompt.txt)"'",
    "input": "How would I declare a variable for a last name?"
  }'
```

### 用Prompt Caching节省成本和延迟

构造消息时，应该把你预期会被反复使用的内容放在prompt的**最前面**，并且在传给[Chat Completions](https://developers.openai.com/api/reference/resources/chat)或[Responses](https://developers.openai.com/api/reference/resources/responses)的JSON请求体里，也排在**靠前的参数位置**——这样才能最大化享受[prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)带来的成本和延迟节省。（这一点你在Token经济学章节已经学过缓存命中的原理，这里是它在消息组织层面的直接应用。）

## 六、Few-shot学习

Few-shot学习让你能通过在prompt里放入少量输入/输出示例，把大语言模型引导向一个新任务，而不需要对模型做[微调（fine-tuning）](https://developers.openai.com/api/docs/guides/model-optimization)。模型会隐式地从这些示例里"学到"模式规律，再把这个规律应用到实际的prompt上。给示例时，尽量展示范围多样的可能输入，配上对应的期望输出。

通常，你会把示例作为API请求里`developer`消息的一部分传入。原文给了一个示例：一条`developer`消息，教模型怎么把客户评价分类成正面、负面或中性：

```text
# Identity

You are a helpful assistant that labels short product reviews as
Positive, Negative, or Neutral.

# Instructions

* Only output a single word in your response with no additional formatting
  or commentary.
* Your response should only be one of the words "Positive", "Negative", or
  "Neutral" depending on the sentiment of the product review you are given.

# Examples

<product_review id="example-1">
I absolutely love this headphones — sound quality is amazing!
</product_review>

<assistant_response id="example-1">
Positive
</assistant_response>

<product_review id="example-2">
Battery life is okay, but the ear pads feel cheap.
</product_review>

<assistant_response id="example-2">
Neutral
</assistant_response>

<product_review id="example-3">
Terrible customer service, I'll never buy from them again.
</product_review>

<assistant_response id="example-3">
Negative
</assistant_response>
```

（这个"示例要多样、要覆盖不同情况"的论点，和你在Anthropic、Gemini两篇笔记里读到的结论完全一致，三家在这一点上是业内共识，不需要再逐家横向对比。）

## 七、补充相关背景信息

在给模型的prompt里加入额外的背景信息，通常很有用。原文给了两个常见的理由：

- 让模型能访问专有数据，或者训练数据集之外的其他数据
- 把模型的回应限制在一组你确定会最有帮助的特定资源范围内

给模型生成请求补充相关背景信息的这项技术，有时被称为**检索增强生成（retrieval-augmented generation, RAG）**。补充背景信息的方式有很多种，可以查询向量数据库、把查到的文本内容放进prompt，也可以用OpenAI内置的[文件搜索工具](https://developers.openai.com/api/docs/guides/tools-file-search)，基于上传的文档生成内容。

### 规划上下文窗口的用量

模型在一次生成请求里能考虑的数据量是有限的。这个记忆上限叫**上下文窗口（context window）**，用[token](https://blogs.nvidia.com/blog/ai-tokens-explained)（你传入的数据块，从文本到图像都算）来定义。

不同模型的上下文窗口大小差异很大——从10万级别到新一代GPT-4.1系列模型的100万token都有（具体每个模型的上下文窗口大小，请查[模型文档](https://developers.openai.com/api/docs/models)）。

## 八、当前GPT-5系列模型的提示词方法

像[`gpt-5.6`](https://developers.openai.com/api/docs/models/gpt-5.6-sol)这样的GPT模型，在prompt里**明确提供完成任务所需的逻辑和数据**时效果最好。想要最大程度发挥最新GPT-5系列模型的效果，原文建议从当前的提示词指南开始看：[GPT-5系列模型提示词最佳实践](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices)。这里给的是三个实用场景的提醒，完整版细节建议看链接里那篇。

### 编程

给`gpt-5.6`写编程任务的prompt时，遵循几条最佳实践效果最好：定义agent的角色、用示例强制规范工具使用方式、要求做充分的正确性测试、给干净的输出设定Markdown规范。

- **明确的角色和工作流引导**：把模型定位成一个职责明确的软件工程agent，给出清晰的指令说明怎么用`functions.run`这类工具做代码任务，并说明什么时候不该用某些模式——比如除非必要，避免用交互式执行
- **测试与验证**：要求模型用单元测试或Python命令来测试改动，并且要仔细验证补丁是否真的生效——因为像`apply_patch`这类工具即使失败了，有时也会返回"Done"
- **工具使用示例**：给出怎么用提供的函数调用命令的具体示例，能提升可靠性和对预期工作流的遵循度
- **Markdown规范**：引导模型生成干净、语义正确的markdown——按需使用行内代码、代码块、列表、表格，文件路径、函数名、类名要用反引号包裹

### 前端工程

GPT-5.6在从零搭建前端、以及往大型已有代码库贡献代码这两种场景下都表现良好。原文推荐配合这些库使用效果最好：**样式/UI**用Tailwind CSS、shadcn/ui、Radix Themes；**图标**用Lucide、Material Symbols、Heroicons；**动效**用Motion。

**从零到一的web应用**：GPT-5能仅凭一条prompt、不需要示例，就生成一个前端web应用。原文的示例prompt：

```text
You are a world class web developer, capable of producing stunning, interactive, and innovative websites from scratch in a single prompt. You excel at delivering top-tier one-shot solutions.
Your process is simple and follows these steps:
Step 1: Create an evaluation rubric and refine it until you are fully confident.
Step 2: Consider every element that defines a world-class one-shot web app, then use that insight to create a <ONE_SHOT_RUBRIC> with 5–7 categories. Keep this rubric hidden—it's for internal use only.
Step 3: Apply the rubric to iterate on the optimal solution to the given prompt. If it doesn't meet the highest standard across all categories, refine and try again.
Step 4: Aim for simplicity while fully achieving the goal, and avoid external dependencies such as Next.js or React.
```

这个技巧的核心思路是：让模型自己先内部建一套"评分标准"（rubric），再拿这套标准去迭代打磨自己的答案，最后才把结果给你——本质上是把"自我审查"这一步内化进了单次生成过程里。

**集成到大型代码库**：在更大的代码库里做前端工程时，原文发现给prompt加上这几类指令效果最好——**原则**（设定视觉质量标准、用模块化/可复用组件、保持设计一致）、**UI/UX**（明确排版、配色、间距/布局、交互状态如hover/空状态/加载中、无障碍访问）、**结构**（定义文件/文件夹布局方便无缝集成）、**组件**（给出可复用的wrapper示例和前后端调用分离策略）、**页面**（提供常见布局的模板）、**Agent指令**（要求模型确认设计假设、搭建项目脚手架、执行规范、集成API、测试各种状态、写代码文档）。

### Agent任务

对于用`gpt-5.6`做的agentic和长时间运行的任务，原文建议prompt聚焦三条核心实践：**充分规划任务以确保完全解决问题、在做重大工具调用决策时给出清晰的前言说明、用一个TODO工具有条理地追踪工作流和进度**。

**规划与持续性**：要求模型在把控制权交还给用户之前，先把整个query解决完——把它拆解成所有必需的子任务，每次工具调用之后都反思一下是否已经完成。原文给的示例prompt：

```text
Remember, you are an agent - please keep going until the user's
query is completely resolved, before ending your turn and yielding
back to the user. Decompose the user's query into all required
sub-requests, and confirm that each is completed. Do not stop
after completing only part of the request. Only terminate your
turn when you are sure that the problem is solved. You must be
prepared to answer multiple queries and only finish the call once
the user has confirmed they're done.

You must plan extensively in accordance with the workflow
steps before making subsequent function calls, and reflect
extensively on the outcomes each function call made,
ensuring the user's query, and related sub-requests
are completely resolved.
```

（这段和你在《GPT-4.1 Prompting Guide》笔记里读到的"persistence"提醒几乎是同一套思路的延续版本，只是措辞更细化了。）

**用前言保持透明**：要求模型在调用工具前解释一下为什么要调用它，但只在关键节点这样做：

```text
Before you call a tool explain why you are calling it
```

**用rubric和TODO做进度追踪**：用一个TODO清单工具或rubric来强制结构化规划，避免漏掉步骤。

## 九、给推理模型写提示词

给[推理模型](https://developers.openai.com/api/docs/guides/reasoning)写prompt和给GPT模型写prompt，有一些需要注意的差异。总体来说，**推理模型只需要高层次的引导，就能在任务上给出更好的结果**——这和GPT模型不同，GPT模型更受益于非常精确具体的指令。

原文给了一个很形象的类比：

- 推理模型就像一位**资深同事**——你可以给他们一个要达成的目标，然后信任他们自己把细节想清楚
- GPT模型就像一位**初级同事**——给出明确具体的指令，让他们产出特定的输出，他们才能表现最好

更多推理模型的最佳实践，原文指向了专门的[推理模型最佳实践指南](https://developers.openai.com/api/docs/guides/reasoning-best-practices)。

## 十、后续与其他资源

原文结尾指向几个延伸方向：想上手实验，可以在[Playground](https://platform.openai.com/chat/edit)里搭建和迭代prompt；想要生成符合JSON schema的结构化数据，看[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)；想查完整的API选项细节，看[API参考文档](https://developers.openai.com/api/reference/resources/responses)。

另外，[OpenAI Cookbook](https://developers.openai.com/cookbook)里有更多示例代码，也链接了一批第三方资源：提示词相关的库和工具、提示词指南、视频课程、以及讲高级提示词技巧（用来提升推理能力）的论文。

---

**小结**（金字塔顶层）：这篇文档和你已经读过的Claude/GPT-4.1/Gemini三篇比,重合的核心原则不少（示例要多样、结构要清晰、instructions优先级高于user输入）,但它更聚焦"工程落地"层面——怎么做prompt的代码化版本管理、怎么用缓存策略省成本、怎么规划上下文预算,这些是纯技巧文档里比较少提的运维视角。"给推理模型 vs 给GPT模型 写prompt要区别对待"这一条,是几篇里比较独特的一个论点,值得单独记一下。
