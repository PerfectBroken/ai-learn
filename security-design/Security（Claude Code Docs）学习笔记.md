# Security（Claude Code Docs）学习笔记

来源：Claude Code官方文档，Security页，地址 https://code.claude.com/docs/en/security 。本笔记不逐字翻译，是转述内容结构和关键机制，关键短句用引用块标出。

**这篇在本章的位置**：这不是一篇工程博客，是**产品文档**——本质上是把前面三篇工程博客（sandboxing、how-we-contain-claude、auto-mode）里讲的机制，浓缩成一份"作为Claude Code用户，你实际能配置、能看到的安全功能清单"。读法应该反过来：前面三篇讲的是"为什么这么设计、付出了什么代价"，这篇讲的是"这些设计最终变成了哪些具体的开关、命令、设置项"——是这一章从"原理"落到"产品功能"的最后一环。

## 目录

- [1 我们如何看待安全](#1-我们如何看待安全)
- [2 防范Prompt注入](#2-防范prompt注入)
- [3 MCP安全](#3-mcp安全)
- [4 IDE安全](#4-ide安全)
- [5 云端执行安全](#5-云端执行安全)
- [6 安全最佳实践](#6-安全最佳实践)
- [7 值得记的点](#7-值得记的点)
- [8 跟OWASP Top 10 for Agentic Applications的对应关系](#8-跟owasp-top-10-for-agentic-applications的对应关系)
- [参考资料](#参考资料)

## 1 我们如何看待安全

**安全基础**：Claude Code按Anthropic自己的综合安全项目开发，SOC 2 Type 2报告、ISO 27001认证这类资质可以在[Anthropic Trust Center](https://trust.anthropic.com/)查到。

**基于权限的架构**——这一段基本是auto-mode笔记里"三层权限判定结构"的产品化说明：

- **Manual模式**（人工审批模式）：默认只读，改文件/跑测试/执行命令之前都会先问；内置一份免问的只读命令白名单（`ls`、`cat`、`git status`等），用户和组织可以直接配置这些权限规则。
- **Auto模式**：由一个独立的分类器模型代替用户审查动作、拦下它判定不安全的操作——具体"哪些动作直接放行、哪些送去给分类器、哪些依然会问用户"，文档专门链接到auto-mode文档里"分类器怎么评估动作"这一节。用户自己写的allow/deny规则依然优先生效，组织可以整体关掉auto模式。
- 一个session到底从哪个模式启动，取决于订阅计划、启动入口、以及用户/组织自己的设置。

**内置防护**（四条，逐条对应之前学过的具体机制）：

- **沙箱化的bash工具**：文件系统+网络隔离，用`/sandbox`命令定义Claude可以自主活动的边界——这正是sandboxing那篇讲的机制，这里变成了一个具体命令。
- **工作目录边界**：Manual模式下，Claude Code只能写入启动时所在的文件夹及其子文件夹，改动父目录之外的文件需要显式许可；用Read/Grep/Glob读取边界之外的路径也会先问——**但在auto模式下，读取这些路径不会问**，这是一个很值得记的细节：auto模式放宽的不只是"要不要执行危险操作"，也包括"要不要读边界外的东西"。可以用`sandbox denyRead`规则收紧只读Bash命令能读到的范围（仅在开启沙箱时生效）。
- **审批疲劳缓解**：支持按用户/按代码库/按组织给常用安全命令加白名单。
- **Accept Edits模式**：自动批准文件编辑，以及工作目录内一组固定的文件系统类Bash命令（`mkdir`、`touch`、`rm`、`mv`、`cp`、`sed`），其余Bash命令和边界外路径依然会问——这是介于Manual和Auto之间的第三种粒度。

**用户责任**：

> Claude Code only has the permissions you grant it. You're responsible for reviewing proposed code and commands for safety before approval.

翻译：Claude Code只拥有你授予它的权限，审查建议的代码和命令是否安全，责任在用户自己——这句话把"权限系统再完善，最终决策权和责任都在人"这条原则明确写进了产品文档。

## 2 防范Prompt注入

开篇给了prompt injection一个简明定义：攻击者插入恶意文本，试图覆盖或操纵AI助手的指令。

**核心防护**（四条）：

- **权限系统**：Manual模式下敏感操作需要显式批准。
- **上下文感知分析**：通过分析完整请求来检测潜在有害指令。
- **输入净化**：处理用户输入以防止命令注入。
- **网络命令审批**：`curl`、`wget`这类拉取网络内容的命令**默认不会自动批准**——Manual模式下它们跟其他非只读Bash命令一样要问，用户可以选择批准一次或加一条显式allow规则（比如`Bash(curl *)`），也可以把它们直接加进`permissions.deny`彻底封死。

**隐私保障**：敏感信息的留存期限有限制（具体天数见Privacy Center）、用户session数据访问受限、用户可以自己控制数据是否用于训练（Consumer用户可以在隐私设置里随时改）。

**额外防护**（八条，是这一节篇幅最长的部分）：

- **网络请求审批**：Manual模式下，大多数发起网络请求的工具默认都需要用户批准。
- **隔离的上下文窗口**：Web fetch用一个独立的上下文窗口，避免抓到的内容里的恶意prompt直接混进主对话——这跟auto-mode笔记里"剥离工具结果"是同一个思路的另一种实现，只是这里是物理隔离出一个单独的上下文，而不是分类器读不到。
- **信任验证**：第一次跑某个代码库、或者接入新的MCP server都需要过一次信任验证。**两个例外要记住**：用`-p`标志非交互运行时，信任验证是关掉的；如果直接在home目录启动Claude Code，信任接受只在当前session内有效、不会写盘，每次启动都要重新确认——没有办法持久化这一条，正确做法是从项目子目录启动，信任状态才会按目录保存到磁盘。
- **命令注入检测**：Manual模式下，即便一条命令之前已经被加入白名单，只要这次调用看起来可疑，依然需要手动批准。
- **失败即拒绝（fail-closed）匹配**：Manual模式下，没有匹配上任何规则的命令，默认需要审批（不是默认放行）。
- **自然语言描述**：复杂的bash命令会带一段解释，方便用户理解它到底要做什么。
- **凭证安全存储**：API key和token在macOS上存进Keychain，在Windows/Linux上靠文件权限保护。

**跟不可信内容打交道的最佳实践**（五条）：审查建议的命令再批准；不要把不可信内容直接管道输给Claude；核实对关键文件的改动；跟外部网络服务交互时优先用虚拟机跑脚本和工具调用；用`/feedback`上报可疑行为。

## 3 MCP安全

允许配置的MCP server清单本身是写进源码里的（作为Claude Code设置的一部分，纳入版本控制）。官方建议要么自己写MCP server，要么只用信任的provider的MCP server；用户可以为MCP server单独配置权限。Anthropic会按自己的[审核标准](https://claude.com/docs/connectors/building/review-criteria)审核连接器之后才收进[Anthropic Directory](https://claude.ai/directory)，但**不会**对任何MCP server做安全审计或托管维护——这句话呼应了contain-claude笔记里"经过审计的连接器不等于经过审计的数据"这个区分：目录审核的是准入资格，不是持续的安全保证。

## 4 IDE安全

只有一句指路：在IDE里跑Claude Code的安全和隐私细节，去看VS Code安全和隐私那篇文档，这里不展开。

## 5 云端执行安全

跑[Claude Code on the web](https://code.claude.com/docs/en/claude-code-on-the-web)时，有额外的安全控制，具体分两种情况：

**路由到自建（self-hosted）环境的session**：跑在用户自己的基础设施上，隔离、出站网络、git凭证这些都是用户自己部署的责任，不是Anthropic管。

**Anthropic托管的环境**（六条）：

- **隔离的虚拟机**：每个云端session跑在一个独立的、Anthropic托管的VM里。
- **网络访问控制**：默认限制网络访问，可以配置成完全禁用或只放行特定域名。
- **凭证保护**：认证通过一个安全代理处理，代理在沙箱内部用一个限定范围的凭证，再转换成用户真实的GitHub认证token——这正是sandboxing笔记里"Claude Code on the web"那套代理机制的产品化描述。
- **分支限制**：git push操作被限制在当前工作分支。
- **审计日志**：云端session里的所有操作都会记录，供合规和审计使用。
- **自动清理**：session VM在闲置一段时间后会被回收。

**Remote Control**（这是文档里专门拎出来强调"跟云端session不是一回事"的一种模式）：web界面连接的是跑在用户本地机器上的Claude Code进程——**代码执行和文件访问都留在本地**，session流量通过Anthropic API走TLS传输；连接期间，对话记录会存在Anthropic服务器上用来跨设备同步，但这不涉及任何云端VM或沙箱。这个连接用多个短生命周期、窄范围的凭证，各自限定用途、独立过期，来限制单个凭证被攻陷后的爆炸半径——这跟contain-claude笔记里Claude Cowork"session范围收窄+可独立撤销的token"是同一个设计思路。

## 6 安全最佳实践

**跟敏感代码打交道**：审查所有建议的改动再批准；给敏感仓库用项目专属的权限设置；考虑用dev container做额外隔离；用`/permissions`定期审计权限设置。

**团队安全**：用managed settings强制执行组织标准；通过版本控制分享已批准的权限配置；给团队成员做安全最佳实践培训；通过OpenTelemetry指标监控Claude Code使用情况；用`ConfigChange` hook在session期间审计或阻止设置变更。

**报告安全问题**：发现漏洞不要公开披露，通过HackerOne项目提交，附详细复现步骤，留时间让官方先修复再公开。

文档末尾还链接了一批相关资源，没有展开讲，值得记一下有哪些：安全指导插件（让Claude在session里审查并修复自己代码改动里的漏洞）、`/security-review`命令（对当前分支的改动跑一次按需安全扫描）、沙箱环境对比、Sandboxing、Permissions、Monitoring usage、Development containers、Anthropic Trust Center、以及一篇专门给CISO写的《agentic AI框架评估指南》。

## 7 值得记的点

- **这篇文档最大的价值是"验证"，不是"新信息"**——读完会发现，前面三篇工程博客里讲的几乎每一个机制，都能在这份文档里找到一个对应的产品开关或设置项：沙箱化bash工具、分类器审批、工具结果隔离上下文、凭证不进沙箱靠代理转换……原理和产品是完全对得上号的，说明这一章读的不是几篇互相独立的文章，是同一套安全架构在"设计动机"和"最终形态"两个层面的两次呈现。
- **一个之前三篇工程博客都没提到的新细节**：auto模式下，读取工作目录边界外的路径**不会**触发审批，Manual模式下才会问——这意味着auto模式放宽的范围比"要不要执行危险操作"更大，连"要不要读什么"这个更基础的边界也一起放宽了，是理解auto模式实际风险面时容易漏掉的一点。
- **"信任验证在home目录不会持久化"这个例外**，直接呼应了contain-claude笔记里"漏掉的风险①"讲的那类问题（本地配置在信任建立之前被解析执行）——官方选择了"宁可让用户每次都重新确认，也不把home目录的信任状态写盘"，是一个具体的、保守方向的产品决策。
- **MCP安全那一节明确划清了责任边界**："收进目录"只代表通过了准入审核，不代表Anthropic持续审计或托管这个server——用户自己引入的MCP server，安全责任始终在用户自己身上。

## 8 跟OWASP Top 10 for Agentic Applications的对应关系

这篇文档是把前面三篇的机制打包成产品功能，能对上号的ASI类目基本是sandboxing（ASI02/05/10/03）、auto-mode（ASI01/02/05/10）、contain-claude（ASI02/03/05/06/10）这三篇已经覆盖过的类目的并集，没有引入新的类目覆盖——因为它本身不是一篇有新论证或新案例的文章，是文档化已有机制，所以这里不重新逐条打分，直接沿用前几篇笔记已经给出的评分即可，重复列一遍表格意义不大。真正新增的信息量在"云端执行安全"和"Remote Control"这两节，跟contain-claude笔记里"claude.ai临时容器"和"Claude Cowork session-scoped token"两个机制是同一件事在产品文档里的具体落地，不构成新的ASI覆盖类目。

## 参考资料

- Claude Code Docs, *Security*, https://code.claude.com/docs/en/security
