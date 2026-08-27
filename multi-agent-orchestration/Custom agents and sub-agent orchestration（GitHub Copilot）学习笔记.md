# Custom agents and sub-agent orchestration（GitHub Copilot SDK）

官方文档：[Custom agents and sub-agent orchestration](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents)

## 1 核心概念

**自定义agent是轻量级的agent定义，可以附加到一个session上**。每个agent都有自己的系统提示词、工具限制、可选的MCP服务器。**当用户请求跟某个agent的专长匹配时，Copilot运行时会自动把它当子agent委托出去**——在隔离的上下文里跑，同时把生命周期事件流回父session。

四个关键概念：

| 概念 | 含义 |
|---|---|
| **自定义agent（Custom agent）** | 一份带有自己提示词和工具集的命名agent配置 |
| **子agent（Subagent）** | 被运行时调用、去处理任务一部分的自定义agent |
| **推断（Inference）** | 运行时基于用户意图自动选择agent的能力 |
| **父session（Parent session）** | 派生子agent的那个session，接收所有生命周期事件 |

## 2 定义自定义agent

创建session时传`customAgents`，每个agent至少要有`name`和`prompt`：

```typescript
const session = await client.createSession({
    model: "gpt-5.4",
    customAgents: [
        {
            name: "researcher",
            displayName: "Research Agent",
            description: "Explores codebases and answers questions using read-only tools",
            tools: ["grep", "glob", "view"],
            prompt: "You are a research assistant. Analyze code and answer questions. Do not modify any files.",
        },
        {
            name: "editor",
            displayName: "Editor Agent",
            description: "Makes targeted code changes",
            tools: ["view", "edit", "bash"],
            prompt: "You are a code editor. Make minimal, surgical changes to files as requested.",
        },
    ],
});
```

### 配置字段参考

| 字段 | 类型 | 必需 | 说明 |
|---|---|:---:|---|
| `name` | string | ✅ | agent的唯一标识符 |
| `displayName` | string | | 事件里展示的可读名字 |
| `description` | string | | agent能力描述——**帮助运行时选中它**（自动推断依赖这个字段） |
| `tools` | string[] 或 null | | 这个agent能用的工具名，`null`或不填=全部工具 |
| `prompt` | string | ✅ | agent的系统提示词 |
| `mcpServers` | object | | 这个agent专属的MCP服务器配置 |
| `infer` | boolean | | 运行时能不能自动选中这个agent（默认`true`） |
| `skills` | string[] | | 启动时预加载进这个agent上下文的技能名 |
| `model` | string | | 这个agent运行用的模型 |
| `reasoningEffort` | string | | 这个agent运行用的推理力度 |

官方提示：好的`description`帮运行时把用户意图匹配到正确的agent，要具体说明这个agent擅长什么、能做什么。

**会话级还有一个`agent`属性**：在创建session时预选一个自定义agent，让它从一开始就是活跃状态（值必须匹配`customAgents`里某个agent的`name`）。

## 3 每个agent的技能预加载

用`skills`属性可以把技能预加载进某个agent的上下文——**指定的每个技能，完整内容会在启动时被"急切地"（eagerly）直接注入agent上下文，agent不需要再调用技能工具，说明已经就位了**。技能是可选的：agent默认不带任何技能，**子agent不会从父agent那里继承技能**——比如`security-auditor`启动就带着`security-scan`/`dependency-check`两个技能，`docs-writer`只带`markdown-lint`，没配`skills`字段的agent不带任何技能内容。

**这一点是三个厂商（Claude/LangChain/Copilot）里对"技能怎么进上下文"讲得最直白的一次**——Claude Skills是渐进式披露（先metadata，用到才加载完整内容），这里明确是"急切注入"（eager，启动就整段塞进去），是两种不同的加载时机策略。

## 4 子agent委托的完整流程——五步

给一个配了自定义agent的session发提示词时，运行时按下面五步评估要不要委托：

