# 错误语义设计

**结论：这个话题也不需要单独展开成一整章新内容——跟[工具发现/注册](../tool-discovery/ToolDiscovery.md)一样，内容被拆成了三个不同层次分别学过了，这里做索引，并补一条之前漏掉的官方判断标准。**

一开始以为ToolDesign.md里已经"非常详细"学过这一块，核实下来发现：ToolDesign.md里其实只有两段分散的旁枝内容，撑不起一整章分量；但把ToolCalling.md、MCPProtocol.md、ToolDesign.md三处已学内容拼起来看，恰好覆盖了错误从"协议里被服务器标记"到"被翻译成模型能读的格式"再到"文案该怎么写"的完整链条——只是分散在三个不同的抽象层级，之前没人把它们串起来过。

## 三层各自回答什么问题

| 层次 | 回答的问题 | 已学位置 |
| --- | --- | --- |
| 模型API线格式层 | LLM侧的API，怎么把"这次调用失败了"这个事实告诉模型？ | [ToolCalling.md §2.6](../tool-calling/ToolCalling.md#26-tool_result里有没有专门的错误字段) |
| MCP协议结构层 | MCP协议内部，错误分几种、该用哪种JSON结构表示、为什么要分？ | [MCPProtocol.md §1.5](../mcp-protocol/MCPProtocol.md#15-错误处理机制protocol-errors与tool-execution-errors) |
| 工具设计原则层 | 错误信息的文案本身该怎么写，才能让Agent读了能纠正？ | [ToolDesign.md §3.4](../tool-design/ToolDesign.md#34-优化token效率)、[§3.5⑤](../tool-design/ToolDesign.md#35-对工具描述做prompt-engineering我们做得最深的部分) |

## 层次一：模型API线格式层

**Claude和OpenAI在这一层的设计哲学完全不同**——Claude给`tool_result`配了专门的`is_error: true`字段，官方明确建议写有信息量的错误信息（如`"Rate limit exceeded. Retry after 60 seconds."`），且工具调用本身不合法时会自动重试2-3次；OpenAI没有专门字段，错误就是塞进结果里的一个普通字符串，格式（JSON/错误码/纯文本）完全自定义，官方原话"the model will interpret that string as needed"。

这一层对应的是"**LLM能不能一眼从结构上认出这是个错误**"——Claude靠字段名，OpenAI靠约定俗成的字符串内容，两种设计哲学都成立，但可靠性不同（结构化字段比字符串约定更不容易被漏判）。

## 层次二：MCP协议结构层

MCP官方把错误拆成**Protocol Errors**（JSON-RPC标准`error`字段，工具名不存在/参数不合法这类请求结构本身的问题）和**Tool Execution Errors**（`result.isError: true`，工具正常被调用、但业务逻辑执行失败）两层，这条已经在MCPProtocol.md §1.5记过。

**这次新补的是官方给出的判断标准本身**——两层为什么要分开，不是随便分类，而是按"**模型能不能凭这条反馈自己纠正**"来分的：Tool Execution Errors算"actionable feedback"，Client**应该（SHOULD）**转发给LLM；Protocol Errors是请求结构本身的问题，模型大概率改不好，Client转发不转发是**可选的（MAY）**。这条规则解释了为什么1.6节实测脚本里"参数校验失败"走的是Tool Execution Error——因为"参数不对"对模型来说是可自我纠正的。

## 层次三：工具设计原则层

前两层解决的是"错误该被谁看到、走哪个字段"，这一层解决的是"**文案本身写得好不好**"——即便字段/协议层设计得再规范，一句`"Error: invalid input"`还是没用。ToolDesign.md里两处相关内容：

- §3.4：报错要给"具体问题+可操作的改进方式"，不要模糊错误码；我们工具的`未知的仓库名：xxx。当前配置里可用的仓库：promotion-api`就是这条原则的实例。
- §3.5⑤：不只是"报错"需要说清楚语义，**正常返回值里携带的隐含状态**也要说清楚——`risk`字段等于`UNKNOWN`本身携带精确语义（"查无此符号"），不说清楚Agent会理解成"没有结果=没有影响"。这条严格说不是"错误处理"，但本质上是同一个原则的延伸：**任何"非常规状态"（无论是报错还是正常返回里的特殊值），都需要显式说明语义，不能指望Agent靠字面意思脑补**。

## 一个值得记的反差

OpenAI官方Function Calling指南在"错误该怎么设计"这件事上基本是空白——原文原话是结果格式"up to you (JSON, error codes, plain text, etc.)"，没有给出任何具体指导。跟Anthropic（`is_error`字段+文案建议）、MCP（两层机制+SHOULD/MAY判断标准）的具体程度形成明显对比：**这不是三方对同一个问题给出了不同答案，而是只有两方真正把"错误语义"当成一个值得设计的问题来对待**。

## 后续

如果之后遇到更细的错误恢复策略（比如重试次数、退避策略、幂等键配合错误重试），那属于[幂等性保障](../tool-design/ToolDesign.md#35-对工具描述做prompt-engineering我们做得最深的部分)和Layer 5"故障恢复策略"的范畴，不在这份文档展开。
