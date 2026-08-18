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
- [3 MCP Server](#3-mcp-server)
  - [3.1 MCP SDK](#31-mcp-sdk)
- [4 MCP Authorization](#4-mcp-authorization)
  - [4.1 概览](#41-概览)
  - [4.2 完整授权流程图](#42-完整授权流程图)
  - [4.3 几个关键机制](#43-几个关键机制)

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

来源：[MCP Tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)

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
