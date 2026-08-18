"""用MCP官方client SDK的高层API（ClientSession.list_tools()），连接本地一个真实的
MCP server（tool-design/api-impact-tool/server.py），看SDK解析好之后交给调用方的
Tool对象长什么样——这是"SDK视角"，对应raw_jsonrpc_trace.py里"协议原始报文视角"的
另一面，两者数据是同一份，只是抽象层级不同。

复习时想快速确认"某个工具最终暴露给Agent的description/input_schema长什么样"，
用这个脚本比翻官方文档的示例更直接：这是你自己项目里的真实工具，不是抽象例子。

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


async def main():
    params = StdioServerParameters(
        command=PYTHON,
        args=["server.py"],
        cwd=PROJECT_DIR,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            for tool in result.tools:
                # model_dump()拿到的是这个MCP工具在协议层被序列化成的、
                # Agent实际能看到的完整数据结构——不是Python对象repr
                payload = tool.model_dump(exclude_none=True)
                print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
