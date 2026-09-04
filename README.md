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

- [Turn Loop 设计](agent-loop/TurnLoop.md)（含"状态管理"相关概念，见文档内第3节——单独调研后判断这部分内容不足以撑起独立一章，并入了这里）
- [会话持久化](session-persistence/SessionPersistence.md)
- [Multi-Agent 编排](multi-agent-orchestration/MultiAgentOrchestration.md)
  - [子Agent终止条件](subagent-termination/SubagentTermination.md)
- [任务分解策略](task-decomposition/TaskDecomposition.md)

### Layer 4 — 可观测性

- 成本追踪
- OTel 集成
- 结构化日志
- Token 用量分析
- 分布式追踪
- Bug report机制

### Layer 5 — 工程化

- [Agent 测试策略](agent-testing-strategy/AgentTestingStrategy.md)（含Parity/快照测试——推导下来它是regression eval的一个具体子类型，不单独成章，内容并入"阶段三：跑评估、读结果"）
- [安全设计](security-design/SecurityDesign.md)
- [生产部署](production-deployment/ProductionDeployment.md)（目前只有从Multi-Agent编排一章顺带记的一条彩虹部署笔记，尚未正式开始学）
- 故障恢复策略