# 安全设计

## 目录

- [本章学习材料](#本章学习材料)
- [防护方法总览（跨文章去重汇总）](#防护方法总览跨文章去重汇总)
- [参考资料](#参考资料)

## 本章学习材料

先读的是行业标准，再按"公司怎么把标准落地成具体机制"的顺序读了六篇工程/产品文档：

1. [OWASP Top 10 for Agentic Applications 2026 学习笔记](<OWASP Top 10 for Agentic Applications 2026 学习笔记.md>)——十条风险的统一分类框架（ASI01-10），后面几篇的落地机制全部对照这份taxonomy打分
2. [Making Claude Code more secure and autonomous with sandboxing（Anthropic）学习笔记](<Making Claude Code more secure and autonomous with sandboxing（Anthropic）学习笔记.md>)——沙箱化bash工具+凭证代理，最先落地的两个具体机制
3. [How we contain Claude across products（Anthropic）学习笔记](<How we contain Claude across products（Anthropic）学习笔记.md>)——三条产品线（claude.ai/Claude Code/Claude Cowork）的容纳架构对比+四个真实事故复盘
4. [How we built Claude Code auto mode（Anthropic）学习笔记](<How we built Claude Code auto mode（Anthropic）学习笔记.md>)——两层防御（输入层探针+输出层推理盲分类器）的完整实现细节，本章信息量最大的一篇
5. [Security（Claude Code Docs）学习笔记](<Security（Claude Code Docs）学习笔记.md>)——把前三篇的机制打包成产品功能和设置项
6. [Safety in building agents（OpenAI）学习笔记](<Safety in building agents（OpenAI）学习笔记.md>)——已精简，只保留"developer消息隔离"和"结构化输出"两条真正有信息量的建议
7. [Safety and Security for AI Agents（Google ADK）学习笔记](<Safety and Security for AI Agents（Google ADK）学习笔记.md>)——本章唯一给出可运行代码的一篇，`in-tool guardrails`把"结构化输出约束数据流"从概念落到了代码

## 防护方法总览（跨文章去重汇总）

按机制去重，不按文章罗列。ASI标注严格按照本章已经跑过的三张打分表（contain-claude/auto-mode/ADK的OWASP对应关系表）和sandboxing笔记的定性结果，只标**>5分**的；没有正式打过分的机制如实注明，不硬凑。

| 防护方法 | 实现方式 | 解决的ASI（>5分） |
|---|---|---|
| 执行沙箱隔离 | 用OS级原语（bubblewrap/seatbelt/gVisor/完整VM）圈住agent能碰到的文件系统和网络范围，文件系统隔离+网络隔离缺一不可，单独一层都能被绕过 | ASI02、ASI03、ASI05 |
| 出站网络白名单/代理 | 只放行批准过的域名/服务，中间人代理只认自己签发的session token；教训是把白名单当成"能力授权"而非单纯的目的地过滤器 | ASI02、ASI05 |
| 凭证代理（凭证不进沙箱） | 真实凭证永远留在可信环境外，agent只拿限定范围、可独立撤销的临时token，敏感操作由代理层校验后代为签发/转换 | ASI03、ASI10 |
| 输入层prompt-injection探针 | 工具输出（文件/网页/shell/外部响应）进入上下文前先扫描，命中可疑模式就附加警告，提醒agent把这段内容当可疑数据、不当指令 | ASI01、ASI06 |
| 输出层推理盲分类器 | 只看用户消息+工具调用，剥离assistant文字和工具结果，防止agent用话术说服分类器、也防止被注入内容间接操纵；两阶段（快筛+精判）平衡成本和召回 | ASI01、ASI02、ASI05、ASI10 |
| 确定性in-tool policy校验 | 开发者预设policy（允许的表/字段/阈值），工具执行前用它校验模型生成的参数，不理解语义只核对结构化事实，模型判断力被骗也不受影响 | ASI01、ASI02、ASI10 |
| Agent-Auth/User-Auth身份分层 | 工具用agent自己的服务账号（需配日志留归因）或用户委托的token（只能做用户自己能做的事）跟外部系统交互，按场景选择或组合 | ASI03 |
| Deny-and-continue断路器 | 动作被拦截时不直接打断会话，把拒绝当工具结果还给agent、附带善意重试提示，累计3次连续或20次总拒绝才升级人类或终止进程 | ASI10 |
| Callback/Plugin安全策略层 | Before Tool Callback做单agent一次性校验；Plugin（如用小模型评估注入/越狱倾向）在runner层全局生效，一次配置覆盖所有agent | ASI01 |

**以下四条也在本章出现过，但没有跨过>5分门槛或从未被正式打分，如实列出、不计入上表**：

- **多agent双检查点**（auto-mode，委派+回程各跑一次分类器）——对应ASI03/07都卡在5分，未达标
- **消息角色优先级隔离、结构化输出约束数据流（概念层）**（OpenAI精简笔记）——全篇未跑ASI打分
- **信任验证/延迟解析**（Claude Code Docs，本地配置解析推迟到信任提示之后）——未跑正式打分，概念上呼应contain-claude的ASI04但该条本身评分4分未达标
- **Session/租户级记忆隔离**（本章讨论中针对ASI06补充的方案）——未跑正式打分

**目前整章唯一完全空白的两条**：ASI08（级联故障，官方十条建议里七条不占运行时开销、三条用的是已验证的分级放行模式，但七篇材料里没有一篇给出跨agent级联本身的专门机制）、以及ASI07的**协议层/密码学层**认证（PKI证书pinning、消息签名、防重放——`multi-agent-orchestration`那一章也确认完全没涉及，是整个学习路线图目前唯一的空白，不只是这一章的疏漏）。

## 参考资料

- OWASP GenAI Security Project, *OWASP Top 10 for Agentic Applications 2026*, 2025-12-09（用户提供的PDF，CC BY-SA 4.0）

Anthropic：
- David Dworken, Oliver Weller-Davies, *Making Claude Code more secure and autonomous with sandboxing*, 2025-10-20, https://www.anthropic.com/engineering/claude-code-sandboxing
- Max McGuinness, Mikaela Grace, Jiri De Jonghe, Jake Eaton, Abel Ribbink, *How we contain Claude across products*, 2026-05-25, https://www.anthropic.com/engineering/how-we-contain-claude
- John Hughes, *How we built Claude Code auto mode: a safer way to skip permissions*, 2026-03-25, https://www.anthropic.com/engineering/claude-code-auto-mode
- Claude Code Docs, *Security*, https://code.claude.com/docs/en/security

OpenAI：
- *Safety in building agents*（Agent Builder已废弃，定于2026-11-30下线；现役等价页面是Agents SDK下的Guardrails），https://platform.openai.com/docs/guides/agent-builder-safety

Google：
- *Safety and Security for AI Agents*, Agent Development Kit (ADK) Docs, https://adk.dev/safety/
