# Session resume and persistence（GitHub Copilot SDK）

来源：`docs.github.com/en/copilot/how-tos/copilot-sdk/use-copilot-sdk/session-persistence`

> 原文给了TypeScript/Python/Go/C#四种语言的对照示例，机制完全一样，下面只保留TypeScript（原文的主示例语言）+ Python，Go/C#省略（语法不同、行为一致，需要时再回原文查）。

## 会话工作原理

创建会话时，Copilot CLI维护对话历史、工具状态、规划上下文。默认这些状态存在内存里，会话结束就没了。开启持久化后，能跨重启、跨容器迁移、甚至跨不同客户端实例恢复会话。

会话生命周期四个状态：

| 状态 | 说明 |
|---|---|
| **Create** | 分配`session_id` |
| **Active** | 发送提示、工具调用、拿响应 |
| **Paused** | 状态存到磁盘 |
| **Resume** | 从磁盘加载状态 |

## 快速开始：创建一个可恢复的会话

**关键在于提供一个自定义的`session_id`**——不提供的话，SDK会生成一个随机ID，之后没法恢复这个会话。

```typescript
import { CopilotClient } from "@github/copilot-sdk";

const client = new CopilotClient();

const session = await client.createSession({
  sessionId: "user-123-task-456",
  model: "gpt-5.2-codex",
});

await session.sendAndWait({ prompt: "Analyze my codebase" });
// 会话状态自动持久化，可以安全关闭客户端
```

## 恢复会话

数分钟、数小时甚至数天之后，都能从中断的地方接着往下：

```typescript
// 从另一个客户端实例恢复（或者进程重启之后）
const session = await client.resumeSession("user-123-task-456");
await session.sendAndWait({ prompt: "What did we discuss earlier?" });
```

## 恢复时能重新配置的选项

恢复的时候可以改一大批配置，官方列了15个可选字段，比预想的丰富很多：

| 选项 | 说明 |
|---|---|
| `model` | 换一个模型恢复 |
| `systemMessage` | 覆盖/扩展system prompt |
| `availableTools` | 限制可用工具 |
| `excludedTools` | 禁掉特定工具 |
| `provider` | 重新提供BYOK凭证（BYOK会话**必须**重传） |
| `reasoningEffort` | 调整推理强度 |
| `streaming` | 开关流式响应 |
| `workingDirectory` | 换工作目录 |
| `configDir` | 覆盖配置目录 |
| `mcpServers` | 配置MCP服务器 |
| `customAgents` | 配置自定义agent |
| `agent` | 按名字预选一个自定义agent |
| `skillDirectories` | 加载skill的目录 |
| `disabledSkills` | 禁用哪些skill |
| `infiniteSessions` | 配置无限会话行为（见下面单独一节） |

```typescript
const session = await client.resumeSession("user-123-task-456", {
  model: "claude-sonnet-4",
  reasoningEffort: "high",
});
```

**这个能力比LangGraph/OpenAI都灵活**——LangGraph的`thread_id`恢复是纯粹接着跑原来的图，OpenAI的`session`恢复也没有这种"顺手把模型/工具/system prompt都换一遍"的选项；Copilot把"恢复"和"重新配置"合并成了一步。

## BYOK（自带密钥）配合恢复使用

用自己的API key时，**恢复必须重新传一次provider配置**——出于安全考虑，API key从来不会被持久化到磁盘：

```typescript
const session = await client.createSession({
  sessionId: "user-123-task-456",
  model: "gpt-5.2-codex",
  provider: { type: "azure", endpoint: "...", apiKey: process.env.AZURE_OPENAI_KEY, deploymentId: "..." },
});

const resumed = await client.resumeSession("user-123-task-456", {
  provider: { type: "azure", endpoint: "...", apiKey: process.env.AZURE_OPENAI_KEY, deploymentId: "..." }, // 再传一次
});
```

## 持久化的内容——跟之前笔记的目录结构对得上

存在`~/.copilot/session-state/{sessionId}/`：

```text
~/.copilot/session-state/
└── user-123-task-456/
    ├── checkpoints/           # 对话历史快照
    │   ├── 001.json          # 初始状态
    │   ├── 002.json          # 首次交互后
    │   └── ...               # 增量检查点
    ├── plan.md               # agent的规划状态（如果有）
    └── files/                # 会话产出的文件
        ├── analysis.md
        └── notes.txt
```

