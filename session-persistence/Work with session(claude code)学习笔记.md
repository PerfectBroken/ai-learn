# 处理会话

会话如何持久化智能体的对话历史，以及何时使用 continue（继续）、resume（恢复）和 fork（分叉）来回到之前的运行。

**会话（session）** 是 SDK 在你的智能体工作过程中累积的对话历史。它包含你的提示词、智能体发起的每一次工具调用、每一个工具结果以及每一条响应。SDK 会自动将其写入磁盘，以便你之后可以回到它。回到一个会话意味着智能体拥有之前的完整上下文：它已经读过的文件、已经执行过的分析、已经做出的决策。你可以提出后续问题、从中断中恢复，或者分支出去尝试不同的方法。

会话持久化的是**对话**，而不是文件系统。要快照和回滚智能体所做的文件更改，请使用[文件检查点](https://code.claude.com/docs/en/agent-sdk/file-checkpointing)。

本指南涵盖：如何为你的应用选择正确的方法、自动跟踪会话的 SDK 接口、如何捕获会话 ID 并手动使用 `resume` 和 `fork`，以及关于跨主机恢复会话需要了解的内容。

## 选择方法

你需要多少会话处理取决于你的应用形态。当你发送多个应该共享上下文的提示词时，会话管理就会发挥作用。在单次 `query()` 调用中，智能体已经会根据需要进行多轮交互，权限提示和 `AskUserQuestion` 是[在循环内处理](https://code.claude.com/docs/en/agent-sdk/agent-loop#in-loop-interactions)的（它们不会结束调用）。

| 你正在构建什么 | 使用什么 |
|---|---|
| 一次性任务：单个提示词，无后续 | 无需额外操作。一次 `query()` 调用即可处理。 |
| 单进程中的多轮对话 | `ClaudeSDKClient`（Python）或 `continue: true`（TypeScript）。SDK 为你跟踪会话，无需处理 ID。 |
| 进程重启后从中断处继续 | `continue_conversation=True`（Python）/ `continue: true`（TypeScript）。恢复目录中最近的会话，无需 ID。 |
| 恢复某个特定的历史会话（非最近的） | 捕获会话 ID 并将其传给 `resume`。 |
| 在不丢失原始方案的情况下尝试替代方法 | 分叉（fork）会话。 |
| 无状态任务，不希望任何内容写入磁盘（仅 TypeScript） | 设置 `persistSession: false`。会话仅在调用期间存在于内存中。Python 始终持久化到磁盘。 |


### 继续、恢复与分叉

Continue、resume 和 fork 是你在 `query()` 上设置的选项字段（Python 中的 [ClaudeAgentOptions](https://code.claude.com/docs/en/reference/python/agent-sdk/ClaudeAgentOptions)，TypeScript 中的 [Options](https://code.claude.com/docs/en/reference/typescript/agent-sdk/Options)）。**Continue** 和 **resume** 都会拾取一个已有的会话并在其上追加内容。区别在于它们如何找到那个会话：

- **Continue** 查找当前目录中最近的会话。你不需要跟踪任何东西。当你的应用一次只运行一个对话时效果很好。
- **Resume** 接受一个特定的会话 ID。由你来跟踪这个 ID。当你有多个会话时（例如，多用户应用中每个用户一个会话），或者想回到一个不是最近的会话时，需要使用它。

**Fork** 则不同：它创建一个新会话，以原始会话历史的副本作为起点。原始会话保持不变。使用 fork 来尝试不同的方向，同时保留回到原方向的选项。

---

## 自动会话管理

两个 SDK 都提供了一个接口，可以跨调用为你跟踪会话状态，因此你不需要手动传递 ID。在单进程内进行多轮对话时使用这些接口。

### Python：`ClaudeSDKClient`

[ClaudeSDKClient](https://code.claude.com/docs/en/reference/python/agent-sdk/ClaudeSDKClient) 在内部处理会话 ID。每次调用 `client.query()` 都会自动继续同一个会话。调用 [client.receive_response\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/ClaudeSDKClient#receive_response) 来迭代当前查询的消息。将客户端用作异步上下文管理器，以便连接的建立和拆除自动为你处理，或者手动调用 `connect()` 和 `disconnect()`。

以下示例对同一个 `client` 运行两个查询。第一个要求智能体分析一个模块；第二个要求它重构该模块。因为两次调用都通过同一个客户端实例，第二个查询拥有第一个查询的完整上下文，无需任何显式的 `resume` 或会话 ID：

```python
import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

def print_response(message):
    """仅打印消息中人类可读的部分。"""
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                print(block.text)
    elif isinstance(message, ResultMessage):
        cost = (
            f"${message.total_cost_usd:.4f}"
            if message.total_cost_usd is not None
            else "N/A"
        )
        print(f"[done: {message.subtype}, cost: {cost}]")

async def main():
    options = ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Glob", "Grep"],
    )

    async with ClaudeSDKClient(options=options) as client:
        # 第一个查询：客户端在内部捕获会话 ID
        await client.query("Analyze the auth module")
        async for message in client.receive_response():
            print_response(message)

        # 第二个查询：自动继续同一个会话
        await client.query("Now refactor it to use JWT")
        async for message in client.receive_response():
            print_response(message)

asyncio.run(main())

```


## 在 `query()` 中使用会话选项

### 捕获会话 ID

Resume 和 fork 需要一个会话 ID。从结果消息的 `session_id` 字段中读取它（Python 中的 [ResultMessage](https://code.claude.com/docs/en/reference/python/agent-sdk/ResultMessage)，TypeScript 中的 [SDKResultMessage](https://code.claude.com/docs/en/reference/typescript/agent-sdk/SDKResultMessage)），无论成功还是错误，每个结果上都有该字段。在 TypeScript 中，该 ID 也可以更早地作为 init `SystemMessage` 上的直接字段获取；在 Python 中，它嵌套在 `SystemMessage.data` 内部。

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

async def main():
    session_id = None

    try:
        async for message in query(
            prompt="Analyze the auth module and suggest improvements",
            options=ClaudeAgentOptions(
                allowed_tools=["Read", "Glob", "Grep"],
            ),
        ):
            if isinstance(message, ResultMessage):
                session_id = message.session_id
                if message.subtype == "success":
                    print(message.result)
    except Exception as error:
        # 单次 query() 在产出错误结果后会抛出异常。如果
        # 失败是一个错误结果，上面的循环已经捕获了 session_id；
        # 进程失败不会产出结果消息，因此 session_id 保持为 None。
        print(f"Session ended with an error: {error}")

    print(f"Session ID: {session_id}")
    return session_id

session_id = asyncio.run(main())

```

### 按 ID 恢复

将会话 ID 传给 `resume` 以回到那个特定的会话。智能体会从会话中断的地方拾起，拥有完整上下文。恢复的常见原因：

- **对已完成的任务进行后续跟进。** 智能体已经分析了某些内容；现在你希望它基于该分析采取行动，而无需重新读取文件。
- **从限制中恢复。** 第一次运行以 `error_max_turns` 或 `error_max_budget_usd` 结束（参见[处理结果](https://code.claude.com/docs/en/agent-sdk/query#handle-the-result)）；以更高的限制恢复。在单次 `query()` 调用中，SDK 在产出该错误结果后会抛出异常，因此在恢复前要捕获错误。
- **重启你的进程。** 你在关闭前捕获了 ID，并希望恢复对话。

以下示例用一个后续提示恢复[捕获会话 ID](#capture-the-session-id)中的会话。因为你正在恢复，智能体的上下文中已经有了之前的分析：

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

session_id = "..."  # 你在上一个示例中捕获的 ID

async def main():
    # 之前的会话分析了代码；现在基于该分析继续构建
    async for message in query(
        prompt="Now implement the refactoring you suggested",
        options=ClaudeAgentOptions(
            resume=session_id,
            allowed_tools=["Read", "Edit", "Write", "Glob", "Grep"],
        ),
    ):
        if isinstance(message, ResultMessage) and message.subtype == "success":
            print(message.result)

asyncio.run(main())

```
你应该会看到一个基于之前分析构建的响应，而不是从头开始。这确认了智能体在恢复会话时保留了之前的上下文。

如果 `resume` 调用返回了一个全新的会话而不是预期的历史记录，最常见的原因是 `cwd`（当前工作目录）不匹配。会话存储在 `~/.claude/projects/<encoded-cwd>/*.jsonl` 下，或者如果你设置了 `CLAUDE_CONFIG_DIR` 环境变量，则存储在 `$CLAUDE_CONFIG_DIR/projects/<encoded-cwd>/*.jsonl` 下，其中 `<encoded-cwd>` 是绝对工作目录，每个非字母数字字符都被替换为 `-`（因此 `/Users/me/proj` 变为 `-Users-me-proj`）。如果你的 resume 调用从不同的目录运行，SDK 会在错误的位置查找。会话文件也需要存在于当前机器上。

要跨机器或在无服务器环境中恢复会话，请使用 [SessionStore 适配器](https://code.claude.com/docs/en/agent-sdk/sessions#sessionstore-adapter)将转录镜像到共享存储。



### 分叉以探索替代方案

分叉（forking）创建一个新会话，它以原始会话历史的副本开始，但从该点起产生分歧。分叉获得自己的会话 ID；原始会话的 ID 和历史保持不变。你最终会得到两个独立的会话，可以分别恢复。

分叉分支的是对话历史，而不是文件系统。如果分叉的智能体编辑了文件，这些更改是真实的，对在同一目录中工作的任何会话都是可见的。要分支和回滚文件更改，请使用[文件检查点](https://code.claude.com/docs/en/agent-sdk/file-checkpointing)。

以下示例基于[捕获会话 ID](#capture-the-session-id)构建：你已经在 `session_id` 中分析了一个认证模块，并希望在不丢失以 JWT 为重点的线程的情况下探索 OAuth2。第一个代码块分叉会话并捕获分叉的 ID（`forked_id`）；第二个代码块恢复原始的 `session_id` 以继续 JWT 路径。你现在有两个指向两个独立历史的会话 ID：

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

session_id = "..."  # 你在上一个示例中捕获的 ID

async def main():
    # 分叉：从 session_id 分支到一个新会话
    forked_id = None
    try:
        async for message in query(
            prompt="Instead of JWT, outline how OAuth2 would work for the auth module",
            options=ClaudeAgentOptions(
                resume=session_id,
                fork_session=True,
                max_turns=5,
            ),
        ):
            if isinstance(message, ResultMessage):
                forked_id = message.session_id  # 分叉的 ID，与 session_id 不同
                if message.subtype == "success":
                    print(message.result)
    except Exception as error:
        # 单次 query() 在产出错误结果后会抛出异常。如果
        # 失败是一个错误结果，forked_id 已被上面的循环捕获；
        # 连接或进程失败不会产出结果消息。
        print(f"Session ended with an error: {error}")

    print(f"Forked session: {forked_id}")

    # 原始会话未被触碰；恢复它继续 JWT 线程
    try:
        async for message in query(
            prompt="Continue with the JWT approach",
            options=ClaudeAgentOptions(resume=session_id),
        ):
            if isinstance(message, ResultMessage) and message.subtype == "success":
                print(message.result)
    except Exception as error:
        # 单次 query() 在产出错误结果后会抛出异常。
        print(f"Session ended with an error: {error}")

asyncio.run(main())
```


## 跨主机恢复

会话文件是创建它们的机器本地的。要在不同的主机上恢复会话（CI 工作器、临时容器、无服务器），你有两个选择：

- **移动会话文件。** 持久化第一次运行的 `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`，并在调用 `resume` 之前将其恢复到新主机上的相同路径。`cwd` 必须匹配。
- **不依赖会话恢复。** 将你需要的结果（分析输出、决策、文件差异）捕获为应用状态，并将它们传入全新会话的提示词中。这通常比到处传输转录文件更稳健。

两个 SDK 都暴露了用于枚举磁盘上的会话和读取其消息的函数：TypeScript 中的 [listSessions\(\)](https://code.claude.com/docs/en/reference/typescript/agent-sdk/listSessions) 和 [getSessionMessages\(\)](https://code.claude.com/docs/en/reference/typescript/agent-sdk/getSessionMessages)，Python 中的 [list_sessions\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/list_sessions) 和 [get_session_messages\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/get_session_messages)。使用它们来构建自定义会话选择器、清理逻辑或转录查看器。

两个 SDK 还暴露了用于查找和变更单个会话的函数：Python 中的 [get_session_info\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/get_session_info)、[rename_session\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/rename_session) 和 [tag_session\(\)](https://code.claude.com/docs/en/reference/python/agent-sdk/tag_session)，以及 TypeScript 中的 [getSessionInfo\(\)](https://code.claude.com/docs/en/reference/typescript/agent-sdk/getSessionInfo)、[renameSession\(\)](https://code.claude.com/docs/en/reference/typescript/agent-sdk/renameSession) 和 [tagSession\(\)](https://code.claude.com/docs/en/reference/typescript/agent-sdk/tagSession)。使用它们按标签组织会话或给它们起人类可读的标题。