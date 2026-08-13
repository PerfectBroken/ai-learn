## 目录
- [1 Tool Calling是什么](#1-tool-calling是什么)
  - [1.1 解决了什么问题](#11-解决了什么问题)
- [2 API层对比：四家的tools参数长什么样](#2-api层对比四家的tools参数长什么样)
  - [2.1 统一对比表](#21-统一对比表)
  - [2.2 真实写法示例](#22-真实写法示例)
  - [2.3 tool_choice完整取值对比](#23-tool_choice完整取值对比)
  - [2.4 strict模式：schema强一致性](#24-strict模式schema强一致性)
  - [2.5 并行工具调用：一次回复能不能带多个工具调用](#25-并行工具调用一次回复能不能带多个工具调用)
  - [2.6 `tool_result`里有没有专门的错误字段](#26-tool_result里有没有专门的错误字段)
- [3 底层机制：从JSON到语法约束解码](#3-底层机制从json到语法约束解码)
  - [3.1 时序图：JSON和模型原生格式怎么互转](#31-时序图json和模型原生格式怎么互转)
  - [3.2 强制调用的底层机制：语法约束解码](#32-强制调用的底层机制语法约束解码)
  - [3.3 掩码到底管了多少：固定骨架 vs 模型自由发挥](#33-掩码到底管了多少固定骨架-vs-模型自由发挥)
  - [3.4 strict模式的底层机制](#34-strict模式的底层机制)
  - [3.5 并行调用是后处理过滤，不是掩码拦截](#35-并行调用是后处理过滤不是掩码拦截)
- [4 章节定位](#4-章节定位)

## 1 Tool Calling是什么

**一句话：让LLM不再只输出"一段文字"，而是能输出一个结构化的"调用请求"（要调哪个工具、传什么参数），但LLM自己不执行——真正的执行是调用方的代码来做，执行完再把结果喂回给模型继续对话。**

早期LLM只会输出纯文本，如果想让它"查一下今天天气"这种需要触发外部动作的任务，唯一办法是靠prompt硬引导模型输出一段看起来像JSON的文字，再自己写正则表达式去从这堆自由文本里抠数据出来——这个做法很脆弱：模型可能多写一句客套话把JSON包裹坏了，可能字段名拼错，格式稍微不对解析就崩。

OpenAI在**2023年6月13日**的官方博客里正式在API里加入了这个能力（当时的参数名是`functions`，后来演进成`tools`），这是这个能力第一次变成官方支持的API原生机制，而不是靠prompt硬凑——原文描述的机制是：开发者传入一份或多份函数的JSON Schema，模型（GPT-3.5/GPT-4）会判断要不要调用、返回一段描述该调用哪个函数的JSON，这正是后来ChatGPT插件生态的底层机制。（"模型是否专门为此做过微调训练"这一点，查了官方博客原文及多个转述来源，没有找到可确认的原话依据，故不作为既定事实写入。）

来源：[Function calling and other API updates（OpenAI官方博客）](https://openai.com/index/function-calling-and-other-api-updates/)

### 1.1 解决了什么问题

- **可靠性**：模型直接吐出符合schema的结构化参数，不再需要脆弱的文本解析——这背后用到的正是[采样参数](../sampling-parameters/SamplingParameters.md)里提到的约束解码思路，模型在生成阶段就被强制只能吐出合法结构，而不是生成完自由文本再事后校验。
- **让LLM能操作外部世界**：查数据库、发邮件、执行代码——这是agent能做实际动作而不只是"聊天"的入口。
- **能力声明变成结构化契约**：开发者清楚声明"这个模型能用哪些工具、每个工具的参数要求是什么"，模型自己在推理时判断该不该调、调哪个——决策权从"纯靠prompt字里行间猜"变成了"结构化声明+模型自主判断"。

## 2 API层对比：四家的tools参数长什么样

这一章是"参考手册"型的内容——写代码时要查"这个参数怎么传、各家什么值"，直接来这一节。均查证自各家官方文档。底层为什么会这样实现，见[第3节](#3-底层机制从json到语法约束解码)。

（对比对象：Claude Messages API、OpenAI Chat Completions API、Kimi(Moonshot)API、DeepSeek API。OpenAI现主推的Responses API出参结构不同，单独在下方说明，不占用统一表格的行）

### 2.1 统一对比表

| 模型 | 入参字段名 | 入参工具结构 | schema字段名 | 默认tool_choice | 出参触发标志 | 调用信息放在哪 | 单次调用的字段 | 参数字段类型 | 结果回传角色 | 对应原调用的字段 |
|---|---|---|---|---|---|---|---|---|---|---|
| **Claude** | `tools` | **扁平**——`name`/`description`/`input_schema`直接摆在工具对象上 | `input_schema` | `{"type":"auto"}`，模型每轮自主判断（官方文档明确写明） | `stop_reason: "tool_use"` | `content`数组里的`tool_use`块 | `type`/`id`/`name`/`input` | **已解析好的JSON对象**，可直接用 | `role: "user"`（结果包在`tool_result`块里，不是独立角色） | `tool_use_id` |
| **OpenAI** | `tools` | **嵌套**——外层`type:"function"`，定义包在`function`字段里 | `function.parameters` | `"auto"`（默认，模型自主判断） | `finish_reason: "tool_calls"` | `message.tool_calls`数组 | `id`/`type:"function"`/`function.name`/`function.arguments` | **JSON字符串**，需自己`json.loads()`解析 | 专门的`role: "tool"` | `tool_call_id` |
| **Kimi** | `tools` | 同OpenAI（官方文档明确标注兼容OpenAI格式） | `function.parameters` | 文档未显式声明默认值，示例行为推断为自主判断 | `finish_reason: "tool_calls"` | `message.tool_calls`数组 | `id`/`type:"function"`/`function.name`/`function.arguments` | **JSON字符串**，需自己解析 | `role: "tool"` | `tool_call_id` |
| **DeepSeek** | `tools` | 同OpenAI（官方文档明确标注兼容OpenAI格式） | `function.parameters` | 文档未显式声明默认值 | 返回带`tool_calls`的message | `message.tool_calls`数组 | `id`/`function.name`/`function.arguments` | **JSON字符串**，需自己解析 | `role: "tool"` | `tool_call_id` |

**OpenAI Responses API的例外**（官方现主推的API，出参结构和上表的Chat Completions版本不同，Kimi/DeepSeek照抄的是Chat Completions版本，不是这套）：触发标志变成`output`数组里出现`type:"function_call"`的条目；调用信息不嵌套在message里，直接是`output`数组本身；单次调用字段是`type:"function_call"`/`id`/`call_id`/`name`/`arguments`；结果回传没有"角色"概念，是在`input`里追加一个`type:"function_call_output"`条目，对应字段叫`call_id`。入参结构（`tools`/嵌套/`function.parameters`）两套API是一致的，只有出参和结果回传不同。

### 2.2 真实写法示例

**Claude入参**（扁平结构）：
```json
{
  "name": "get_weather",
  "description": "Get the current weather for a given location.",
  "input_schema": {
    "type": "object",
    "properties": {"location": {"type": "string"}},
    "required": ["location"]
  }
}
```

**OpenAI/Kimi/DeepSeek入参**（三家完全一致，嵌套结构）：
```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get the current weather for a given location.",
    "parameters": {
      "type": "object",
      "properties": {"location": {"type": "string"}},
      "required": ["location"]
    }
  }
}
```

**Claude出参**（`input`已经是解析好的对象）：
```json
{"type": "tool_use", "id": "toolu_01A09q90qw90lq917835lq9", "name": "get_weather", "input": {"location": "San Francisco, CA"}}
```

**Kimi出参**（照抄OpenAI Chat Completions格式，`arguments`是字符串）：
```json
{"id": "search:0", "type": "function", "function": {"name": "search", "arguments": "{\"query\": \"Context Caching\"}"}}
```

来源：[Tool use with Claude](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview)、[OpenAI Function calling指南](https://developers.openai.com/api/docs/guides/function-calling)、[Kimi API Tool Calls文档](https://platform.kimi.ai/docs/guide/use-kimi-api-to-complete-tool-calls)、[DeepSeek Tool Calls文档](https://api-docs.deepseek.com/guides/tool_calls/)。

### 2.3 tool_choice完整取值对比

`tool_choice`是`tools`参数的兄弟参数，控制"模型能不能调用工具、要不要强制调用"。均查证自各家官方文档，Kimi文档没有正式枚举取值（代码示例里出现过一次`"auto"`，没有正文说明），故不列入对比。

| 模型 | 自主判断 | 必须调用，不限定哪个 | 强制指定某一个 | 禁止调用 | 独有能力 |
|---|---|---|---|---|---|
| **Claude** | `auto`（有tools时默认） | `any` | `{"type":"tool","name":"..."}` | `none`（无tools时默认） | 改`tool_choice`会让prompt cache失效；`any`/`tool`会prefill assistant消息，模型不先说话解释、直接吐工具调用 |
| **OpenAI** | `"auto"` | `"required"` | `{"type":"function","name":"..."}` | `"none"` | `allowed_tools`——临时圈定一个子集允许调用，官方原文说明是为了保住prompt cache，不用把其他工具从`tools`数组里删掉重传 |
| **DeepSeek** | `auto`（有tools时默认） | `required` | `{"type":"function","function":{"name":"..."}}` | `none`（默认） | 官方参数定义措辞和OpenAI几乎逐字一致，再次印证"API格式兼容OpenAI" |

来源：[Claude Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)、[OpenAI Function calling指南](https://developers.openai.com/api/docs/guides/function-calling)、[DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。

`tool_choice`不同取值背后，约束生效的时机也不一样（`auto`要等触发信号，`required`从第一个token就锁死）——这是实现机制层面的事，见[3.2节](#32-强制调用的底层机制语法约束解码)。

### 2.4 strict模式：schema强一致性

`strict:true`是工具定义里的一个字段，是模型生成时的行为保证，不是架构设计问题。

#### strict是什么：和tool_choice的区别

**`tool_choice`回答的是"要不要调用工具、调哪一个"；`strict`回答的是"已经确定要调用某个工具了，它的参数一定完全符合我定义的schema吗"。** 前者管"调用决策"，后者管"参数质量"，两者是完全不同维度，互不相关，可以任意组合。

即便`tool_choice`已经决定了"必须调用`get_weather`"，**参数部分具体填得对不对，默认情况下不是被硬性约束的**——schema是以"这是可用的函数，格式如下"这种**文字说明**的形式塞进prompt里的（Claude的tool use system prompt模板就是这么写的），模型是照着这段说明书"尽量写对"，不是被语法规则锁死。Claude官方文档原话："Without strict mode, Claude might return incompatible types (`"2"` instead of `2`) or omit required fields"——没开strict，模型完全可能把数字类型的参数写成字符串`"2"`，或漏填一个必填字段。

打开`strict:true`之后，参数部分才会被**真正编译进语法约束**（具体机制见[3.4节](#34-strict模式的底层机制)）——类型对不对、必填字段全不全、有没有多余字段，全部变成数学上排除掉不合法候选，不再是"参考着写"。Claude官方给的例子很直接：不开strict，模型可能返回`passengers: "two"`或`passengers: "2"`；开了`strict:true`，返回的**永远**是`passengers: 2`。

两者可以叠加：`tool_choice=required` + 每个工具都设`strict:true` = "这一轮必须调用某个工具（不限定哪个），而且不管最终调的是哪个，参数一定完美符合schema"——覆盖了工具调用从"要不要发生"到"发生的质量怎么样"的完整链条。

均查证自各家官方文档：

| 模型 | 字段位置 | 底层机制（官方原话） | Schema强制规则 | 特殊限制 |
|---|---|---|---|---|
| **Claude** | 工具定义**顶层**（跟`name`/`description`/`input_schema`平级） | 官方原文明确写"a technique called **grammar-constrained sampling**" | 官方示例统一配`additionalProperties: false` | **HIPAA/PHI警告**：schema会被单独缓存最长24小时，这份缓存不受message content那套PHI保护覆盖，官方原话明确说不要把PHI放进schema的字段名、enum值、pattern正则里 |
| **OpenAI** | 嵌套在`function`对象里（跟`name`/`description`/`parameters`平级） | 官方原文"strict mode works by leveraging our structured outputs feature" | **三条强制规则**：①`additionalProperties`必须设成`false`；②`properties`里**所有**字段都要写进`required`；③可选字段不能真的"可选"，要用`"type":["string","null"]`这种写法表示 | 首次请求如果schema经常变，可能因为要重新编译语法而首次延迟变高；细粒度schema特性不是全支持 |
| **DeepSeek** | 同OpenAI，嵌套在`function`对象里 | 官方定位是对标OpenAI的structured outputs，同样靠约束解码保证格式 | 同OpenAI三条规则（`additionalProperties:false`+全部required）；支持的类型明确列了`string/number/integer/boolean/object/array/enum/anyOf` | **必须切到`https://api.deepseek.com/beta`这个beta端点才能用**；查到一个真实GitHub issue"DeepSeek API Strict Mode Returns Malformed JSON in Function Call Arguments with Schema"，说明这功能在实践中不是100%没坑 |
| **Kimi** | 查不到strict模式相关内容 | — | — | — |

**三个最值得记的点**：

1. **Claude官方文档直接把strict模式和约束解码钉死在一起**——"grammar-constrained sampling"这个术语，和3.2/3.4节查vLLM/xgrammar源码时看到的机制是同一个东西，不是碰巧撞名。
2. **"可选字段用`type:["string","null"]`表示"这条规则很反直觉**——strict模式要求`required`必须包含**所有**属性名，想让某个字段"可以不填"，没法用"不写进required"来表示，只能让这个字段的类型本身允许是`null`，模型判断不需要就填`null`，而不是省略这个key。这是实战里容易踩的坑。
3. **Claude的HIPAA/PHI警告是个很具体的安全提醒**——schema定义会被单独缓存，缓存的保护级别比对话内容低，做医疗、金融这类合规场景的agent时，不能把敏感信息写进字段名/enum/pattern里。

来源：[Claude Strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)、[OpenAI Function calling指南](https://developers.openai.com/api/docs/guides/function-calling)、DeepSeek官方文档与[GitHub issue #1069](https://github.com/deepseek-ai/DeepSeek-V3/issues/1069)。

**strict保证的是schema conformance（结构/类型对不对），不是语义正确性（内容靠不靠谱）**——Claude官方原话是"correctly-**typed** arguments"，不是"correctly arguments"。`location`字段是`string`类型，strict能保证填进去的一定是合法字符串，但不保证这个字符串是个真实存在的地名。这是strict这个机制从设计上就管不了的范畴，不是实现缺陷，所以即便开了strict，agent代码层面保留一层业务校验依然值得（这属于Layer 2"错误语义设计"的范畴，这里不展开）。

### 2.5 并行工具调用：一次回复能不能带多个工具调用

`tool_use`/`tool_calls`这个数组里能不能出现不止一个元素，是纯API层面的事实，加一个能开关它的参数——跟2.1节"调用信息放在哪个数组"是同一件事的延伸。

| 模型 | 默认状态 | 怎么关闭/控制 | 执行顺序有没有规定 | 特殊细节 |
|---|---|---|---|---|
| **Claude** | 默认开启，一次回复可能带多个`tool_use`块 | `disable_parallel_tool_use: true`——嵌套在`tool_choice`对象里，不是顶层参数；效果取决于`tool_choice`类型：`auto`下变成"最多1次调用（仍可直接用文字回答）"，`any`/`tool`下变成"恰好1次调用（强制且唯一）" | 官方明确说不规定，并发还是顺序执行由开发者自己决定 | 每个`tool_use`都必须对应一个`tool_result`，全部放进下一条`user`消息、排在任何文本之前；若某个调用没真的执行（如顺序执行时前一个失败），也要给它补一个`tool_result`，标`is_error:true`并说明未执行 |
| **OpenAI** | 未查到逐字确认的默认值原话（此前调研查到"新模型默认开启"，未重新核实到官方原文，标注置信度） | 顶层参数`parallel_tool_calls: false`，官方原话"ensures exactly zero or one tool is called" | 未查到官方对执行顺序的明确规定 | 微调模型若一轮并行调用了多个函数，那一轮的strict模式会被自动禁用（官方原话确认） |
| **DeepSeek** | 支持并行，V4 Pro/Flash单次最多**128个**并行工具调用（二手来源印证，非官方逐字原文） | 未查到能关闭/控制的参数 | 未查到官方说明 | — |
| **Kimi** | 默认支持，官方原文"没有依赖关系的tool_calls会倾向于并行调用" | 未查到能关闭的参数 | 未查到官方说明 | — |

`parallel_tool_calls`这类开关具体是怎么实现的（是掩码拦截还是后处理过滤），见[3.5节](#35-并行调用是后处理过滤不是掩码拦截)。

**这个参数的主要作用，不在省钱，在省心。** 既然过滤发生在生成之后，用不用这个参数都不影响生成成本——该花的token已经花了。它真正的价值是**把"必须记得过滤"这个责任从Agent代码里挪到了服务端**：如果自己在Agent层过滤，得自己保证"过滤后的结果"和"存进对话历史、传回下一轮的内容"严格一致，多一处自己维护的逻辑，就多一处可能漏掉的边界情况（比如某个代码分支忘了过滤，把好几个工具调用全存进了历史，下一轮请求平白多花几倍token，还牵扯到之前讲过的前缀缓存问题）。参数由服务端保证之后，Agent代码收到的响应本来就只有一个，不存在"忘记过滤"这类问题。

来源：[Claude Parallel tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use)、[OpenAI Function calling指南](https://developers.openai.com/api/docs/guides/function-calling)。

### 2.6 `tool_result`里有没有专门的错误字段

工具执行失败了，怎么把这个错误告诉模型？这是数据结构本身的一个字段，和2.1节"结果回传"（角色名/对应字段名）是同一类知识，补在这里。

| 模型 | 有没有专门的错误字段 | 格式建议 | 特殊行为 |
|---|---|---|---|
| **Claude** | **有**——`tool_result`块里的`is_error: true`（可选字段，跟`content`平级） | 官方明确建议：**写有信息量的错误信息**，比如`"Rate limit exceeded. Retry after 60 seconds."`，不要写笼统的`"failed"`——原文说这样能让Claude"recover or adapt without guessing" | 如果Claude的调用本身不合法（比如缺了必填参数），**会自动重试2-3次**、自己补全缺失信息，才会放弃向用户道歉；官方还提示这类"调用本身不合法"的问题，用`strict:true`能从根源上消除 |
| **OpenAI** | **没有专门字段**——错误就是塞进`output`/`content`字段的一个普通字符串，格式完全自定义（JSON、错误码、纯文本都行），官方原话"the model will interpret that string as needed" | 官方建议即便用了Structured Outputs，也要把返回值当**不可信输入**处理——检查范围、处理缺失ID、校验业务规则 | 没有查到自动重试机制的说明 |
| **DeepSeek / Kimi** | 未查到相关文档 | — | — |

**一个值得记的连带发现**：查Claude文档这块时，看到一条独立的安全提示——工具结果经常来自你控制不了的外部来源（网页、邮件、用户上传、第三方API），官方原话提醒**要把这类内容当"不可信"处理**，因为攻击者可能通过这些内容嵌入指令、试图给Claude下达非预期指令（间接prompt注入）。这正好是你路线图Layer 5"Prompt注入防护"要专门讲的内容，这里先知道"tool_result里的内容不是天然可信的"就够了，不展开。

来源：[Claude Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)、[OpenAI Function calling指南](https://developers.openai.com/api/docs/guides/function-calling)。

## 3 底层机制：从JSON到语法约束解码

上面第2节讲的是"API长什么样、怎么用"；这一节讲"为什么会是这样、底层到底发生了什么"——都是通过读vLLM/xgrammar开源代码、结合[Transformer架构](../transformer/Transformer.md)已学过的机制挖出来的。

### 3.1 时序图：JSON和模型原生格式怎么互转

上面表格里的JSON，不是模型自己直接吐出来的——中间隔着推理服务（vLLM、或DeepSeek官方后端这类软件）内部一整条流水线。以开源的DeepSeek为例，实际去查了vLLM的`deepseekv3_tool_parser.py`源码和DeepSeek官方`tokenizer_config.json`里的chat template，确认了真实的转换链路：

![Tool Calling时序图：Agent请求经Chat Template渲染、Tokenizer、LLM模型、采样器、Detokenizer、Tool Parser处理后返回JSON，红色标注两处格式转换节点](tool-calling-sequence.svg)

**核心结论**：全链路只有两处真正做JSON⇄模型原生格式的转换——① Chat Template渲染（入参JSON→模型原生格式文本，比如DeepSeek会渲染成`<｜tool▁calls▁begin｜>...`这种带特殊token的文本）、② Tool Parser解析（模型原生格式文本→出参JSON，靠正则从原始文本里抠出`tool_calls`）。中间Tokenizer/Detokenizer只做文本↔token ID的转换，LLM模型本身只认token ID张量，完全不懂JSON或文本。

**备注**：
- **Context Window的前缀缓存相关说明**：如果Agent的代码把上一轮拿到的`function.arguments`字符串解析后又重新序列化（比如`json.loads()`再`json.dumps()`），哪怕语义没变，字节层面的格式（key顺序、空格）可能变了——chat template会把这个"变了样"的字符串原样插进prompt，重新渲染出的token序列就和模型原始生成的不完全一致，KV cache从分叉点往后失效。
- **LLM↔采样器的循环就是[采样参数](../sampling-parameters/SamplingParameters.md)那一章的机制**：LLM每步吐出logits（概率分布）后，temperature/top-p/top-k决定采样器具体怎么从里面选出一个token，循环往复直到遇到停止token。

### 3.2 强制调用的底层机制：语法约束解码

`tool_choice`设成`required`或指定具体工具时，模型是**必然**调用，不是"更倾向于"调用——这不是靠prompt多说几句"你必须调用工具"就能保证的，底层机制是**语法约束解码**，直接发生在[Transformer架构](../transformer/Transformer.md)3.8节"最终Linear + Softmax"这一步。

回顾3.8节的原话："堆叠完N层后，取最后一层的输出，经过整个模型唯一一次的LM head Linear，把d_model维投影到vocab_size维得到logits（d_model维的向量和 token-向量表内每个token的向量匹配程度的打分），再经唯一一次Softmax转成概率分布，最后采样/argmax选出新token。"——**约束解码就是在"算出logits"和"Softmax"这两步中间，插入一个过滤步骤**：

![约束解码步骤图：图一展示单次Decode步骤中语法掩码插入的位置——logits算出后、Softmax之前；图二对比tool_choice=auto与required在约束生效时机上的区别](constrained-decoding-step.svg)

以DeepSeek为例（真实vocab_size是129,280，见[Token经济学](../token-economics/TokenEconomics.md)），每一步Decode，模型要在这129,280个候选里给每个都打一个logit分数。约束解码维护一个由JSON Schema/工具调用格式编译出来的"语法状态机"，每生成一个token就往前推进一步，状态机能实时判断"当前这一步，129,280个候选里哪些走得通"——不合法的那些，logit直接改成`-∞`，经Softmax后概率精确为0（`e^(-∞)=0`）。**不管温度调多高、top-p设多大，概率为0的token永远不可能被采样到**——这是数学上的排除，不是"引导"或"说服"。

**举一个具体的分叉点**：假设模型已经生成到"……需要调用天气查询工具`<｜tool▁calls▁begin｜>`"，正要决定紧接着的下一个token。按语法，这里唯一合法的后续是`<｜tool▁call▁begin｜>`，但这个token的原始logit不一定是候选里最高的——"好的""我"这类对话式续写，单纯从语言模型的角度看完全通顺，原始得分可能反而更高。无掩码和有掩码在这个分叉点上会走向完全不同的结果：

![有无掩码对比图：同一组候选token，无掩码时可能采样到"好的"这类语义通顺但破坏工具调用格式的词，导致Tool Parser解析失败；有掩码时不合法候选的logit被强制改成负无穷，只能采样到语法合法的token，保证输出能被正确解析](constrained-decoding-comparison.svg)

**无掩码**：直接按原始logits采样，"好的"这类候选完全可能被选中——模型接着往下生成"好的，我来帮您查询天气……"，这段文本从此再也拼不回`<｜tool▁calls▁begin｜>...<｜tool▁calls▁end｜>`这个结构，Tool Parser的正则匹配不到任何东西，这轮工具调用**形同虚设**，模型自己可能都没意识到调用"失败"了，因为它压根不知道自己被期待要调用工具。

**有掩码**：语法状态机在这一步已经算出"只有`<｜tool▁call▁begin｜>`合法"，把其余候选的logit全部改成`-∞`，不管原始得分怎么排，最终只能采样到这一个——不是"更倾向于选它"，是其余选项概率恒为0，选不到。

去查了vLLM的开源实现：`StructuredOutputsParams`这个类、`structural_tag`字段、底层调用`xgrammar`这个语法约束库做校验；我们之前深挖DeepSeek的tool parser源码时见过的`structural_tag_model = "deepseek_r1"`这行属性，就是把DeepSeek模型和这套约束解码机制关联起来的地方。这套机制只在**Decode阶段**（每生成一个新token时）生效，不影响Prefill阶段（处理输入prompt那一次性的批量前向计算）。

**约束不是从头到尾一刀切的，`tool_choice`不同取值，约束生效的时机也不同**。查了vLLM里两个用同一套接口注册的模型族，源码里`tool_choice`的分支走的是完全不同的构造方式：

- **`auto`（模型自己决定要不要调用）**：用的是`TriggeredTagsFormat(triggers=[...], ...)`——模型先**自由生成**，不受任何语法约束，推理服务全程盯着输出里有没有出现指定的**trigger字符串**（Hermes模型族真实用的trigger是`"<tool_call>"`，源码原文可查）；一旦匹配到，才切换进语法约束模式，限制后面的token只能符合工具调用格式。
- **`forced`/`required`（必须调用）**：用的是`TagsWithSeparatorFormat(..., at_least_one=True, stop_after_first=True)`，**完全没有`trigger`这个概念**——约束从第一个token就直接生效，没有"先自由生成、等信号"这个阶段。

这个区分是有道理的：如果`required`也走"等模型自己冒出trigger"这条路，模型理论上可以永远不生成trigger、一直输出自由文本，`required`的"必须调用"保证就落空了；只有`auto`这种"要不要调用本身也是模型的自主判断"的场景，才需要靠模型自己先生成的文本来触发信号。Kimi K3那份代码印证了同一个规律：`auto`分支用`OptionalFormat`包住工具调用部分（意思是"这部分可以没有"），`forced`/`required`分支直接把工具调用部分摆进序列，不包`Optional`。

来源：vLLM开源代码 `vllm/entrypoints/openai/engine/protocol.py`（`StructuredOutputsParams`/`validate_xgrammar_grammar`）、`vllm/tool_parsers/deepseekv3_tool_parser.py`（`structural_tag_model`属性）、`vllm/tool_parsers/structural_tag_registry.py`（`get_hermes_structural_tag`/`get_kimi_k3_structural_tag`，`TriggeredTagsFormat`/`TagsWithSeparatorFormat`的具体分支逻辑）。**如实说明置信度**：确认了这套约束解码基础设施存在、`auto`用trigger机制而`required`不用这个分野在Hermes/Kimi K3两个模型族上是逐行确认的；但没有查到DeepSeek自己具体的trigger字符串是什么（定义在xgrammar库内部，不在vLLM仓库里），也没有逐行追踪到`tool_choice=required`触发构造语法状态机的确切代码行——这两点标注为高置信度推断，不是逐行确认。

### 3.3 掩码到底管了多少：固定骨架 vs 模型自由发挥

约束解码不是把整段输出都锁死——**掩码只负责收窄候选范围，从不替模型"写"内容**。同一个工具调用里，不同位置的自由度差异很大，是一个连续的光谱，不是"固定/自由"二选一。拿`get_weather`工具（schema：`{"location": {"type":"string"}, "unit": {"type":"string","enum":["celsius","fahrenheit"]}}`）逐位置拆开看：

| 位置 | 自由度 | 原因 |
|---|---|---|
| `<｜tool▁calls▁begin｜>`、`<｜tool▁sep｜>`这类特殊token | **零自由度**，掩码把候选收窄到只剩1个 | 固定的格式骨架，跟传的工具是什么无关，模型没有选择余地 |
| 工具名（如`get_weather`） | 强制指定成这一个：**零自由度**；`auto`/`required`且有多个工具可选：**N选1** | 上一节讲过——forced到一个工具时候选列表已被砍到只剩1个，required时仍是多路选择 |
| `"location"`这个**key**本身 | **接近零自由度**（必填字段，key的字面拼法由schema定死） | key是schema定义好的字符串，不是模型可以自己发明的 |
| `"location"`对应的**值**（如`"San Francisco, CA"`） | **高自由度** | schema只写了`type:"string"`，没有enum/pattern约束，掩码只保证"最终得拼出一个合法的JSON字符串"（记得闭合引号），引号里具体写什么内容完全是模型按上下文自己判断的，跟平时生成普通文本没有区别 |
| `"unit"`对应的值 | **中等自由度，2选1** | schema写了`enum:["celsius","fahrenheit"]`，掩码只放行这两个字符串中的一个，模型自己判断选哪个 |
| 可选字段（假设某字段不是必填的） | **结构性的选择**——要不要包含这个key本身也由模型决定 | 不是"值自由"，是"要不要出现这个字段"这件事本身有弹性 |

**一个更贴切的类比**：与其说这是"填表格"，不如说是"模型在白纸上正常想写什么就写什么，旁边有个人拿着表格模板，在落笔前先把不该出现在这个位置的候选划掉"——模型自己的计算过程（Transformer那一整套attention/FFN/logits）完全不知道有这么一张"表格"存在，只是发现自己"能选的候选变少了"；真正"认识"这套格式的，是外部那个语法状态机，约束是从外部强加给生成过程的，不是模型自己的主观行为。而且这张"表格"的形状本身部分也是动态的——像上表最后一行，"要不要写某个可选字段"这件事，也是模型自己在生成过程中决定的，不像纸质表格那样从一开始就完全定型。

### 3.4 strict模式的底层机制

Claude官方文档明确写"a technique called **grammar-constrained sampling**"来描述strict模式，甚至直说"compiles tool input_schema definitions into grammars using the same pipeline as structured outputs"——**strict模式和`tool_choice=required`用的是同一套约束解码基础设施**（3.2/3.3节讲的语法状态机、逐token掩码检查），区别只在于约束的范围：`tool_choice`的约束管的是"外层格式骨架"（要不要调用、调用谁），strict的约束把这套机制**继续延伸进参数内部**——不再只保证"这是一段合法JSON"，而是保证"这段JSON严格符合这个工具的schema"（类型对、必填全、没有多余字段）。没开strict时，schema只是以文字说明的形式写进prompt供模型参考，不经过语法状态机校验，所以才会出现"应该填数字却填了字符串"这类偏差。

### 3.5 并行调用是后处理过滤，不是掩码拦截

`parallel_tool_calls`这类开关，不是靠3.2/3.3节讲的语法约束掩码在生成过程中拦截的，是推理服务的**后处理代码逻辑**做的截断。查了vLLM的实现，专门有一个函数`maybe_filter_parallel_tool_calls`，注释原话"Filter to first tool call only when parallel_tool_calls is explicitly False"，实现是`choice.message.tool_calls = choice.message.tool_calls[:1]`——**模型该生成几个工具调用还是照常生成几个，只是在返回给客户端之前，推理服务把第2个及之后的直接截断丢弃**，不是3.2节讲的那种在生成阶段用掩码把候选逻辑上排除掉。

这意味着关掉并行调用**不会**帮你省计算或省延迟——该花的生成成本一分不少，只是你看不到多出来的那几个而已。（这条是从OpenAI兼容协议路径的代码里确认的，Claude自己的生产后端闭源，`disable_parallel_tool_use`具体是掩码层面实现还是同款后处理过滤，未查证，不能一概而论。）

来源：vLLM开源代码 `vllm/entrypoints/serve/utils/tool_calls_utils.py`（`maybe_filter_parallel_tool_calls`）。

## 4 章节定位

Tool Calling是Layer 1"LLM基础"的最后一项。它和[采样参数](../sampling-parameters/SamplingParameters.md)章节末尾提到的结论正好呼应——**低温度→高确定性**这个规律，在Tool Calling场景里体现得最典型，但不是它的专属机制。

学完这一章，Layer 1（Transformer架构 → Token经济学 → Context Window → Prompt Engineering → 采样参数 → Tool Calling）整体收官，后续Layer 2"工具系统"（MCP协议、Tool Design、Permission系统……）会在这个基础上继续展开——MCP依赖Tool Calling这个模型层能力，是构建在它之上的一层标准化协议，不是与它平行的另一面。
