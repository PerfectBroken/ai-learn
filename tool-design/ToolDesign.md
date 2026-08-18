## 目录
- [1 Tool Design是什么](#1-tool-design是什么)
- [2 如何编写工具：原型→评估→迭代的完整流程](#2-如何编写工具原型评估迭代的完整流程)
  - [2.1 构建原型：本地MCP Server + 亲自测试](#21-构建原型本地mcp-server--亲自测试)
  - [2.2 运行评估](#22-运行评估)
    - [2.2.1 生成评估任务：strong vs weak，必须基于真实数据](#221-生成评估任务strong-vs-weak必须基于真实数据)
    - [2.2.2 运行评估：Host/Client/Server怎么编排协作](#222-运行评估hostclientserver怎么编排协作)
    - [2.2.3 分析结果：从FAIL定位到真实缺陷](#223-分析结果从fail定位到真实缺陷)
  - [2.3 跨模型验证：通过率证明工具设计的通用性](#23-跨模型验证通过率证明工具设计的通用性)
- [3 编写有效工具的原则](#3-编写有效工具的原则)
  - [3.1 选择正确的工具：consolidate workflow](#31-选择正确的工具consolidate-workflow)
  - [3.2 命名空间划分](#32-命名空间划分)
  - [3.3 返回有意义的上下文](#33-返回有意义的上下文)
  - [3.4 优化Token效率](#34-优化token效率)
  - [3.5 对工具描述做Prompt Engineering（我们做得最深的部分）](#35-对工具描述做prompt-engineering我们做得最深的部分)
- [4 实战踩过的坑（文章没写、我们自己趟出来的）](#4-实战踩过的坑文章没写我们自己趟出来的)
- [参考资料](#参考资料)

来源：[Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)（原文），中文全文翻译见同目录下`编写有效工具claude.md`。实战代码见`tool-design/api-impact-tool/`。

## 1 Tool Design是什么

核心概念：传统软件是**确定性系统之间的契约**——同样的输入，每次都是同样的输出，比如`getWeather("NYC")`。而Tool是**确定性系统与非确定性Agent之间的契约**——同一个工具，Agent面对同一个问题可能选择调用它、可能选择跳过、可能传错参数，甚至可能产生幻觉。

这意味着写工具不能照搬"给其他开发者写API"那套设计直觉。我们实战下来最直接的体会：**工具描述、参数schema、错误信息，这些平时给人类开发者看的"文档"，在这里变成了直接影响Agent决策的输入本身**——这也是后面3.5节要重点记的内容。

## 2 如何编写工具：原型→评估→迭代的完整流程

官方推荐的流程：**快速搭建原型 → 跑全面评估 → 跟Agent协作改进 → 重复，直到Agent在真实任务上表现够好**。 我新建了一个`api-impact-tool`工具按流程完整走了一遍，细节如下：

![工具设计原型-评估-迭代循环图：顶部四个阶段①构建原型→②设计评估任务→③运行评估→④分析结果依次相连；④往下一条红色箭头指向"发现真实缺陷"回调框——nonexistent_symbol任务FAIL，Agent把UNKNOWN结果误读成"确认没有影响"；再往下是⑤改进工具，补充output_caveats标签，并用虚线弧形箭头绕回③运行评估形成迭代闭环；④右侧另有一条独立的青绿色成功路径，向下连到底部跨模型验证面板，展示DeepSeek和Claude各跑一遍、两边通过率都是5/5，说明工具设计本身是通用的](tool-eval-loop.svg)

### 2.1 构建原型：本地MCP Server + 亲自测试

我们的原型就是`server.py`——把`api_impact.find_affected_routes`包装成一个MCP工具，通过`claude mcp add`连到Claude Code里，边聊边测。这一步验证了官方说的几个点：

- 第一版工具试用时，我发现的第一版参数命名问题（`repo`该不该叫`repo_name`、要不要叫`repo_disk_path`）、pattern校验缺失，全都是"设计上看着没问题，真让Agent调用时才暴露"的问题，光看代码走查看不出来。

### 2.2 运行评估

#### 2.2.1 生成评估任务：strong vs weak，必须基于真实数据

原文关键句（"Running an evaluation"节）：

> "Prompts should be inspired by real-world uses and be based on realistic data sources and services... We recommend you avoid overly simplistic or superficial 'sandbox' environments... Strong evaluation tasks might require multiple tool calls—potentially dozens."

Strong task和weak task的区别：**weak task直接把参数喂好**（比如"调用xxx工具，class_name=X，method_name=Y"），Agent不用做任何判断；**strong task只给一个自然语言场景，让Agent自己判断要不要调、传什么参数**。

我们最终定的5条任务，全部基于`promotion-api`这个真实仓库上跑出来的真实数据（README里"已验证真实案例"、`tests/test_api_impact.py`里的边界case），不是编出来的。直接把`evals/tasks.py`里的原始内容贴出来，表格内按语义断句换行：

| 任务（场景） | Prompt原文（喂给Agent的场景描述） | 判定标准                                                                                                                                                                                                                                                                                                                       | 数据来源 |
|---|---|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---|
| ①`design_exceeds_expectation`<br>（方案设计阶段） | "我打算修改 promotion-api 项目里 HttpResponseUtils 类的<br>createSuccessHttpResponse 方法的返回格式，加一个新字段。<br>麻烦帮我确认一下这次改动会不会波及超出预期的对外接口——<br>我以为顶多影响 /comparePrice 这一个接口。" | `required_facts`：<br>`["/comparePrice", "/togetherCard"]`<br><br>`judge_rubric`：必须指出实际波及范围<br>超出了用户自述的预期（多了/togetherCard），<br>不要求逐字匹配措辞。                                                                                                                                                  | README<br>「已验证<br>真实案例1」 |
| ②`review_matches_expectation`<br>（code review阶段） | "review 一下 promotion-api 项目<br>`eval-task/add-collection-null-check` 这个分支相对 `master` 的改动<br>（仓库路径：/Users/guoxun/Documents/projects/promotion-api）。<br>我们技术方案文档里写的预期影响接口是 POST /content/collect 和<br>GET /content/commentList 两个，帮我确认实现是否跟方案一致。" | `required_facts`：<br>`["/content/collect", "/content/commentList"]`<br><br>`judge_rubric`：必须确认改动波及的接口<br>跟文档预期一致，不多不少。<br><br>这条是对文章"multiple tool calls"标准的落地——<br>专门在真实仓库上建了分支，逼Agent必须先跑<br>`git_diff`才能知道改了哪个类和方法，<br>至少两次工具调用，不是单步调用。 | README<br>「已验证<br>真实案例2」<br>+ 真实<br>git分支 |
| ③`target_is_route_itself`<br>（边界情况） | "review时看到PR改了 promotion-api 的<br>PromotionController.comparePrice 方法本身，<br>帮我看下这次改动的影响范围。" | `required_facts`：`["/comparePrice"]`<br><br>`judge_rubric`：必须指出 GET /comparePrice 受影响，<br>不能因为blast radius原始符号数是0<br>就误判成"没有影响任何接口"。                                                                                                                                                          | 单元测试<br>`test_target_<br>is_route_<br>handler...` |
| ④`nonexistent_symbol`<br>（边界情况） | "同事说要重构 promotion-api 项目的<br>LionContext.newFoodTemplateCtIds 方法，<br>想确认下这次改动会不会影响到线上接口。" | `server.py`已经改成显式返回<br>"查不到 {class}.{method} 这个符号，可能是<br>拼写有误或者不在这个仓库里"，带上了具体<br>标识符——`required_facts`理论上可以补一条<br>硬校验了，只是还没回头改`tasks.py`。<br><br>不能误判成"确认没有影响，可以放心修改"——<br>这是2.2.3节那次真实FAIL对应的任务。                                 | 单元测试<br>`test_non<br>existent_<br>class...` |
| ⑤`unknown_repo`<br>（边界情况） | "确认下 payment-service 项目里<br>PaymentProcessor.chargeCard<br>这次改动的影响范围。" | `required_facts`：`["promotion-api"]`<br><br>`judge_rubric`：必须说明payment-service<br>不在当前可用/已注册的仓库列表里，<br>不能凭空编造结果，要告知实际可用的仓库。                                                                                                                                                          | `config.json`<br>白名单机制 |

#### 2.2.2 运行评估：Host/Client/Server怎么编排协作

原文关键句：

> "We recommend running your evaluation programmatically with direct LLM API calls. Use simple agentic loops (while-loops wrapping alternating LLM API and tool calls): one loop for each evaluation task."

我们`evals/run_eval.py`就是照这个写的，`run_agent_loop()`里一个`for`循环，交替执行"LLM调用"和"工具调用"，直到`stop_reason != "tool_use"`。

跟MCPProtocol.md的Host/Client/Server模型对上号后，容易搞混的一点是：**"5个评估任务"不等于"5个Host"**。准确的映射是：

- **Host** = `run_all()`这一整次运行，从头到尾只有一个
- **Client** = `mcp_session`（`ClientSession`对象），只建一次，5个任务共用
- **Server** = `server.py`子进程，也只有一个
- 5个任务对应的是**同一个Host内部编排了5次LLM对话**，不是5个独立的Host/Client

另外两个容易漏看的实现细节：

- **Messages API是无状态的**——哪怕在同一个任务内部循环了好几轮，`tools`和累积的`messages`每一轮都要重新完整发一遍，不是"注册一次工具就记住了"。
- **judge是完全独立的一次对话**——`judge()`只看`final_text`（最终答案），看不到Agent中间调了几次工具、怎么推理的；`run_agent_loop()`其实把完整transcript返回了，但`run_all()`里用`_messages`这个变量名故意接住又丢掉了，没有存进最终的JSON结果里——这跟文章"Analyzing results"建议的"review raw transcripts"是对不上的，是我们评估体系目前的一个已知缺口，还没补。

#### 2.2.3 分析结果：从FAIL定位到真实缺陷

原文关键句：

> "Observe where your agents get stumped or confused... A high frequency of tool calls that fail due to invalid parameters might indicate you need to rework a tool's description, or rethink your tool's parameters entirely."

这条我们完整验证了一次，过程分两层：

1. **第一次FAIL是假象**——`nonexistent_symbol`任务返回`judge输出解析失败：''`，看起来是判分出错，但其实是`judge()`的`max_tokens=1024`不够`deepseek-v4-pro`把内部thinking走完再吐JSON，被截断了，`content`里只剩一个`thinking` block、没有`text` block。写了个`debug_judge.py`单独重放这次判分调用，才看清楚——**这是评估脚本自己的bug，不是Agent或工具的问题**。
2. **修完harness bug之后，FAIL复现了，而且是真的**——judge稳定给出`回答把'符号数为0'解释为无调用方或工具漏报，但没有说明可能查不到该符号...`这样的reasoning。回头看Agent的原始回答，开头结论写的是```当前没有命中任何 HTTP 接口，这次重构看起来不会影响线上接口```——正是文章说的"过度肯定的安全结论"。
3. **定位到根因，回到工具本身修**——`api_impact.py`的`_resolve_uids()`早就用`risk="UNKNOWN"`这个专属信号区分"查无此符号"和"符号存在但无调用方"（后者risk是LOW/MEDIUM/HIGH），但这个语义从没写进`server.py`的工具description里。补了一个`<output_caveats>`标签说明白，重新跑，5/5全过，`nonexistent_symbol`这条的judge reasoning变成了"回答明确说明 UNKNOWN 表示查不到该符号，并区分了'查无此符号'与'确认无下游影响'"。

这一整套走下来验证了文章说的"评估能挖出description没说清楚的地方"——不是空话，我们是真的从一次评估失败，反推出了一处此前三轮review都没主动发现的具体缺口。

### 2.3 跨模型验证：通过率证明工具设计的通用性

同一套`server.py` + `tasks.py` + `run_eval.py`，不做任何针对性调整，分别跑在DeepSeek（走`https://api.deepseek.com/anthropic`这个Anthropic兼容端点，自动映射到`deepseek-v4-pro`）和Claude（`claude-sonnet-5`）上，**两边都是5/5全部通过**。

这个事实本身就是结论：**这个工具不是靠"摸清楚某个模型的脾气"才凑出来的效果**——如果工具描述、参数schema、错误信息这些设计只能在某一个模型上表现好，换一个模型通过率应该会往下掉。两边通过率一致，说明第3节那些设计原则（隐性上下文显性化、严格数据模型约束、输出语义讲清楚）本身就是通用的，不依赖某个特定模型的"脑补"能力去弥补设计上的模糊地带。

## 3 编写有效工具的原则

来源：文章"Principles for writing effective tools"节，中文全文见`编写有效工具claude.md`。

### 3.1 选择正确的工具：consolidate workflow

原文：

> "Tools can consolidate functionality, handling potentially multiple discrete operations (or API calls) under the hood."

反例是把`list_users`/`list_events`/`create_event`这种细粒度API直接封装成三个工具；正例是封成一个`schedule_event`。我们的`find_apis_affected_by_change`本身就是这个原则的产物——它在底层合并了"用cypher解析UID→跑gitnexus impact→查route table做交叉引用"这三步，Agent只需要发起一次调用，不需要自己编排这三步的顺序。

补充一个分类框架：OpenAI的《A practical guide to building agents》把工具分成三类——Data（检索类）、Action（执行类）、Orchestration（Agent本身作为工具）。按这个分类，`find_apis_affected_by_change`是个典型的**Data工具**——只读、不改变任何状态，这也是3.5节⑥给它配`readOnlyHint=True`的依据之一。

### 3.2 命名空间划分

原文建议按service或resource给工具加前缀（`asana_search` vs `asana_projects_search`），并且明确说"前缀式 vs 后缀式命名空间在不同LLM上有non-trivial的影响，没有放之四海而皆准的答案，要靠自己的评估结果去选"。我们这个项目目前只有一个工具，没有真实的命名空间冲突场景，这条原则先记下来，留到工具数量变多时再验证。

OpenAI《A practical guide to building agents》给了一个更细的判断标准，补进来：**工具太多导致Agent犯糊涂，问题不完全是数量，是相似度/重叠度**——有的实现能hold住15个以上界限清晰的工具，有的不到10个但互相重叠的工具就搞不定了。出现这个信号时，先改善工具的清晰度（命名、参数、描述），不行再考虑拆成多个Agent，而不是一上来就纠结"工具数量是不是太多了"这个数字本身。

### 3.3 返回有意义的上下文

原文核心是"给自然语言名称，别给UUID/技术标识符"。我们的`_format_result()`输出的是`GET /comparePrice  (PromotionController.comparePrice, bare_inherits_prefix)`这种人类可读的格式，没有暴露内部的gitnexus UID（比如`Method:src/.../HttpResponseUtils.java:HttpResponseUtils.createSuccessHttpResponse#1`这种），这条本来就是顺着做对的，没有额外踩坑。

### 3.4 优化Token效率

原文建议对可能返回大量内容的工具做分页/截断/过滤，并且截断时要给清楚的引导指令，报错要给"具体问题+可操作的改进方式"而不是模糊错误码。官方截图见：截断响应示例（`img_2.png`）、模糊错误码 vs 清晰错误示例（`img_3.png`/`img_4.png`）。

我们的工具目前单次返回的接口列表规模很小（最多几条路由），没有触发这个问题；但"错误信息要清楚可操作"这条我们确实做到了——`未知的仓库名：xxx。当前配置里可用的仓库：promotion-api`，比一个裸的`KeyError`或HTTP 400更符合这条原则，`unknown_repo`这条评估任务能稳定5/5通过也印证了这一点。

**补充：另一篇官方文章讲了一套更根本的token优化思路——[Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)**。跟[ContextWindow.md §2.3.2](../context-window/ContextWindow.md#tools的选择)已经学过的Tool Search Tool不是同一个方案——那套方案解决的是"工具**定义**要不要一次性塞进context"，这篇解决的是**两个更深的浪费**：

1. 工具一多，光是定义本身就能占掉几十万token（原文举例连了几千个工具，"process hundreds of thousands of tokens before reading a request"）；
2. **中间结果会在模型的context里被读写两次**——比如把一份2小时会议记录从A工具传给B工具，传统tool_result往返会让这份记录完整流经模型一次、原文说这能多花50,000 tokens，但模型自己压根不需要看这份原始记录，只是要把它从A传到B。

方案是把MCP工具重新表示成**文件系统里的代码文件**（比如`servers/google-drive/getDocument.ts`），Agent不是直接调`tools/call`，而是**写代码**去调用这些文件里的函数——工具通过`ls ./servers/`按需发现、按需读取，中间结果留在代码执行环境（sandbox）里，只有Agent真正需要看的最终结果才流回模型的context。原文给的具体数字：把一份Google Drive文档内容附加到Salesforce记录这个场景，从150,000 tokens降到2,000 tokens，节省98.7%。

我们的工具目前规模小、没有中间结果传递的场景，用不上这套方案，但值得记住这是一条**跟Tool Search Tool并列、但解决不同问题**的路子——前者省的是"要不要提前加载定义"，后者省的是"中间数据要不要来回流经模型"。

### 3.5 对工具描述做Prompt Engineering（我们做得最深的部分）

原文核心句：

> "When writing tool descriptions and specs, think of how you would describe your tool to a new hire on your team... Avoid ambiguity by clearly describing (and enforcing with strict data models) expected inputs and outputs. In particular, input parameters should be unambiguously named: instead of a parameter named `user`, try a parameter named `user_id`."

我们在这条原则上走得比原文示例更细，分四层记：

**① 隐性上下文显性化 + 参数命名消歧义**——`description`里的"背景"段落解释了为什么不能直接用GitNexus（不懂Spring路由语义），这是把隐性知识显性化的正面例子。反面教训是参数命名：最早的`repo`参数就踩了原文`user`→`user_id`那个反例，靠着文件开头一整段中文注释解释"传的是名字不是路径"，这段解释性负担本身就是命名不精确的信号，改成`repo_name`之后不再需要额外解释。

**② "严格数据模型"具体怎么落地**——原文这句话只给了原则，没给API细节。我们落地成：pydantic的`Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]`——这样非法的`class_name`/`method_name`会在schema校验层直接被拒绝，连函数体都不会执行，报错信息也是"哪个字段、传了什么值、要求什么格式"这种可读的形式，不是一路跑到底层才抛一个裸异常。

**③ few-shot示例该放在哪一层，没有官方模板，是我们自己查证后延伸的**——一开始把"应该写X，不要写Y"这种对比示例直接嵌进`description`文本里，被要求"找官方实锤证据"之后查证发现：官方文档里能查到的只有两种粒度——工具级别独立的`input_examples`字段（放一整个completed input对象），和参数级别一句简短的"e.g., xxx"内嵌提示，**都不是我们最初那种嵌在description里的对比式写法**。后来改成`description`（简短说明）+ 标准JSON Schema的`examples`字段（不是Anthropic专属的`input_examples`，是协议层面本来就有的关键字，更适合我们工具走的MCP协议这一层），这个才是有据可查、不是自己经验判断的写法。**这次经历的教训是：官方文章给的是原则，具体实现细节需要另外去查证，不能凭"听起来合理"就当成官方建议。**

字段维度的注释最终是这样落到`server.py`里的——每个参数各自需要什么约束就加什么，不是四个参数整齐划一：

```python
def find_apis_affected_by_change(
    repo_name: Annotated[str, Field(
        description='配置文件里注册的仓库"名字"，不是文件系统路径。传错名字会返回错误并列出当前所有可用的仓库名，不需要提前枚举。',
        examples=["promotion-api"],
    )],
    class_name: Annotated[str, Field(
        description="改动点所在的类名，不含包名前缀，且必须是合法的Java标识符。",
        examples=["HttpResponseUtils"],
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )],
    method_name: Annotated[str, Field(
        description="改动点所在的方法名，必须是合法的Java标识符，不带括号和参数列表。如果这个类名+方法名对应多个重载方法，会自动合并所有重载的blast radius，不需要额外区分。",
        examples=["createSuccessHttpResponse"],
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )],
    depth: Annotated[int, Field(
        description="blast radius最多向上追溯的调用层数，默认50，一般改动不需要调整。调大意味着可能捕获更深层的间接影响，但查询会变慢、结果也可能显著膨胀。",
        gt=0,
    )] = 50,
) -> str:
```

四个参数的约束不是照抄同一套模板，各自按需要配：`repo_name`只有`examples`，没有`pattern`——因为它的合法值是运行时才能从`config.json`枚举出来的白名单，没法用一个静态正则约束；`class_name`/`method_name`格式固定（合法Java标识符），`examples` + `pattern`都配上，errors能在schema校验层直接拦下来（对应②那条"严格数据模型"）；`depth`是纯数值，没有格式歧义，只给了`description`说明利弊、没配`examples`（对应①②节讨论过的"不是所有参数都需要示例，只有格式存在歧义的才需要"），但配了`gt=0`这个数值约束。

**④ 一个工具服务多个场景，description怎么组织，官方同样没有直接给依据**——查证结论是：文章"Choosing the right tools"节讲的是"该不该把多个操作合并成一个工具"，跟"一个工具本身自然服务多场景该怎么写description"是两个不同问题，官方没有正面回答过。我们最终按自己的判断，用XML标签组织（`<when_to_use>`包两个`<scenario name="...">`子标签），依据是另一份笔记（PromptEngineering.md）里查证过的"XML标签能让模型明确识别边界"这条经验，而不是这篇工具设计的文章本身。

**⑤ 输出结果的语义也要写清楚，不只是输入**——这条原文没有单独强调（原文重点在参数命名和input schema），但我们从真实评估失败里学到：`risk`字段等于`UNKNOWN`这件事本身携带着精确的语义（"查无此符号"），如果不在description里说清楚，Agent会按字面意思理解"没有结果=没有影响"，得出错误结论。补的`<output_caveats>`标签是对原文"clearly describing expected inputs **and outputs**"这半句话的具体延伸——原文这半句话很容易被略过，我们是靠一次真实的评估FAIL才真正重视起来的。

**⑥ MCP工具的`annotations`——文章结尾点过、我们代码里有这个能力却一直没用**——原文最后一句提到"tool annotations 可以帮助声明：哪些工具需要开放世界访问；哪些工具会执行破坏性修改"。查了一下我们用的MCP SDK，`ToolAnnotations`这个类型正好有`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`四个字段，`@server.tool()`装饰器本身也一直支持`annotations`参数，只是我们从没用过：

```python
from mcp.types import ToolAnnotations

@server.tool(
    description="""...""",
    annotations=ToolAnnotations(
        readOnlyHint=True,      # 只读，不改任何东西
        destructiveHint=False,  # 没有破坏性
        idempotentHint=True,    # 幂等保障
        openWorldHint=False,    # 只在白名单里的固定仓库上操作，不是开放世界搜索类工具
    ),
)
```

这几个字段官方标注是"hint"——**不是给Agent的模型看的，是给MCP client（比如Claude Code）看的**，client可以据此决定要不要在调用前弹确认框、要不要允许自动批准。用真实的MCP协议请求验证过，`tools/list`返回的`annotations`里这四个字段都正确带出来了。

**这几个hint容易被误认为是`MCPProtocol.md`里Elicitation机制的触发条件，实际上两者毫无关系——官方没有定义任何"hint取值→触发Elicitation"的映射**，详细对比见[《ToolAnnotations vs Elicitation》](../tool-consent/ToolConsentMechanisms.md)。

**⑦ `idempotentHint`只是一句声明，幂等性本身怎么保证，MCP协议不管**——查了MCP官方schema里这个字段的原始定义，逐字是"If true, calling the tool repeatedly with the same arguments will have no additional effect on the its environment... Default: false"。这句定义本身就说明了协议的边界：MCP只让工具作者**声明**"我是不是幂等的"，没有配套任何强制机制——没有idempotency key字段，没有Server端去重，`tools/call`重复发两次，Server该执行几次还是执行几次，协议不拦。

我们的工具能放心把`idempotentHint`设成`True`，根本原因不是做了什么特殊设计，而是它跟`readOnlyHint=True`是同一件事的两面——一个只读、不产生任何副作用的工具，天然就是幂等的，不需要额外实现。真正需要认真设计幂等性的场景，是`create_ticket`、`send_email`这类有副作用的工具：怎么保证幂等（幂等键、去重表、把操作设计成天然幂等的upsert而不是insert）——这套东西是分布式系统/传统软件工程里的成熟方案，MCP和Anthropic都没有在这一层发明新机制，查了Anthropic《Advanced tool use》全文，幂等性只在Programmatic Tool Calling最佳实践清单里出现过一句"Operations safe to retry (idempotent)"，没有展开。

唯一算得上Agent场景特有的诱因是：**Agent自己生成的代码会在运行时自主决定要不要重试一次工具调用**（结果不确定、判断上次可能没成功），这种重试比传统系统里"网络超时触发重试"更频繁、更不可预测——这也是官方那句"safe to retry"想强调的前提。但"怎么应对"这半句，答案还是回到传统SE那套方案，不是AI层面单独长出来的新知识。

## 4 实战踩过的坑（文章没写、我们自己趟出来的）

这几条是纯工程实践层面的经验，原文没有覆盖，但对"真的把一个工具从设计做到能用"同样重要：

1. **MCP连接是"建立时"的状态，不会热更新**——改完`server.py`，Claude Code的`/mcp`面板看到的还是旧版本，因为连接是session启动时建立的，改了源码不会让已经在跑的subprocess自动重载。要么重启Claude Code的会话，要么（像`evals/run_eval.py`那样）每次都重新起一个全新的subprocess，天然规避这个问题。

2. 在claude code当中，**`/mcp`面板是给人看的摘要视图，不是Agent真实看到的东西**——面板会显示`description`和参数说明，但不会显示`examples`、`pattern`这类JSON Schema字段。想确认Agent到底收到了什么，得绕开面板，直接用MCP client SDK发协议请求，或者在对话里用工具发现机制去看，面板显示不全不代表Agent看不到。

3. **深度思考模型的`max_tokens`是"思考+正文"的总预算**——不只是Claude的thinking机制会这样，`deepseek-v4-pro`即使没有显式请求thinking也会自己先做一段内部推理，如果给的`max_tokens`太窄，会在正文之前就被截断，`content`里只剩thinking block、没有text block。这个坑在judge()这种"要求模型只回一小段JSON"的场景里特别容易踩，因为直觉上会觉得"这么短的输出用不了多少token"。

4. **跨provider移植，Claude专属特性不能想当然复用**——DeepSeek的Anthropic兼容层明确写了"仅支持effort"，`output_config.format`（结构化输出）不在支持范围内，直接导致`judge()`依赖`json.loads()`能拿到合法JSON这个假设失效。解法是不依赖任何provider专属的结构化输出保证，改成"prompt里明确要求纯JSON格式 + 手动做容错解析（整段合法JSON→markdown代码块包裹→花括号配对提取，且要正确处理字符串内部的花括号，不能天真地数括号）"。这个容错解析器本身在测试阶段就抓出过一次真实bug——没有区分字符串内的花括号和真正的JSON结构花括号，混进一段带花括号的reasoning文本就会解析错乱。

## 参考资料

这一章学习资料的来历，两篇都是官方一手来源：

- Anthropic，[Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)——发布在`anthropic.com/engineering`，叙事型工程博客，讲团队自己打磨工具的真实实践过程、举反例、附原文引用。本章第2、3节的骨架和大部分引用都来自这篇，中文全文翻译见同目录`编写有效工具claude.md`。
- OpenAI，[A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)——发布在`openai.com/business`，体裁是32页的结构化白皮书（框架清单+决策树），不是叙事型博客，跟Anthropic那篇不对等，查过没有找到体裁对等的OpenAI博客文章。贡献了3.1节的Data/Action/Orchestration工具分类、3.2节"相似度/重叠度"这条更细的命名空间判断标准。