1. **意图匹配**——运行时分析用户提示词跟每个agent的`name`和`description`
2. **agent选择**——如果找到匹配、且`infer`不是`false`，运行时选中这个agent
3. **隔离执行**——子agent用自己的提示词和受限的工具集去跑
4. **事件流**——生命周期事件（`subagent.started`、`subagent.completed`等）流回父session
5. **结果整合**——子agent的产出被并入父agent的回复

## 5 控制推断——`infer: false`

默认所有自定义agent都参与自动选择（`infer: true`）。设`infer: false`能防止运行时自动选中某个agent——**适用于那种只想在用户明确要求时才调用的agent**：

```typescript
{
    name: "dangerous-cleanup",
    description: "Deletes unused files and dead code",
    tools: ["bash", "edit", "view"],
    prompt: "You clean up codebases by removing dead code and unused files.",
    infer: false, // 只有用户明确要求才会调用这个agent
}
```

## 6 监听子agent事件——五种事件类型

子agent运行时，父session会发出生命周期事件，订阅它们可以构建可视化的agent活动UI：

| 事件 | 什么时候发 | 携带的数据 |
|---|---|---|
| `subagent.selected` | 运行时为任务选中了某个agent | `agentName`、`agentDisplayName`、`tools` |
| `subagent.started` | 子agent开始执行 | `toolCallId`、`agentName`、`agentDisplayName`、`agentDescription`、`model?` |
| `subagent.completed` | 子agent成功完成 | `toolCallId`、`agentName`、`agentDisplayName`、`model?`、`durationMs?`、`totalTokens?`、`totalToolCalls?` |
| `subagent.failed` | 子agent遇到错误 | `toolCallId`、`agentName`、`agentDisplayName`、`error`、`model?`、`durationMs?`、`totalTokens?`、`totalToolCalls?` |
| `subagent.deselected` | 运行时切换离开这个子agent | — |

**这套事件系统是这几家里颗粒度最细的一次**——不只是"完成了/失败了"，连`durationMs`（耗时）、`totalTokens`（token消耗）、`totalToolCalls`（工具调用次数）都作为标准字段直接暴露出来，不需要开发者自己另外埋点统计。

### 用`toolCallId`重建agent执行树

`subagent.started`等事件都带`toolCallId`字段，可以用它把多个子agent的执行状态组织成一棵树（每个节点记录`name`/`status`/`startedAt`/`completedAt`/`error`），配合事件流实时渲染一个"agent活动树"UI——这是官方给出的具体推荐用法。

## 7 限制每个agent的工具——安全和专注的双重考虑

跟前面`AgentDefinition`的`tools`字段类似：给只读探索agent配`["grep", "glob", "view"]`（没有写权限），给编辑agent配`["view", "edit", "bash"]`（有写权限），或者`tools: null`给一个"全权限"agent处理复杂任务。官方原话："使用显式工具列表强制实施最小权限原则"——工具限制在这里被明确当成一种安全边界，不只是"让agent更专注"的工程手段。

## 8 Agent专属工具——`defaultAgent.excludedTools`，这次翻译里最值得记的机制

**用`defaultAgent`属性可以从"默认agent"（没有选中任何自定义agent时处理对话的那个内置agent）身上，隐藏掉指定的工具**。这样一来，主agent一旦需要这个能力，就**被迫**只能委托给某个带着这个工具的子agent——保持主agent的上下文干净。

**适用场景，官方列了三条**：某个工具会产生大量上下文，容易把主agent的上下文撑爆；想让主agent纯粹当"协调者"，把重活都甩给专门的子agent；需要在"编排"和"执行"之间做严格分离。

```typescript
const session = await client.createSession({
    tools: [heavyContextTool],   // analyze-codebase：会产出大量上下文的重工具
    defaultAgent: {
        excludedTools: ["analyze-codebase"],  // 主agent看不到、调不了这个工具
    },
    customAgents: [
        {
            name: "researcher",
            description: "Deep codebase analysis agent with access to heavy-context tools",
            tools: ["analyze-codebase"],   // 只有researcher子agent能用
            prompt: "You perform thorough codebase analysis using the analyze-codebase tool.",
        },
    ],
});
```

