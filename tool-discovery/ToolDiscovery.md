# 工具发现 / 注册

**结论：这个话题不需要单独展开——内容已经被另外两章合起来学完了，这里只做索引。**

一开始以为"工具发现/注册"要么该并入MCP协议章节，要么是MCP没覆盖到的独立缺口，实际核实下来是第三种情况：这个话题被拆成了两个层次，分别已经在两章里写过了，合起来就是完整的。

## 层次一：协议层的发现机制——MCP怎么发现工具

单个MCP Server连上之后，Client怎么知道它有哪些工具、工具集变化了怎么通知——这是MCP协议本身定义的发现机制（`tools/list`请求、`notifications/tools/list_changed`通知）。

→ [MCPProtocol.md 1.4 时序图：Agent与MCP Server的完整交互](../mcp-protocol/MCPProtocol.md#14-时序图agent与mcp-server的完整交互)（时序图里"①建立连接阶段做server/discover和tools/list完成能力与工具发现"）

→ [MCPProtocol.md 1.6 实测脚本：用真实JSON-RPC报文验证上面几节](../mcp-protocol/MCPProtocol.md#16-实测脚本用真实json-rpc报文验证上面几节)（`raw_jsonrpc_trace.py`抓的就是`tools/list`的真实报文）

## 层次二：规模化场景下的发现机制——工具太多了怎么办

单个Server的工具发现解决不了"Agent聚合了几十上百个工具、模型选错/context被工具定义吃满"这个问题。这是Claude API层面的问题，跟MCP协议本身没有直接关系，属于上下文工程的范畴——`tools`字段本身就是要装进context window的协议字段之一，工具选择本质是"Select"这一步在决定该把哪些工具定义塞进窗口。

→ [ContextWindow.md 2.3.2 Select：Agent能读到哪些长期记忆和便签 → "Tools的选择"](../context-window/ContextWindow.md#tools的选择)（对比了Anthropic Tool Search Tool、langgraph-bigtool的`retrieve_tools`、OpenClaw的`tool_search`三种同类方案的具体实现差异，包括`defer_loading`怎么在Claude API服务器端排除token、以及对prompt caching的影响）

## 后续

如果之后遇到MCP多Server聚合时的命名空间冲突/工具注册管理这类新内容（目前只在[ToolDesign.md 3.2 命名空间划分](../tool-design/ToolDesign.md)里提过一点，没有展开成完整机制），再回来这份文档补一节，不需要新开一章。
