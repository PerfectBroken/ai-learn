# Building agents with the Claude Agent SDK 学习笔记

原文作者Thariq Shihipar（编辑：Molly Vorwerck、Suzanne Wang等），发布于2025-09-29，地址 https://claude.com/blog/building-agents-with-the-claude-agent-sdk 。

**这篇文章在harness这条术语线里的位置**：目前查到的资料里，这是"agent harness"这个说法最早的一手使用记录——比Hashimoto的博客（2026-02-05）早了约4个半月，比OpenAI那篇《Harness engineering》（2026-02-11）早了约4个半月，比Anthropic自己给出正式定义句的那篇（2026-04-02）早了半年多。原句在"设计哲学"那节前面的过渡段：

> the agent harness that powers Claude Code (the Claude Code SDK) can power many other types of agents, too

**一处需要标注的不确定性**：这句话里"agent harness"这几个字带的超链接，指向的目标恰好是Anthropic 2026年4月那篇定义文章（`claude.com/blog/harnessing-claudes-intelligence`）——说明这个页面在发布之后至少被编辑过一次（补了一个指向后来文章的链接）。因为我这边访问不了Wayback Machine去核对2025年9月的原始快照，没法100%确认"agent harness"这几个字本身是不是2025年9月发布时就有、还是后来编辑时一并加上去的。这个"最早使用"的判断，建立在信任当前页面版本的基础上，不是铁证，需要保留这个不确定性。

本笔记不逐字翻译，是转述论证逻辑和具体例子，关键短句原文引用会用引用块标出。

## 目录