| 数据 | 持久化？ | 说明 |
|---|---|---|
| 对话历史 | ✅ | 完整消息线程 |
| 工具调用结果 | ✅ | 缓存下来供上下文用 |
| agent规划状态 | ✅ | `plan.md`文件 |
| 会话产出文件 | ✅ | 在`files/`目录 |
| provider/API key | ❌ | 出于安全，必须重新提供 |
| 内存中的工具状态 | ❌ | 工具本身要求设计成无状态 |

## Session ID命名最佳实践

| 模式 | 例子 | 适用场景 |
|---|---|---|
| ❌ 随机ID（如`abc123`） | — | 难审计、没有归属信息 |
| ✅ `user-{userId}-{taskId}` | `user-alice-pr-review-42` | 多用户应用 |
| ✅ `tenant-{tenantId}-{workflow}` | `tenant-acme-onboarding` | 多租户SaaS |
| ✅ `{userId}-{taskId}-{timestamp}` | `alice-deploy-1706932800` | 按时间清理 |

结构化ID的好处：容易审计（"查alice的所有会话"）、容易清理（"删掉超过X天的会话"）、天然能从ID里解析出访问控制信息。

## 管理会话生命周期

**列出/清理**：

```typescript
const sessions = await client.listSessions();
const repoSessions = await client.listSessions({ repository: "owner/repo" });

async function cleanupExpiredSessions(maxAgeMs: number) {
  const sessions = await client.listSessions();
  for (const session of sessions) {
    if (Date.now() - new Date(session.createdAt).getTime() > maxAgeMs) {
      await client.deleteSession(session.sessionId);
    }
  }
}
```

### `disconnect()` vs `deleteSession()`——一个关键区分，容易搞混

这是本篇最值得记的一处细节，跟之前"压缩到底删不删数据"是同一类"操作听起来像但实际语义不同"的坑：

- **`session.disconnect()`**——任务做完了应该显式调用它，而不是等超时。**只释放内存资源，磁盘上的会话数据保留**，之后还能`resumeSession`接着用。
- **`client.deleteSession(sessionId)`**——**永久**从磁盘删掉这个会话及其所有数据（对话历史、规划状态、产出文件）。原文明确："This is irreversible — **the session cannot** be recovered after deletion."

```typescript
// 正常收尾：内存释放，磁盘数据保留，以后还能恢复
await session.disconnect();

// 彻底清除：磁盘数据也没了，无法恢复
await client.deleteSession("user-123-task-456");
```

各语言都提供了符合语言习惯的自动清理写法：TypeScript用`Symbol.asyncDispose`（`await using session = ...`）、Python用`async with`上下文管理器、C#用`IAsyncDisposable`、Go用`defer session.Disconnect()`。**`destroy()`已废弃，统一改用`disconnect()`**（旧代码还能跑，但应该迁移）。

## 自动清理：空闲超时

默认**没有空闲超时**，会话生命周期无限，直到显式`disconnect`或`delete`。可以在客户端级别配置：

```typescript
const client = new CopilotClient({
  sessionIdleTimeoutSeconds: 30 * 60, // 30分钟无活动就自动清理
});
```

`0`或不设置就是禁用这个超时。**注意：这个选项只在SDK自己拉起运行时进程时生效；如果是通过`cliUrl`连到一个已经在跑的服务器，超时配置由那个应用服务器自己管，不受这个选项控制。**

有活跃工作（跑命令、后台agent）的会话，不管超时怎么设，**永远不会**被空闲清理误杀。

也可以订阅空闲事件：

```typescript
session.on("session.idle", (event) => {
  console.log(`Session idle for ${event.idleDurationMs}ms`);
});
```

## 部署模式

**模式1：每用户一个CLI服务器（官方推荐）**——适合强隔离、多租户、Azure动态会话场景，优点是完全隔离、安全模型简单、扩展容易。

**模式2：共享CLI服务器（省资源）**——适合内部工具、可信环境、资源受限的场合，但要求：每个用户的session ID必须唯一、应用层自己做访问控制、操作前要校验session ID归属：

```typescript
async function resumeSessionWithAuth(client, sessionId, currentUserId) {
  const [sessionUserId] = sessionId.split("-");
  if (sessionUserId !== currentUserId) {
    throw new Error("Access denied: session belongs to another user");
  }
  return client.resumeSession(sessionId);
}
```

## Azure动态会话——容器可能重启/迁移的部署场景

会话状态目录必须挂载到持久存储上：

```yaml
containers:
  - name: copilot-agent
    volumeMounts:
      - name: session-storage
        mountPath: /home/app/.copilot/session-state
volumes:
  - name: session-storage
    azureFile:
      shareName: copilot-sessions
      storageAccountName: myaccount
```

