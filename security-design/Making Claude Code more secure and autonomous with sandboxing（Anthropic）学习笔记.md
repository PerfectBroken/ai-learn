# Making Claude Code more secure and autonomous with sandboxing 学习笔记

来源：Anthropic官方工程博客，作者David Dworken、Oliver Weller-Davies，发布于2025-10-20，地址 https://www.anthropic.com/engineering/claude-code-sandboxing 。本笔记不逐字翻译，是转述机制和设计逻辑，关键短句用引用块标出。

**这篇在本章的位置**：跟OWASP那份Top 10不一样，那份讲的是"agent系统里存在哪些风险类别"，这篇讲的是**一家公司具体怎么给自己的编程agent产品做安全加固**——是一份对得上号的工程实现案例，尤其直接对应OWASP清单里的**ASI05（意外代码执行）**和**ASI02（工具滥用与利用）**：Claude Code本来就会执行命令、改文件，这篇讲的正是怎么把这类操作圈进一个安全的边界里。

## 目录

- [1 问题：权限提示太多，会导致"审批疲劳"](#1-问题权限提示太多会导致审批疲劳)
- [2 沙箱化方案：文件系统隔离+网络隔离](#2-沙箱化方案文件系统隔离网络隔离)
- [3 具体实现一：Sandboxed bash tool](#3-具体实现一sandboxed-bash-tool)
- [4 具体实现二：Claude Code on the web](#4-具体实现二claude-code-on-the-web)
- [5 跟OWASP Top 10 for Agentic Applications的对应关系](#5-跟owasp-top-10-for-agentic-applications的对应关系)
- [6 值得记的点](#6-值得记的点)

## 1 问题：权限提示太多，会导致"审批疲劳"

Claude Code默认跑在一套基于权限的模型上：默认只读，修改文件或跑命令之前要先申请权限（有少数例外，比如`echo`、`cat`这类公认安全的命令会被自动放行，但大多数操作依然需要显式批准）。

这套模型的问题原文点得很直接：

> Constantly clicking "approve" slows down development cycles and can lead to 'approval fatigue', where users might not pay close attention to what they're approving, and in turn making development less safe.

翻译：不停地点"批准"会拖慢开发节奏，还会导致"审批疲劳"——用户点多了容易不再仔细看自己到底在批准什么，反而让开发变得**更不**安全。这是一个很值得记的反直觉结论：**权限提示这个机制本身，如果用得太频繁，会从"安全措施"变成"安全隐患"**——不是加的确认越多越安全，是加的确认太多、太琐碎，用户会开始盲目点通过。

## 2 沙箱化方案：文件系统隔离+网络隔离

Anthropic给出的解法不是"减少确认的频率"，是**换一种边界设计思路**——沙箱化：预先定义好一片Claude可以自由活动的边界，边界之内不用逐个操作申请权限，边界之外照常拦截确认。原文给了一个具体数字：

> In our internal usage, we've found that sandboxing safely reduces permission prompts by 84%.

内部实测权限提示减少了84%，而且是"安全地"减少——不是靠放宽标准换来的减少。

沙箱化建立在操作系统级别的能力之上，实现两层边界：

1. **文件系统隔离**：确保Claude只能访问或修改指定的目录。这一层专门用来防止一个被prompt注入攻陷的Claude去改动敏感的系统文件。
2. **网络隔离**：确保Claude只能连接到批准过的服务器。这一层专门用来防止一个被prompt注入攻陷的Claude泄露敏感信息、或者下载恶意软件。

原文特别强调了一句很关键的设计原则——**这两层缺一不可，必须同时具备**：

> Without network isolation, a compromised agent could exfiltrate sensitive files like SSH keys; without filesystem isolation, a compromised agent could easily escape the sandbox and gain network access.

翻译：没有网络隔离，被攻陷的agent能把SSH密钥这类敏感文件外泄出去；没有文件系统隔离，被攻陷的agent能轻易逃出沙箱、拿到网络访问权限。**这跟我们之前读的OWASP Top 10里"ASI05意外代码执行"和"ASI02工具滥用"的防护建议高度一致**——单独一层隔离都留有绕过空间，两层叠加起来才真正把攻陷影响圈死在沙箱内部。

## 3 具体实现一：Sandboxed bash tool

第一个具体功能是**沙箱化的bash工具**，目前以研究预览版（beta）形式提供，也开源了独立的sandbox runtime（`anthropic-experimental/sandbox-runtime`），可以用来给任意进程、agent、MCP server做沙箱化，不只是Claude Code专属。

**底层实现**：建立在操作系统级别的原语之上——Linux用[bubblewrap](https://github.com/containers/bubblewrap)，macOS用seatbelt——在操作系统层面强制这些限制，覆盖的不只是Claude Code自己直接发起的操作，还包括命令衍生出的任何脚本、程序、子进程。

**两层边界的具体落地方式**：

1. **文件系统隔离**：允许对当前工作目录做读写访问，但阻止修改目录之外的任何文件。
2. **网络隔离**：只允许通过一个连接到代理服务器的unix域套接字访问互联网，这个代理服务器跑在沙箱**外部**，负责限制进程能连接的域名，并且处理"新请求的域名要不要放行"这个用户确认流程。如果需要更高的安全性，这个代理本身还支持自定义，可以对出站流量强制任意规则。

两个组件（文件系统边界、网络边界）都是可配置的，可以自由选择允许或禁止特定的路径或域名。

**这套机制带来的实际安全效果**：即便一次prompt injection攻击成功了，影响也被完全隔离住，不会波及整体用户安全——原文举的具体例子是"一个被攻陷的Claude Code没法偷走你的SSH密钥，也没法给攻击者的服务器打电话"。

## 4 具体实现二：Claude Code on the web

第二个功能是**Claude Code on the web**，让用户能在云端一个隔离的沙箱里跑Claude Code——每个session都在自己独立的沙箱里执行，这个沙箱能完整访问自己的服务器，但访问方式是安全可控的。

**一个特别的设计点**：这套沙箱专门设计成**敏感凭证（比如git凭证或签名密钥）永远不会进入沙箱内部**，跟Claude Code共存——这样即便沙箱里跑的代码被攻陷了，用户依然是安全的，不会有更进一步的损害。

**具体机制**：用一个自定义的代理服务，透明地处理所有git交互。沙箱内部，git客户端用一个专门构建的、限定范围的凭证，向这个代理服务做认证；代理服务校验这个凭证、以及这次git交互的具体内容（比如确保这次操作只会推送到配置好的那个分支），校验通过后才会附上正确的认证token，再把请求发给GitHub——**Claude Code自己从始至终都拿不到真正能直接操作GitHub的凭证**，凭证和实际操作之间始终隔着这一层代理做校验。

## 5 跟OWASP Top 10 for Agentic Applications的对应关系

对照《OWASP Top 10 for Agentic Applications 2026 学习笔记.md》逐条核对下来，Claude Code的沙箱功能能直接对上号的是四条，集中在"执行/工具/凭证"这几个跟沙箱机制天然相关的类别，跟"输入怎么被污染""agent之间怎么互相欺骗""人类怎么被说服"这类问题没有关系，那几条需要完全不同的机制去解决。

**直接对上的两条**：

- **ASI05（Unexpected Code Execution）**——OWASP笔记里的防护建议原话是"执行环境永远不用root权限跑，代码放进带严格网络访问限制的沙箱容器里"，Claude Code的sandboxed bash tool做的正是这件事：文件系统隔离（只能读写当前工作目录）+网络隔离（只能通过代理连白名单域名），底层用Linux bubblewrap/macOS seatbelt在操作系统层强制。这是匹配度最高的一条。
- **ASI02（Tool Misuse and Exploitation）**——OWASP笔记里的防护建议"Execution Sandboxes and Egress Controls：把工具/代码执行放进隔离沙箱，强制出站白名单，拒绝所有未批准的网络目的地"，跟Claude Code沙箱的设计几乎是同一句话的两种写法。bash工具是agent最主要的"工具"，沙箱把它能做的事圈死在预定义边界内。

**通过"凭证代理"这个具体设计点对上的两条**：

- **ASI10（Rogue Agents）**——OWASP笔记原话是"密钥绝不能直接暴露给agent，要由编排层来代理签名操作，防止被攻陷的agent直接外泄或滥用长期有效的密钥"。Claude Code on the web的git代理服务就是这条建议的具体实现：git凭证永远不进沙箱，Claude Code自己拿不到能直接推送代码的真实token，代理服务代它做认证和校验。
- **ASI03（Identity and Privilege Abuse）**——防护建议里的"Just-in-Time and Ephemeral Access：即时、短期有效的凭证"跟这个代理模式也对得上，只是Claude Code的做法更彻底——不是给agent一个短期token，是**压根不让agent碰到真实凭证**，比OWASP建议的"短期but直接持有"更进一步。

## 6 值得记的点

- **"审批疲劳"这个概念，是这篇文章给出的一个很值得记的反直觉洞察**——权限确认机制本身如果太琐碎频繁，反而会削弱用户的注意力、降低整体安全水平，不是简单的"确认越多越安全"。沙箱化解决的不是"要不要设边界"，是"边界该设在哪个粒度"——从"每个操作都要问一遍"改成"预先划好一片可以自由活动的区域，只在越界的时候才问"。
- **"文件系统隔离+网络隔离缺一不可"这条原则，是这篇文章里最具体、最可执行的一条工程经验**，直接对应到OWASP Top 10里ASI02、ASI05这两条的防护建议（沙箱执行、出站流量白名单），是一个真实产品把抽象防护建议具体实现出来的样本。
- **"凭证永远不进入沙箱、由代理层代理认证操作"这个设计模式，在OWASP笔记的ASI10（失控agent）防护建议里也出现过**——"密钥绝不能直接暴露给agent，要由编排层来代理签名操作"，这里的git代理服务就是这条原则的一次具体落地：Claude Code这个agent本身从头到尾都拿不到能直接推送代码的真实凭证。
- **这套沙箱机制是开源的**（`anthropic-experimental/sandbox-runtime`），Anthropic明确鼓励其他团队把它集成进自己的agent里去——这跟我们之前研究的开源框架（Promptfoo、HALO等）性质不一样，这个是安全基础设施本身被开源，不是评估工具。

## 参考资料

- David Dworken, Oliver Weller-Davies, *Making Claude Code more secure and autonomous with sandboxing*, Anthropic, 2025-10-20, https://www.anthropic.com/engineering/claude-code-sandboxing