**具体运作方式**：列在`defaultAgent.excludedTools`里的工具，**处理程序（handler）依然被正常注册、能执行**；只是**对LLM隐藏**——主agent的模型看不到它、也没法直接调用；**任何在自己`tools`数组里列了它的自定义子agent，依然能正常使用它**。

**这是目前查到的、唯一一家把"故意藏起一个能力、逼主agent必须委托"当成显式设计工具的厂商**——Claude/OpenAI/LangChain都在讲"怎么让主agent决定要不要委托"，Copilot这里反过来提供了一个"不给你选、你就是得委托"的强制手段，是一种更强硬的架构约束，不是靠提示词说服模型，是靠工具可见性直接卡死。

### 跟另外两种工具过滤器的优先级关系

| 过滤器 | 作用范围 | 效果 |
|---|---|---|
| `availableTools` | 整个session | 白名单——只有这些工具对任何人存在 |
| `excludedTools` | 整个session | 黑名单——这些工具对任何人都被屏蔽 |
| `defaultAgent.excludedTools` | 只对主agent | 对主agent隐藏，对子agent依然可用 |

**优先级**：会话级`availableTools`/`excludedTools`先生效（全局层面），`defaultAgent.excludedTools`在这个基础上再对主agent单独加一层限制。**如果一个工具同时出现在会话级`excludedTools`和`defaultAgent.excludedTools`里，会话级的排除优先——这个工具对所有人都不可用**（子agent也救不回来）。

## 9 给agent挂MCP服务器

每个自定义agent都能有自己专属的MCP服务器，接入专门的数据源：

```typescript
customAgents: [
    {
        name: "db-analyst",
        description: "Analyzes database schemas and queries",
        prompt: "You are a database expert. Use the database MCP server to analyze schemas.",
        mcpServers: {
            "database": { command: "npx", args: ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"] },
        },
    },
],
```

## 10 模式和最佳实践

- **研究者+编辑者配对**：定义一个只读的研究agent（`grep`/`glob`/`view`）和一个有写权限的编辑agent（`view`/`edit`/`bash`），运行时会把探索类任务派给研究者、修改类任务派给编辑者——这是Copilot官方点名推荐的一个具体模式。
- **描述要具体，不要笼统**：官方举了反例`{ description: "Helps with code" }`（运行时没法跟别的agent区分开）vs 正例`{ description: "Analyzes Python test coverage and identifies untested code paths" }`——跟`Subagents（LangChain）学习笔记.md`里"name和description是提示词层面的杠杆，要仔细选"是同一条经验的另一次印证。
- **优雅处理失败**：始终监听`subagent.failed`事件，在应用里处理（记日志、给用户提示错误、重试、或者回退到主agent），不要假设子agent一定会成功。

## 值得记的点

- **`defaultAgent.excludedTools`是这次翻译里最有价值的新发现**——用"对主agent隐藏工具、强制委托给子agent"这种架构级手段，取代"靠提示词说服主agent该委托的时候委托"，是一种更硬的约束方式，另外三家（Claude/OpenAI/LangChain）都没有对应机制。
- **技能预加载的"急切注入"vs Claude Skills的"渐进式披露"，是两种不同的加载时机哲学**——Copilot这边一旦配了`skills`，内容在session启动那一刻就全量塞进去；Claude Skills是先给一段metadata，真正用到时才加载完整内容进上下文。两种各有代价：急切注入省去了"要不要加载"的判断开销，但不管用不用得上都先占着上下文；渐进式披露更省token，但多一轮"发现-加载"的开销。
- **事件系统里自带`durationMs`/`totalTokens`/`totalToolCalls`这几个可观测性字段**，直接对应了Layer 4"可观测性"里"成本追踪""Token用量分析"要解决的问题——这几个指标在Copilot这边是子agent生命周期事件的标准字段，不需要开发者自己另外埋点，这个设计值得后面学可观测性那几章时回头对比。