挂载好之后，容器重启会话依然能恢复。

## 无限会话（Infinite Sessions）——长时间运行工作流的自动压缩

对可能超出上下文限制的长工作流，开启`infiniteSessions`：

```typescript
const session = await client.createSession({
  sessionId: "long-workflow-123",
  infiniteSessions: {
    enabled: true,
    backgroundCompactionThreshold: 0.80,  // 上下文用到80%就开始后台压缩
    bufferExhaustionThreshold: 0.95,      // 95%时如果必要就阻塞
  },
});
```

注意：这两个阈值是**上下文利用率比例**（0.0-1.0），不是绝对token数。`ContextWindow.md`§2.3.3已经有一张完整的五源压缩对比表，Copilot这一行原本是空的（"具体触发阈值本轮未深挖"），这次查到的数字已经补进那张表了——完整对比（含LangGraph的"无内置阈值靠开发者接组件"、Claude的"三层数据"细节、OpenClaw的"实时算溢出量"）直接看那张表，这里不重复展开。

## 限制和注意事项

| 限制 | 说明 | 缓解办法 |
|---|---|---|
| BYOK需要重新认证 | API key不持久化 | 存进密钥管理器，恢复时按需取用 |
| 需要可写存储 | `~/.copilot/session-state/`必须可写 | 容器里挂载持久卷 |
| **没有内置的会话锁** | 同一个session被并发访问时行为未定义 | 应用层自己实现锁或排队 |
| 工具状态不持久化 | 内存里的工具状态会丢 | 工具设计成无状态，或者自己另外持久化 |

### 并发访问怎么办——SDK不管，官方给了个Redis锁的示例

```typescript
import Redis from "ioredis";
const redis = new Redis();

async function withSessionLock(sessionId, fn) {
  const lockKey = `session-lock:${sessionId}`;
  const acquired = await redis.set(lockKey, "locked", "NX", "EX", 300);
  if (!acquired) throw new Error("Session is in use by another client");
  try {
    return await fn();
  } finally {
    await redis.del(lockKey);
  }
}
```

**这一点是LangGraph/OpenAI/Claude Agent SDK三家笔记里都没有明确讨论过的话题**——"同一个session被两个客户端同时操作会怎样"，Copilot官方直接承认"没有内置机制，自己想办法"，这算是它比另外几家更坦诚地暴露了一个共性问题（其他几家笔记里都没查到这方面的说明，不代表它们没有这个问题，只是没查到官方怎么说）。

## 值得记的点

（下面重新核对过跟之前几篇笔记的重复度，不是每一条都是新发现，如实标注）

- **真正新增的能力：恢复会话时能顺手重新配置model/工具/system prompt等15个选项**——这是LangGraph/OpenAI都没有的，"恢复"和"重新配置"合并成一步。
- **补上了`ContextWindow.md`§2.3.3压缩对比表里一个明确留白的空**：无限会话的压缩阈值用的是"上下文利用率比例"（0.0-1.0），不是绝对token/字节数——这个数字之前在那张五源对比表里是空的（原文标注"具体触发阈值本轮未深挖"），已经把这次查到的`0.80`/`0.95`补进去了。**完整的跨厂商压缩机制对比要看那张表，不在这里重复展开**（之前我在这里写的"跟OpenClaw/Claude Code凑成三种度量方式"是简化过头了——Claude那边其实是三层数据、不是单一的"绝对token数"，直接看`ContextWindow.md`里的原表更准确）。
- **`disconnect()` vs `deleteSession()`——概念部分重复，不是全新的**：`Sessions（OpenAI）学习笔记.md`里`RedisSession`/`DaprSession`的`close()`"owned client→终态"已经是同一类"释放连接≠删除数据"的概念了，只是当时没讲清楚底层数据是否被删；Copilot这篇的真实贡献只是把这个区分做得更显式（两个命名不同、语义不同的方法，`deleteSession()`原文明确写了"irreversible"）。
- **"没有内置会话锁"——不是一个新话题，是跟OpenClaw给出了相反答案**：`Agent loop（OpenClaw）学习笔记.md`里OpenClaw有一整套并发控制（`activeWriterRunId`声明+`expectedWriterRunId`校验+SQLite写入队列+Gateway状态目录锁）。真正的看点是**"Copilot坦然交给应用层自己解决，OpenClaw自己做了一整套锁机制"这个反差**，不是"Copilot提出了一个新问题"——最终做对比表时，这一行应该是OpenClaw和Copilot对着写，不是单独给Copilot记一笔。
