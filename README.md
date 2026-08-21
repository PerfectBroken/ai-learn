# Agent 工程师五层技能树

> 从 LLM 基础到工程化，对应三条职业路径

## 技能层级（自下而上）

### Layer 1 — LLM 基础

- [Transformer架构](transformer/Transformer.md)
- [Token 经济学](token-economics/TokenEconomics.md)
- [Context Window](context-window/ContextWindow.md)
- [Prompt Engineering](prompt-engineering/PromptEngineering.md)
- [采样参数](sampling-parameters/SamplingParameters.md)
- [Tool Calling](tool-calling/ToolCalling.md)

### Layer 2 — 工具系统

- [MCP 协议](mcp-protocol/MCPProtocol.md)
- [Tool Design](tool-design/ToolDesign.md)
- [Permission 系统](mcp-protocol/MCPProtocol.md#5-trust--safety权限与同意机制)
- [工具发现 / 注册](tool-discovery/ToolDiscovery.md)
- [错误语义设计](error-semantics/ErrorSemantics.md)
- [Skills](skills/Skills.md)

### Layer 3 — Agent 架构

- [Turn Loop 设计](agent-loop/TurnLoop.md)
- 状态管理
- 会话持久化
- Multi-Agent 编排
- 子 Agent 生命周期
- 任务分解策略

### Layer 4 — 可观测性

- 成本追踪
- OTel 集成
- 结构化日志
- Token 用量分析
- 分布式追踪

### Layer 5 — 工程化

- Agent 测试策略
- Parity / 快照测试
- 安全设计
- Prompt 注入防护
- 生产部署
- 故障恢复策略