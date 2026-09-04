# Safety and Security for AI Agents 学习笔记

来源：Google Agent Development Kit（ADK）官方文档，地址 https://adk.dev/safety/ 。本笔记不逐字翻译，是转述机制设计和代码逻辑，关键短句用引用块标出，保留了最有代表性的一段示例代码（Python）。

**这篇在本章的位置**：这是本章目前**唯一给出可运行代码**的一篇——前面Anthropic三篇讲的是产品级架构决策（沙箱/VM/凭证代理），OpenAI那篇讲的是prompt层面的建议但没有代码，这篇是框架级的具体API：怎么用ADK的`ToolContext`、`before_tool_callback`、Plugin机制，把"给agent设边界"这件事写成真正能跑的代码。跟前面几篇比，深度不输Anthropic，但视角更偏"开发者拿到框架之后具体怎么写"，不是"公司怎么做架构决策"。

## 目录

- [1 多层防护总览](#1-多层防护总览)
- [2 安全与安全风险](#2-安全与安全风险)
- [3 最佳实践](#3-最佳实践)
- [4 其他安全风险：UI里的模型生成内容](#4-其他安全风险ui里的模型生成内容)
- [5 值得记的点](#5-值得记的点)
- [6 跟OWASP Top 10 for Agentic Applications的对应关系](#6-跟owasp-top-10-for-agentic-applications的对应关系)
- [参考资料](#参考资料)

## 1 多层防护总览

开篇先给了一句风险来源清单：

> Sources of risk include vague instructions, model hallucination, jailbreaks and prompt injections from adversarial users, and indirect prompt injections via tool use.

翻译：风险来源包括模糊的指令、模型幻觉、来自恶意用户的越狱和prompt注入、以及通过工具使用发生的间接prompt注入。

Google Cloud Agent Platform给出的是**五层防护**，跟前面三篇Anthropic文章"环境层+模型层+外部内容层"三分法不完全对齐，是一套更细的分类：

1. **身份与授权（Identity and Authorization）**：控制agent"以谁的身份"行动——定义agent自己的身份认证和用户的身份认证。
2. **筛查输入输出的Guardrails**：精确控制模型和工具调用，细分四种具体机制（下面第3节展开）。
3. **沙箱化代码执行**：防止模型生成的代码造成安全问题。
4. **评估与追踪（Evaluation and tracing）**：用评估工具衡量agent最终输出的质量、相关性、正确性；用tracing获得agent行动的可见性，分析它选了什么工具、用了什么策略、路径效不效率。
5. **网络控制与VPC-SC**：把agent活动限制在安全边界内（比如VPC Service Controls），防止数据外泄、限制潜在影响范围。

## 2 安全与安全风险

文档强调：**上具体防护措施之前，先针对自己agent的能力、领域、部署场景做一次彻底的风险评估**。

**风险来源**（跟开篇那句基本重复，但单独成节强调）：模糊的agent指令、来自恶意用户的prompt注入和越狱尝试、通过工具使用发生的间接prompt注入。

**风险分类**（三类）：

- **目标偏移与目标腐化（Misalignment & goal corruption）**：追求非预期的或代理性的目标，导致有害结果（"reward hacking"）；误解复杂或模糊的指令。
- **有害内容生成，含品牌安全**：生成有毒、仇恨、有偏见、露骨、歧视性或非法内容；品牌安全风险，比如用了违背品牌价值观的语言、或聊跑题了。
- **不安全的行动**：执行破坏系统的命令；未经授权的购买或金融交易；泄露敏感个人数据（PII）；数据外泄。

## 3 最佳实践

### 身份与授权

**这一段的核心观点**：工具用什么身份去操作外部系统，是从安全角度看至关重要的设计决策——同一个agent里不同的工具可以配置不同的身份策略。两种模式：

**Agent-Auth**：工具用**agent自己的身份**（比如一个service account）跟外部系统交互——这个身份必须在外部系统的访问策略里被显式授权（比如把agent的service account加进数据库IAM策略里、只给读权限）。这类策略能约束agent只做开发者本来就打算允许的事：即便给资源开了只读权限，不管模型自己想做什么，工具都无法执行写操作。

> 这个方案实现简单，**适合"所有用户权限级别都一样"的agent**。如果用户权限不一致，单靠这个方案不够，必须配合下面的其他技术。工具实现里要记得留日志维系"操作对应哪个用户"这条归因链，因为agent的所有操作看起来都是来自agent本身的。

**User Auth**：工具用**"操控用户"（比如在前端跟agent交互的那个人）的身份**去跟外部系统交互——ADK里典型实现是OAuth：agent先跟前端交互拿到一个OAuth token，工具执行外部操作时带上这个token，外部系统按"这个用户自己有没有权限做这件事"来做授权判断。

> User Auth的优势是agent只能做用户自己本来就能做的事，大幅降低恶意用户滥用agent去获取额外数据访问权限的风险。但常见的委托实现通常只有一组固定的可委托权限（也就是OAuth scope），这些scope往往比agent实际需要的权限更宽——这时还是需要下面的技术进一步收紧agent的实际动作范围。

### 筛查输入输出的Guardrails

**In-tool guardrails（工具内部的护栏）**：可以有意识地设计工具本身的安全性——只暴露我们想让模型执行的那些动作，别的什么都不暴露。通过限制提供给agent的动作范围，能**确定性地**消除掉一整类我们永远不希望agent做的失控动作。

机制依赖的是工具能接收两类输入：模型设置的**参数（arguments）**，和开发者以确定性方式设置的**`Tool Context`**——可以依靠这份确定性设置的信息，去校验模型的行为是不是符合预期。文档给了一个具体例子：一个查询工具可以被设计成从Tool Context里读取一份policy：

```python
# 设置policy（概念示例）
policy = {}
policy['select_only'] = True
policy['tables'] = ['mytable1', 'mytable2']
invocation_context.session.state["query_tool_policy"] = policy

# 工具执行时，Tool Context会被传进来，工具自己校验policy
def query(query: str, tool_context: ToolContext) -> str | dict:
  policy = tool_context.invocation_context.session.state.get('query_tool_policy', {})
  actual_tables = explainQuery(query)

  if not set(actual_tables).issubset(set(policy.get('tables', []))):
    allowed = ", ".join(policy.get('tables', ['(None defined)']))
    return f"Error: Query targets unauthorized tables. Allowed: {allowed}"

  if policy.get('select_only', False):
    if not query.strip().upper().startswith("SELECT"):
      return "Error: Policy restricts queries to SELECT statements only."

  return {"status": "success", "results": [...]}
```

这个例子很清楚地展示了跟OpenAI那篇"用结构化输出约束数据流"的本质区别：OpenAI那篇只停在"用枚举/schema约束"这个概念层面，这里直接给出了**校验逻辑写在哪、怎么写**——policy是开发者在初始化时确定性设置好的，跟模型自己生成的`query`参数完全隔离，模型不管怎么生成query，工具执行前都会先拿policy校验一遍表名和语句类型。

**Built-in Gemini Safety Features（Gemini内置安全特性）**：

- **内容安全过滤器**：分两种，**不可配置的过滤器**自动屏蔽CSAM、PII这类被禁止的内容；**可配置的过滤器**让你按四类危害（仇恨言论、骚扰、露骨内容、危险内容）设置基于概率和严重度分数的拦截阈值，默认关闭，可以自己配置。
- **安全系统指令**：直接在system instruction里指导模型该怎么表现、该生成什么类型的内容，可以写清楚禁止/敏感话题、免责声明措辞、以及品牌调性方面的要求。

文档明确指出这两个特性的边界：

> While these measures are robust against content safety, you need additional checks to reduce agent misalignment, unsafe actions, and brand safety risks.

翻译：这两个特性在内容安全上很扎实，但要降低agent目标偏移、不安全行动、品牌安全这几类风险，还需要额外的检查手段——**内容过滤器管的是"说了什么"，管不住"做了什么"**。

**Callbacks and Plugins（回调与插件）**：这是这篇文档区分度最高的一段，把"给单个agent加护栏"和"给整个系统统一加护栏"分成了两条路：

- **Callback**：给单个agent、单次工具/模型I/O加预校验的简单方法。当工具本身没法改造加护栏时，可以用`Before Tool Callback`——这个回调能拿到agent状态、被请求的工具、以及参数，做一次校验（比如检查参数里的user_id是不是跟session里记录的用户一致，不一致就返回错误、阻止工具执行）。这个方式很通用，甚至可以做成一个可复用的策略库；缺点是如果护栏需要的信息不在参数里直接可见，就用不上。
- **Plugin**：**当你要实现的策略不是针对单个agent、而是要在多个agent之间通用时，官方推荐用Plugin**——设计成自包含、模块化的形式，能在runner层面全局生效：一个安全插件配置一次，就能应用到用这个runner的每一个agent上，不用每个agent重复写一遍。文档举了三个具体例子：
  - **Gemini as a Judge Plugin**：用Gemini Flash Lite评估用户输入、工具输入输出、agent响应是否恰当、有没有prompt注入或越狱迹象，判定不安全就返回一句固定话术（"抱歉我没法帮你处理这个，还有什么我能帮忙的吗？"）。
  - **Model Armor Plugin**：在agent执行的指定节点查询Model Armor API，检测潜在的内容安全违规，命中就返回固定话术。
  - **PII Redaction Plugin**：专门为`Before Tool Callback`设计，在数据被工具处理或发给外部服务之前，先把PII打码。

### 沙箱化代码执行

代码执行是一种特殊的工具，有额外的安全含义：必须用沙箱防止模型生成的代码危害本地环境。ADK给了两个现成选项：Vertex Gemini Enterprise API的代码执行功能（服务端沙箱化）、以及ADK里的Code Executor工具（调用Vertex Code Interpreter Extension，适合做数据分析）。

如果这两个都不满足需求，官方建议自己用ADK提供的组件搭一个代码执行器，并给了两条具体的加固建议：

> We recommend creating execution environments that are hermetic: no network connections and API calls permitted to avoid uncontrolled data exfiltration; and full cleanup of data across execution to not create cross-user exfiltration concerns.

翻译：建议做成**密闭的（hermetic）**执行环境——不允许联网、不允许调用API，避免不受控的数据外泄；每次执行之间要彻底清理数据，避免产生跨用户的数据外泄隐患。

### 评估与网络边界

**评估**这一节只是一句指路，链接到ADK自己的Evaluate Agents文档，没有展开——跟本章之前读过的《Why evaluate agents》属于同一套体系，这里不重复。

**VPC-SC边界与网络控制**：如果agent跑在VPC-SC边界内，能保证所有API调用只会操作边界内的资源，降低数据外泄的可能性。文档也很诚实地指出这类边界控制的局限：

> However, identity and perimeters only provide coarse controls around agent actions. Tool-use guardrails mitigate such limitations, and give more power to agent developers to finely control which actions to allow.

翻译：身份和边界控制只能提供**粗粒度**的动作控制，工具使用护栏（也就是前面讲的in-tool guardrails/callback/plugin）能弥补这个局限，把"允许哪些具体动作"的控制权真正交给开发者精细掌控——**这句话点出了这篇文档的核心论证逻辑**：身份、沙箱、网络边界这些是"粗粒度兜底"，真正精细的控制必须靠工具层面的护栏来实现，两者缺一不可，跟Anthropic"环境层+模型层要互补"是同一个结论，只是Google这边多分了一层"工具层"出来单独强调。

## 4 其他安全风险：UI里的模型生成内容

这是文档单独拎出来的一条，之前几篇都没提过：**agent输出在浏览器里被渲染展示时要格外小心**——如果HTML或JS内容没有在UI里被正确转义，模型返回的文本可能被直接执行，导致数据外泄。文档举的例子：一次间接prompt注入可以诱导模型生成一个img标签，让浏览器把session内容发给第三方站点；或者构造出一个链接，一旦被点击就把数据发到外部站点。**正确的转义要确保模型生成的文本不会被浏览器当成代码来解释**——这本质上是经典的XSS（跨站脚本）风险，只是攻击载荷的来源从"用户输入"变成了"agent的模型输出"。

## 5 值得记的点

- **这篇是本章唯一给出可运行代码的文章**，"In-tool guardrails"那段代码把OpenAI《Safety in building agents》里"用结构化输出约束数据流"这条只停留在概念层面的建议，具体落地成了"policy由开发者确定性设置进Tool Context、工具执行前用这份policy校验模型生成的参数"这样一段真正能跑的逻辑，是理解"怎么在代码里实现输入校验"最具体的一份材料。
- **Callback vs Plugin的区分是一个很实用的工程决策框架**：单agent、一次性的校验用Callback；要在整个系统里统一生效、可复用的策略用Plugin，在runner层配置一次即可全局覆盖——这跟本章之前读到的"要不要为每个工具单独写权限判断"这类问题给出了一个清晰的选型标准。
- **"身份/沙箱/网络边界是粗粒度兜底，工具层护栏才是精细控制"这句话**，本质上是Anthropic"环境层+模型层要互补"结论的Google版本，但视角更细——Google把"工具"单独拎出来当成第三层，而不是笼统归进"环境层"，这跟ADK本身是一个以"工具"为核心构建单元的框架有关。
- **"UI里转义模型生成内容"是本章目前唯一提到的经典Web安全风险（XSS）跟agent安全的交叉点**——前面几篇全部聚焦在"agent会不会做坏事"，这条提醒的是"agent的输出被下游系统怎么处理，本身也是一块攻击面"，是一个容易被忽略的补充视角。

## 6 跟OWASP Top 10 for Agentic Applications的对应关系

逐条核对《OWASP Top 10 for Agentic Applications 2026 学习笔记.md》，这篇是本章目前打分最集中的一篇——五层防护里"身份与授权""Guardrails""沙箱化代码执行"三层，几乎是逐字对应OWASP给ASI02/03/05开出的防护建议原文，尤其是`In-tool guardrails`那段代码，本质就是OWASP给ASI02建议的"加一层Intent Gate式的策略执行中间件，校验意图和参数、强制schema"的具体实现。但这篇完全没碰供应链（ASI04）、记忆投毒（ASI06）、agent间通信（ASI07）、级联故障（ASI08）、人-agent信任滥用（ASI09）——这五条全部是0分，比前两篇覆盖的类目更少、但打满分的类目命中率更高。下表只保留评分>5分的类目。

| ASI类目 | 文中对应的具体机制 | 覆盖程度 | 评分（10=完整，0=未覆盖） |
| --- | --- | --- | --- |
| ASI01 Agent Goal Hijack | "风险来源"明确点名prompt注入、越狱、间接prompt注入；`Gemini as a Judge Plugin`专门评估用户输入、工具输入输出、agent响应有没有prompt注入/越狱迹象；`in-tool guardrails`即便目标已经被劫持，也能靠确定性policy拦下越权的具体动作 | 部分——有检测层（Judge Plugin）+containment层（policy校验）两条防线，但Judge Plugin本身是概率性的LLM判断，对"伪装成正常请求"的注入依然可能失手，跟auto-mode的局限是同一类 | 7 |
| ASI02 Tool Misuse and Exploitation | `in-tool guardrails`示例代码——policy规定只能查哪些表、只能`SELECT`，工具执行前强制校验模型生成的参数 | 完整——这几乎是OWASP给ASI02建议原文"Intent Gate式的策略执行中间件，校验意图和参数、强制schema"的字面翻译加代码实现，是全章匹配度最精确的一条 | 10 |
| ASI03 Identity and Privilege Abuse | "身份与授权"整节：Agent-Auth（agent自己的身份，需要额外加日志维系用户归因）vs User-Auth（用户自己的OAuth token，只能做用户自己能做的事，但scope往往比agent实际需要的更宽） | 完整——跟OWASP"根源是用户中心身份系统和agentic设计的架构性错位""归因空白"这两个说法几乎是同一件事的两种表述，是继contain-claude之后第二篇把这条讲透的文章 | 10 |
| ASI05 Unexpected Code Execution | "沙箱化代码执行"：密闭执行环境（不联网、不能调用API）、每次执行之间彻底清理数据防跨用户外泄 | 完整——直接对应OWASP"执行环境放进带严格网络限制的沙箱容器里跑""文件系统访问限制到专用目录"这几条防护建议 | 10 |
| ASI10 Rogue Agents | 风险分类里的"reward hacking"（追求非预期或代理性目标）直接对应ASI10核心定义；`in-tool guardrails`和评估/tracing能在偏移已经发生后拦下具体动作、或事后追溯agent的工具选择和路径 | 部分——跟auto-mode的deny-and-continue是同一个逻辑（不管背后动机、只看动作本身），但没有watchdog agent互相校验、加密身份认证这类更系统的机制 | 6 |

## 参考资料

- Google, *Safety and Security for AI Agents*, Agent Development Kit (ADK) Docs, https://adk.dev/safety/
