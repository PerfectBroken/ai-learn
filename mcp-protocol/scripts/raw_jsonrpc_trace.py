"""在MCP官方client SDK和真实的server.py子进程之间"抓包"——不看SDK解析好的Python
对象，而是打印实际在stdio管道上往返的、原始的JSON-RPC 2.0消息本身，跟MCPProtocol.md
1.3/1.4/1.5节学的内容对上号：
  - 1.3节：capabilities协商发生在initialize握手阶段——所以先看initialize的request/response
  - 1.4节：连接建立后做tools/list完成工具发现——对应下面第二组request/response
  - 1.5节：Protocol Errors走JSON-RPC的error字段，Tool Execution Errors走result里的isError——
    这里额外发一次"合法工具名+非法参数"的tools/call，实测这次触发的到底是哪一层错误
    （笔记原本只给了"工具名不存在"和"业务逻辑失败"两个例子，没覆盖"参数校验失败"这种，
    这个脚本补上了：实测结果走的是Tool Execution Error，即result.isError=true，不是
    JSON-RPC的error字段——只要工具名合法，参数校验失败也被算作"工具执行的结果之一"）

运行前提：依赖 ../../tool-design/api-impact-tool/venv 这个虚拟环境（已装好mcp、pydantic），
这份venv属于tool-design那一章的api-impact-tool项目，不要另外重装。
"""
import asyncio
import json
import os

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tool-design", "api-impact-tool")
)
PYTHON = os.path.join(PROJECT_DIR, "venv", "bin", "python3")


def _log(direction: str, item) -> None:
    if isinstance(item, Exception):
        print(f"\n===== {direction}（异常，不是消息） =====\n{item!r}")
        return
    payload = item.message.model_dump(mode="json", exclude_none=True)
    print(f"\n===== {direction} =====")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


class ReadTap:
    """包一层read stream：每收到一条SessionMessage就先打印再原样交给ClientSession。"""

    def __init__(self, inner):
        self._inner = inner

    async def receive(self):
        item = await self._inner.receive()
        _log("← SERVER 返回", item)
        return item

    async def aclose(self):
        await self._inner.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.receive()

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._inner.__aexit__(*args)


class WriteTap:
    """包一层write stream：每发一条SessionMessage就先打印再原样发给子进程。"""

    def __init__(self, inner):
        self._inner = inner

    async def send(self, item):
        _log("→ CLIENT 发出", item)
        await self._inner.send(item)

    async def aclose(self):
        await self._inner.aclose()

    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._inner.__aexit__(*args)


async def main():
    params = StdioServerParameters(command=PYTHON, args=["server.py"], cwd=PROJECT_DIR)

    async with stdio_client(params) as (read, write):
        tapped_read, tapped_write = ReadTap(read), WriteTap(write)
        async with ClientSession(tapped_read, tapped_write) as session:
            print("\n########## 阶段一：initialize握手（对应1.3节的capabilities协商） ##########")
            await session.initialize()

            print("\n########## 阶段二：tools/list（对应1.4节时序图里的工具发现步骤） ##########")
            await session.list_tools()

            print("\n########## 阶段三：tools/call，故意传一个不合法的class_name ##########")
            print("（验证1.5节说的两层错误——这次触发的是Protocol Error还是Tool Execution Error）")
            result = await session.call_tool(
                "find_apis_affected_by_change",
                {"repo_name": "promotion-api", "class_name": "com.xxx.Foo", "method_name": "bar"},
            )
            print("\n----- call_tool()返回的CallToolResult（SDK已经帮我们解析成Python对象了） -----")
            print(f"is_error = {result.is_error}")
            print(f"content = {result.content}")


if __name__ == "__main__":
    asyncio.run(main())