- [1 背景：从Claude Code SDK改名为Claude Agent SDK](#1-背景从claude-code-sdk改名为claude-agent-sdk)
- [2 设计哲学：给Claude一台电脑](#2-设计哲学给claude一台电脑)
- [3 可以构建的agent类型](#3-可以构建的agent类型)
- [4 Agent反馈循环：收集上下文→采取行动→验证工作→重复](#4-agent反馈循环收集上下文采取行动验证工作重复)
- [5 测试与改进agent](#5-测试与改进agent)
- [6 结语：快速上手](#6-结语快速上手)

## 1 背景：从Claude Code SDK改名为Claude Agent SDK

Anthropic在这篇文章里正式把Claude Code SDK改名为Claude Agent SDK。理由是：Claude Code最初是为写代码设计的，但过去几个月里，Anthropic内部已经把它用在深度研究、视频制作、记笔记等一大堆非编程场景上，甚至开始驱动公司内部几乎所有的主要agent循环——既然驱动Claude Code的这套底层机制（也就是那句"agent harness"）本来就能驱动其他很多类型的agent，改名是为了反映这个更广的定位。

## 2 设计哲学：给Claude一台电脑

核心设计原则：**Claude需要跟程序员每天用的同一套工具**——在代码库里找文件、写文件、改文件、跑lint、执行、调试，必要时反复迭代直到代码跑通。给Claude接入用户的终端（computer access）之后，它就有了像程序员一样写代码所需的条件。

但这套能力顺带也让Claude在**非编程任务**上表现出色：只要给它跑bash命令、编辑文件、创建文件、搜索文件的工具，它就能读CSV、搜网页、做可视化、解读指标——本质是"给它一台电脑"，让它能像人一样干活。这也是Claude Agent SDK的核心设计原则：给你的agent一台电脑，让它像人一样工作。

## 3 可以构建的agent类型

文章列了四类示例，说明"给一台电脑"这个原则能解锁的agent类型：

- **金融agent**：理解你的投资组合和目标，调用外部API、存数据、跑计算帮你评估投资；
- **个人助理agent**：订travel、管理日历、排日程、整理简报，靠连接内部数据源、跨应用追踪上下文；
- **客服agent**：处理高歧义的用户请求（比如工单），收集/审核用户数据、调外部API、必要时升级给人工；
- **深度研究agent**：跨大量文档做调研，检索文件系统、多来源综合分析、生成详细报告。

SDK给的是构建这类agent的基础组件，具体能自动化什么工作流由开发者自己定。

## 4 Agent反馈循环：收集上下文→采取行动→验证工作→重复

Claude Code里Claude的运作方式通常遵循一个固定循环：**收集上下文 → 采取行动 → 验证工作 → 重复**。文章用一个假想的"邮件agent"贯穿举例，逐段拆这四步该怎么落地。

### 4.1 收集上下文

**Agentic search + 文件系统**：文件系统里的内容代表"可能被拉进模型上下文"的信息。遇到大文件（日志、用户上传的文件）时，Claude会自己判断用`grep`、`tail`这类bash脚本去加载需要的部分——文件夹/文件结构本身就是一种上下文工程。邮件agent的例子：把历史对话存进一个"Conversations"文件夹，需要时自己去搜。

**语义检索**：比agentic search快，但准确度更低、更难维护、透明度更差（把上下文切块、embedding成向量、按概念查询）。建议先用agentic search，只有确实需要更快或更多变体时再加语义检索。

**子agent**：Claude Agent SDK默认支持，价值有两个——一是**并行化**（同时起多个子agent处理不同任务），二是**管理上下文**（子agent用自己独立的上下文窗口，只把相关信息传回主orchestrator，不传全部上下文），最适合"要在大量信息里筛出少量有用内容"的任务。邮件agent的例子：给它一个"搜索子agent"能力，并行跑多个查询，只返回相关摘录而不是整段邮件。

**压缩（Compaction）**：agent长时间运行时，上下文维护很关键。SDK的compact功能会在接近上下文上限时自动总结之前的消息，防止agent耗尽上下文——这是基于Claude Code的`/compact`斜杠命令做的。

### 4.2 采取行动

**Tools**：agent执行动作的主要构件，在Claude的上下文窗口里很显眼，是它决定怎么完成任务时首先会考虑的选项，所以设计工具时要有意识地追求上下文效率。邮件agent的例子：定义`fetchInbox`、`searchEmails`这类作为agent最主要、最高频的动作。

**Bash与脚本**：给agent一种灵活的通用计算能力。邮件agent的例子：让Claude写代码下载PDF附件、转文本、搜索里面的内容。

**代码生成**：SDK特别擅长这个，因为代码精确、可组合、可无限复用，适合需要可靠完成复杂操作的agent。文中举了Claude.AI的文件创建功能——完全靠代码生成实现，Claude写Python脚本生成Excel、PowerPoint、Word文档，保证格式一致、功能复杂度也能达到。邮件agent的例子：用代码实现"给收到的邮件设规则"这类需求。

**MCP**：提供Slack、GitHub、Google Drive、Asana这类标准化集成，自动处理鉴权和API调用，不用自己写集成代码或管OAuth流程。邮件agent的例子：直接调`search_slack_messages`、`get_asana_tasks`这类现成工具去理解团队上下文、确认某个客服请求是不是已经有人在处理。

### 4.3 验证工作

**定义规则**：最好的反馈形式，是给出明确规则，再告诉agent哪条规则失败了、为什么。**代码检查（lint）就是这类"基于规则反馈"的一个好例子**——文中特别提到，生成TypeScript再lint，通常比直接生成纯JavaScript更好，因为能拿到更多层反馈。邮件agent的例子：校验邮箱地址是否合法（不合法直接报错），检查是否给这个人发过邮件（发过则给警告）。

**视觉反馈**：适合UI生成/测试这类视觉任务——生成带HTML格式的邮件后，截图回传给模型做视觉核对和迭代，检查布局定位、样式、内容层次、响应式效果是否正确。可以用Playwright这类MCP server自动化整个截图-反馈循环。

**LLM评判**：让另一个语言模型基于模糊规则去评判agent输出的质量。文中坦言这个方法**不太鲁棒、延迟也高**，只在"哪怕一点点性能提升都值得付出这个成本"的场景才值得用。邮件agent的例子：用一个独立子agent评判草稿的语气是否跟用户以往的消息风格一致。

## 5 测试与改进agent

建议走完几轮agent循环之后就开始测试，重点看失败案例，站在agent的角度反问"它有没有配到位的工具"。文中给了四个具体的自查问题：

- agent理解错任务？→ 可能缺关键信息，考虑调整搜索API的结构，让它更容易找到需要的信息；
- agent反复在同一个任务上失败？→ 考虑在工具调用里加一条正式规则去识别并修复这个失败模式；
- agent没法自己纠错？→ 考虑给它更有用、或者更有创造性空间的工具，换个角度解决问题；
- agent表现随功能增加而波动？→ 基于真实客户使用场景，搭一套有代表性的测试集做程序化评估（evals）。

## 6 结语：快速上手

Claude Agent SDK通过给Claude接入一台能写文件、跑命令、迭代自己工作的电脑，降低了构建自主agent的门槛。围绕"收集上下文、采取行动、验证工作"这个循环去设计，就能构建出可靠、易于部署和迭代的agent。已经在用旧版SDK的开发者建议按迁移指南升级。

## 参考资料

- Thariq Shihipar, *Building agents with the Claude Agent SDK*, Anthropic, 2025-09-29, https://claude.com/blog/building-agents-with-the-claude-agent-sdk
