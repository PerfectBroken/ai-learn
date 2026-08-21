# Skills

## 目录

- [1 Skills是什么](#1-skills是什么)
- [2 Claude Code的实现](#2-claude-code的实现)
  - [2.1 SKILL.md格式与关键frontmatter字段](#21-skillmd格式与关键frontmatter字段)
  - [2.2 谁能调用：disable-model-invocation / user-invocable](#22-谁能调用disable-model-invocation--user-invocable)
  - [2.3 渐进式披露与内容生命周期](#23-渐进式披露与内容生命周期)
  - [2.4 加载位置与优先级](#24-加载位置与优先级)
- [3 Skills vs MCP Prompts vs Tools](#3-skills-vs-mcp-prompts-vs-tools)
- [4 OpenClaw的实现对照（源码验证）](#4-openclaw的实现对照源码验证)
  - [4.1 加载优先级与per-agent可见性](#41-加载优先级与per-agent可见性)
  - [4.2 Skills Prompt怎么拼进system prompt](#42-skills-prompt怎么拼进system-prompt)
  - [4.3 Snapshot机制：什么时候拍快照，什么时候刷新](#43-snapshot机制什么时候拍快照什么时候刷新)
  - [4.4 跟Claude Code对照的结论](#44-跟claude-code对照的结论)
- [5 参考资料](#5-参考资料)

## 1 Skills是什么

**结论先行：Skill是一份"打包好的可复用指令"——用一个带`SKILL.md`的文件夹封装某个专项工作流/领域知识，让Claude在相关时动态发现、加载，而不是每次对话都要重新解释一遍。**

Anthropic官方博客《Skills in Claude's Agentic Ecosystem》给出的定义：

> Skills are folders containing instructions, scripts, and resources that Claude discovers and loads dynamically when relevant to a task.

它跟三个相邻概念的区别（同一篇博客）：

- **跟Prompts（对话里临时给的指令）比**：Prompts是一次性的、被动的、当场给；Skills跨会话持久存在，Claude判断相关时**主动**触发。
- **跟Projects（长期背景知识）比**：Projects回答"你应该知道什么"；Skills回答"你应该怎么做"——是程序性知识+可执行代码，不是背景资料。
- **跟MCP比**：MCP负责把Claude连接到外部工具/数据源（Google Drive、GitHub、数据库）；Skills教Claude怎么用这些工具、遵循什么流程。两者配合：MCP管"能不能拿到数据"，Skills管"怎么聪明地处理这些数据"。

### 背景：谁发明的，为什么

**Skills是Anthropic发明的**，正式发布于工程博客《Equipping agents for the real world with Agent Skills》，**2025年10月16日**（`anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills`）。

原文给出的动机，核心是一句话：

> Claude is powerful, but real work requires procedural knowledge and organizational context.

也就是说，模型本身通用能力已经够强了，缺的是"怎么按我们公司/我这个人的具体流程做事"这类程序性知识和组织上下文——每次都靠在对话里现场解释一遍，既浪费token又没法复用。文章明确把当时的替代方案定性为"零散、为每个场景单独定制agent"，Skills想解决的正是这种碎片化：

> Instead of building fragmented, custom-designed agents for each use case, anyone can now specialize their agents with composable capabilities.

**不是凭空发明的，是从Claude Code内部一个更早的功能演化来的**——Claude Code官方文档《Extend Claude with skills》里明确写着"Custom commands have been merged into skills"：早期Claude Code有一个更简单的"自定义命令"机制（纯markdown文件放在`.claude/commands/`，输个`/文件名`就执行），Skills是在这基础上加了目录结构（能带脚本/参考资料）、frontmatter控制（谁能调用、什么时候用）、以及模型自主触发能力，把这个功能整体升级、并入了进来。**这篇工程博客里没有提到Skills的设计受到了其他公司/已有机制的启发**——原文唯一提到的相关外部机制是MCP，但只是讲两者未来会互补，不是灵感来源。

现在Skills已经从Claude Code这一个产品，长成了一个开放规范——[Agent Skills](https://agentskills.io)。**直接去规范官网核实了一手信息**（此前只在Claude Code/OpenClaw各自文档里看到"提到"这份规范，没有真正读过它自己怎么说）：

> The Agent Skills format was originally developed by Anthropic, released as an open standard, and has been adopted by a growing number of agent products. The standard is open to contributions from the broader ecosystem.

这句话直接确认了两点：①起源确实是Anthropic；②现在治理权已经开放给整个生态（GitHub组织`agentskills/agentskills` + Discord社区），不是Anthropic一家说了算。

规范官网自己把"渐进式披露"定义成了标准的三阶段（用词跟Anthropic产品文档的Level 1/2/3是同一件事，但这是**规范层面**的定义，不是某一家产品自己的实现描述）：

> 1. **Discovery**: At startup, agents load only the name and description of each available skill...
> 2. **Activation**: When a task matches a skill's description, the agent reads the full `SKILL.md` instructions into context.
> 3. **Execution**: The agent follows the instructions, optionally executing bundled code or loading referenced files as needed.

官网还有一个采用方展示页（Client Showcase），除了Claude Code、Claude、OpenClaw之外，ChatGPT & Codex、GitHub Copilot、VS Code、Cursor、Gemini CLI等一大批主流agent产品都在列——这也是为什么OpenClaw能照着同一份规范实现自己的skills机制（§4会看到，具体工程细节完全不同，但都遵循同一份`SKILL.md`格式规范）：Skills现在已经不是"Claude专属功能"，是这个赛道正在收敛出的一个跨厂商事实标准。

## 2 Claude Code的实现

来源：Claude Code官方文档《Extend Claude with skills》(`code.claude.com/docs/en/skills`)。

### 2.1 SKILL.md格式与关键frontmatter字段

每个skill是一个目录，必须有`SKILL.md`：YAML frontmatter（决定何时用、谁能用）+ markdown正文（真正的指令内容）。官方原文强调：**只有`description`字段是推荐必填的**，其余全部可选。

最关键的几个字段（原文表格节选，完整字段表还包括`argument-hint`/`arguments`/`allowed-tools`/`model`/`context`/`hooks`/`paths`等）：

| 字段 | 作用 |
|---|---|
| `description` | Claude据此判断"什么时候该用这个skill"。省略时取正文第一段。**`description`+`when_to_use`合计被截断在1,536字符**，控制prompt里的目录开销 |
| `disable-model-invocation` | 设为`true`：Claude不能自动加载，只能用户手动`/skill-name`触发。适合有副作用、要控制时机的操作（部署、发消息） |
| `user-invocable` | 设为`false`：只有Claude能触发，用户不能手动`/name`。适合背景知识类skill，不是一个"动作" |
| `allowed-tools` | 触发这个skill的这一轮，免审批授予的工具列表，下一条消息发出就清空 |
| `context: fork` | 让这个skill在一个独立的子agent（subagent）里跑，拿不到当前对话历史 |

### 2.2 谁能调用：disable-model-invocation / user-invocable

这两个字段可以正交组合，官方给了一张对照表（原文，翻译）：

| Frontmatter配置 | 用户能调用 | Claude能调用 | 什么时候进入上下文 |
|---|---|---|---|
| （默认） | 能 | 能 | description一直在上下文里；调用时才加载完整内容 |
| `disable-model-invocation: true` | 能 | 不能 | description不在上下文里；用户调用时才加载完整内容 |
| `user-invocable: false` | 不能 | 能 | description一直在上下文里；调用时才加载完整内容 |

### 2.3 渐进式披露与内容生命周期

这是Skills机制的核心设计——**两级加载**，官方原文（"Skill content lifecycle"节）：

> In a regular session, skill descriptions are loaded into context so Claude knows what's available, but full skill content only loads when invoked.

即：**第一级**——所有可用skill的`description`（一小段元数据，几十到几百token）**始终**在system prompt里，供模型判断"要不要用哪个"；**第二级**——只有真正被调用（模型自主选择，或用户`/name`）时，`SKILL.md`的完整正文才作为一条消息注入对话，且**注入之后会一直留在上下文里，直到会话结束**——Claude Code不会在后续轮次里重新读取这个文件。

配套的两个细节值得记：

- **compaction（压缩）时的处理**：上下文因为太长被摘要后，Claude Code会把"最近一次调用过的每个skill"重新附加回来，每个最多保留5,000 token，所有重新附加的skill合计共享25,000 token预算——预算不够时，**最早调用的skill会被完全丢弃**。
- **官方承认的模糊地带**：skill内容还在上下文里，但模型没有照着做，官方原文的建议是"the model is choosing other tools or approaches. Strengthen the skill's description and instructions... or use hooks to enforce behavior deterministically"——**没有优先级参数**，确定性结果只能靠hooks硬编码，这一点在之前的调研里已经验证过。

**第一级metadata具体拼在system prompt的什么位置，有单独实锤过**：Anthropic官方文档《Agent Skills》（`platform.claude.com/docs/en/agents-and-tools/agent-skills/overview`，Agent SDK的skills文档明确指向这篇作为架构权威说明）原文：

> Claude loads this metadata at startup and includes it in the system prompt.

文档给了system prompt里具体长什么样的例子：

> **Startup:** System prompt includes: `pdf-processing - Extract text and tables from PDF files, fill forms, merge documents. Use when working with PDF files or when the user mentions PDFs, forms, or document extraction.`

也就是`name - description`拼成一行文本，会话启动时就写进system prompt——跟OpenClaw"编译成一个紧凑XML块注入system prompt"是同一套思路（一个用自然语言短句拼接，一个用XML标签包裹），字段内容都只有name+description这一层，不含完整正文。

**调用skill走的是普通的`tool_use`通道，接口层面没有单独的"skill_use"机制**——直接从当前会话自己能调用的`Skill`工具定义拿到的实锤：

```json
{
  "name": "Skill",
  "parameters": {
    "properties": {
      "skill": { "type": "string" },
      "args": { "type": "string" }
    },
    "required": ["skill"]
  }
}
```

`Skill`本身就是`tools`数组里的一个普通工具，跟`Read`/`Bash`/`Edit`是同一种形状（`name`+`description`+`parameters`）。模型想用某个skill时，发出的是一次标准`tool_use`，工具名固定是`"Skill"`，参数里带一个`skill`字符串指定具体调用哪个——**Messages API层面只有一份`tools`列表，没有专属的"skill_use_list"**，"调用skill"和"调用Bash"在协议结构上没有任何区别，区别只在于`Skill`这个特定工具的语义是"把某个`SKILL.md`的指令内容读进上下文"。Anthropic官方Agent SDK文档用的说法也印证了这一点："the skill invocation appears as a **Skill tool use**, followed by Read calls"——官方也是把它算作一种"tool use"，没有专属事件类型。

**第三级（skill内部拆分的多篇`.md`、bundled脚本）不是靠一次`Skill`调用内部悄悄解决的，是靠agent loop多走几轮、模型自己再发起新的工具调用来解决的**。证据分两处：

一是上一段已经引用过的Agent SDK真实事件流例子（跑一个`security-check`skill）：

> In the stream, the skill invocation appears as a Skill tool use, **followed by Read calls** on the project files.

"followed by"说明这是**两类先后独立的事件**，不是打包在同一次`Skill`调用里。

二是官方架构文档对分层资源读取方式的完整说明（"How Claude accesses Skill content"节）：

> If those instructions reference other files (such as FORMS.md or a database schema), Claude reads those files too using **additional** bash commands. When instructions mention executable scripts, Claude runs them through bash and receives only the output.

关键词"additional"（额外的）——明确是后续、独立的工具调用。这跟`SKILL.md`正文里引用附带文件的写法也对得上，官方给的示例就是一段普通markdown链接，不是什么"自动附加"的特殊语法：

```markdown
## Additional resources
- For complete API details, see [reference.md](reference.md)
- For usage examples, see [examples.md](examples.md)
```

串起来看，一次"多文件+带脚本"的skill大致长这样（每个`→`都是一次独立的loop迭代，回到LLM重新决策）：

`Skill`调用返回`SKILL.md`正文（提到"详见reference.md""运行check.py校验"）→ **loop回到LLM** → 模型判断需要细节，发一次`Read`读`reference.md` → **loop回到LLM** → 模型判断需要跑校验，发一次`Bash`执行脚本，只拿到**输出**（脚本代码本身不进上下文）→ **loop回到LLM** → 模型综合信息给出最终答案。

这跟"渐进式披露"的初衷是一致的：如果多篇`.md`和脚本在第一次`Skill`调用时就无脑塞进上下文，"按需加载"就名存实亡了——只有把"要不要读下一份材料"这个判断权继续交还给LLM、让它在每一轮自己决定，才能真正做到"用到什么就付出什么token成本"。

### 2.4 加载位置与优先级

Skill可以放在四个层级（个人`~/.claude/skills/`、项目`.claude/skills/`、插件`<plugin>/skills/`、企业级），**同名时企业>个人>项目**；插件skill用`plugin-name:skill-name`命名空间天然不会冲突。还支持**嵌套目录**：monorepo里某个子包自己的`.claude/skills/`，只有当Claude真正读写到那个子目录下的文件时才会加载，会话开始时不预加载——跟"渐进式披露"是同一个"按需"哲学在目录发现层面的体现。

## 3 Skills vs MCP Prompts vs Tools

这是Layer 2范围内最容易搞混的一组对比，之前的调研已经确认（结论直接搬过来，证据来源见下方参考资料）：

| 维度 | MCP Prompts原语 | Skills |
|---|---|---|
| **归属层次** | MCP协议本身定义的一种原语（跟Resources/Tools并列） | 本地文件（`SKILL.md`），不是协议层面的东西，是产品/客户端自己的机制 |
| **触发方式** | MCP规范原文："Prompts are **user-controlled**"——设计上由用户主动选择触发 | Anthropic官方博客原文："Claude **dynamically decides**"——模型自主判断相关性后主动加载 |
| **加载机制** | 客户端调用`prompts/list`拿列表，`prompts/get`拿完整内容，没有"先加载一部分、按需加载全部"这种分级 | 渐进式披露：description常驻上下文，完整正文按需加载 |
| **调用的语法保证** | 无直接可比——不涉及"模型自由选择" | `Skill`工具的`skill`参数是`"type": "string"`，不是`enum`——选中哪个skill完全靠模型语义判断，没有语法掩码（grammar masking）兜底，跟"选哪个工具"这一步（有解码约束保证）是不同可靠度的两件事 |

## 4 OpenClaw的实现对照（源码验证）

来源：OpenClaw官方文档`docs/tools/skills.md`，关键机制额外用`gh search code`/`gh api`核实了源码（`src/skills/loading/workspace-skill-prompt.ts`、`skill-prompt-limits.ts`），不是纯读文档猜测。

### 4.1 加载优先级与per-agent可见性

OpenClaw的skill来源分6级优先级（原文表格，同名时**优先级高的赢**）：

| 优先级 | 来源 | 路径 |
|---|---|---|
| 1（最高） | Workspace skills | `<workspace>/skills` |
| 2 | Project agent skills | `<workspace>/.agents/skills` |
| 3 | Personal agent skills | `~/.agents/skills` |
| 4 | Managed/local skills | `<state-dir>/skills` |
| 5 | Bundled / Custodian skills | 随安装内置 |
| 6（最低） | Extra目录 + 插件skills | `skills.load.extraDirs` |

跟Claude Code"企业>个人>项目"的3级不同，OpenClaw是**6级**，且多了"workspace"（比"项目"更细的一级）和"per-agent allowlist"——多agent场景下，每个agent可以单独配置一份`skills: [...]`白名单，跟"skill放在哪"是两套独立的控制维度（原文明确区分"location"和"visibility"）。

### 4.2 Skills Prompt怎么拼进system prompt

官方文档"Environment injection"一节给出四步流程（原文翻译）：①读取skill元数据、应用gating规则；②注入env/API key到`process.env`；③**把符合条件的skills编译成一个紧凑的XML块，注入system prompt**；④运行结束后恢复原环境。

源码验证了第③步的细节。`buildSkillSnapshot`（`workspace-skill-prompt.ts`第51行）调用`formatSkillsForPromptBounded`，后者内部的字段命名是`descriptionMaxChars`（`skill-prompt-limits.ts`），只处理`name`和`description`两个字段——**跟Claude Code一样，这个XML目录里只有name+description，不含完整的正文指令**。官方文档"Token impact"一节给出了具体的成本模型：

> Base overhead (only when 1+ skills are eligible): a fixed block of intro prose plus the `<available_skills>` wrapper. Per skill: ~97 characters + your `name`, `description`, and `location` field lengths.

超出`skills.limits.maxSkillsPromptChars`预算时，会按顺序降级：先保留所有skill的身份信息（name/location/version，不含description）→ 用剩余预算塞入缩短版description → 预算实在不够就整个省略description。这套"分级降级"策略，跟Claude Code"description恒定1,536字符截断"是不同的实现思路（OpenClaw更精细，按总预算动态压缩；Claude Code是每个skill定长截断）。

完整正文什么时候真正进入模型视野？文档"Reference a skill in a prompt"一节写道，当有`$skill-name`这样的显式引用时，OpenClaw"tells the model to read each referenced `SKILL.md` before acting"——**是让模型自己去读这个文件，不是运行时把正文塞进prompt**。这跟Claude Code"调用时注入一条完整消息"的实现方式不同，但达到的效果一致：完整内容都是**按需**才进入上下文，不会一开始就把所有skill的全文都摆在system prompt里。

**这句"让模型自己去读文件"不是比喻，源码验证了它是字面意思——OpenClaw根本没有一个叫`Skill`的专属工具，是把skill读取包进了普通的`read`工具里**（`src/agents/core-coding-tools.ts`第169-177行）：

```ts
if (baseToolNames.has("read")) {
  ...
  base.push(
    wrapReadToolWithSkillContent(guarded, options.skillsSnapshot?.resolvedSkills, {...}),
  );
}
```

`wrapReadToolWithSkillContent`（`agent-tools.read.ts`第1064行）包裹的正是`read`这个基础文件读取工具（跟`edit`/`write`同属base coding tools），内部维护一份"skill文件路径→内容"的映射：本地磁盘的`SKILL.md`直接读文件；node-hosted的skill走`node://`虚拟路径，直接返回预先解析好的内容。**模型调用skill时发出的就是一次普通的`read`，参数是`SKILL.md`的路径，被这层wrapper拦截命中后直接返回内容——在事件流里跟读任何别的文件没有区别，不是一次独立可辨识的"skill调用"。**

这跟Claude Code形成了一个比"名字不同"更深的架构差异，值得单独列出来对比：

| 维度 | Claude Code | OpenClaw |
|---|---|---|
| 是否有专属工具 | 有——`Skill`是`tools`数组里独立的一个工具，`name: "Skill"`，参数`skill: string` | **没有**——复用/包裹了普通的`read`文件读取工具（`wrapReadToolWithSkillContent`），没有单独的工具定义 |
| 协议层可辨识度 | 高——事件流里是独立的`Skill tool use`，能直接区分"这是一次skill调用" | 低——就是一次普通的文件读，只能靠"读的路径命中某个SKILL.md"事后推断这是在用skill |
| 触发方式 | 模型主动选择要调用哪个skill（`skill`参数） | 模型只是被告知"去读这个路径"（system prompt目录里的skill信息，或`$name`引用展开的指令），读的动作本身和读别的文件没区别 |
| 工具本身的description（源码原文） | "Invoke a skill. A skill is a packaged set of instructions... call this tool first — the skill's instructions load into the turn for you to follow... some skills instead run in a subagent and return the finished result." | `src/agents/sessions/tools/read.ts`第479行："Read text/image file (jpg/png/gif/webp/bmp); images attach to model context. Text caps `{N}` lines or `{X}KB`. Continue with offset/limit, or cursor within a long line."——**通篇没提skill**，纯粹是通用文件读取工具的描述，skill行为完全靠外层wrapper透明注入 |
| 能读的内容范围 | 只能"调用一个已注册的skill"，功能上跟"读任意文件"完全脱钩，不是通用工具 | 通用文件读取：文本+图片（jpg/png/gif/webp/bmp），skill只是它能读的众多目标之一 |
| 长内容/分页处理 | 没有offset/limit这类参数——skill正文整篇作为一条消息注入对话 | 有完整分页机制（`DEFAULT_MAX_LINES`/`DEFAULT_MAX_BYTES` + offset/limit/cursor），因为要应对任意大小的真实文件 |
| 参数替换 | 支持`args`透传，skill正文里能用`$ARGUMENTS`/`$0`/`$1`等占位符接收调用时传入的值 | 无——读到的是wrapper映射表里存的静态内容（真实文件或node-hosted的预解析内容），没有参数替换这层 |
| 子agent/后台执行 | 支持`context: fork`——可以让skill在独立subagent里跑，默认后台执行，完成后作为通知送达 | 无——`read`只是同步返回文件内容，不涉及任何子agent调度 |

### 4.3 Snapshot机制：什么时候拍快照，什么时候刷新

官方文档"Snapshots and refresh"原文：

> OpenClaw snapshots eligible skills **when a session starts** and reuses that list for all subsequent turns in the session. Changes to skills or config take effect on the next new session.

即默认是**session开始时拍一次快照，整个session复用**，不是每轮重新计算。但紧接着文档又说了两种"中途也会刷新"的例外：`SKILL.md`文件变化被watcher检测到，或者有新的、符合条件的远程node接入——刷新后的列表在**下一轮**agent turn生效（不是立即打断当前轮）。

### 4.4 跟Claude Code对照的结论

| 维度 | Claude Code | OpenClaw |
|---|---|---|
| 渐进式披露两级结构 | 有：**实锤确认拼进system prompt**（"Claude loads this metadata at startup and includes it in the system prompt."，`platform.claude.com`架构文档原文）+ 完整正文按需加载 | 有：官方文档明确写的也是"injected into the system prompt"，紧凑XML目录（name+description）常驻 + 完整正文靠模型主动读文件 |
| 快照/刷新时机 | 没有"session开始拍快照"这个说法，但skill目录文件变化"picked up within the current session, without a restart"——更接近**持续监听、随时生效** | 明确是"session开始时拍一次快照，全程复用"，文件变化会刷新，但要等**下一轮**才生效——是"定期刷新的快照"，不是持续实时 |
| 加载位置层级 | 3级（企业/个人/项目）+ 插件命名空间 + 嵌套目录 | 6级，多了workspace/per-agent allowlist这类多agent场景的控制维度 |
| Token预算控制 | 每个skill的description+when_to_use定长截断在1,536字符 | 按`maxSkillsPromptChars`总预算动态降级（保留身份→缩短description→省略description） |
| 选择skill的可靠度 | `Skill`工具的`skill`参数是`type: string`，无语法掩码，但好歹是个专属参数、语义上限定为"选一个skill" | **比Claude Code还松**：源码实锤——`read`工具的路径参数`path: Type.String({ description: "File path; relative/absolute." })`（`read-tool-contract.ts`第6行），是**所有文件读取共用的通用字符串参数**，连"这是在选一个skill"这层语义限定都没有。模型只能凭system prompt那份XML目录里给的`location`字段（"Token impact"节确认目录里含`name`/`description`/`location`三个字段），自己拼出正确路径字符串传给`read`——没有任何schema层面的保证 |

**总体结论**：两家在"渐进式披露"这个核心设计理念上是一致的（先给模型一份便宜的目录，真正要用再付出完整内容的token成本），但具体工程实现——快照时机、目录层级复杂度、预算降级策略——各自摸索出了不同的方案，符合Layer 2这几章反复看到的规律：**理念可以趋同，工程细节永远值得单独查证，不能凭"两家做的是同一件事"就假设实现细节也一样**。

## 5 参考资料

- Claude Code Docs，[Extend Claude with skills](https://code.claude.com/docs/en/skills)——frontmatter完整字段表、渐进式披露与内容生命周期、加载位置与优先级规则。
- Anthropic Blog，[Skills in Claude's Agentic Ecosystem](https://claude.com/blog/skills-explained)——理念层定义，Skills vs Prompts/Projects/MCP的定位区分。
- OpenClaw Docs，[Skills](https://docs.openclaw.ai/tools/skills)——加载优先级、gating、环境注入、snapshot机制、token成本模型，本章§4的翻译来源。
- OpenClaw源码（`gh api`直接核实，不是猜测）：`src/skills/loading/workspace-skill-prompt.ts`（`buildSkillSnapshot`/`resolveSkillsPrompt`）、`src/skills/loading/skill-prompt-limits.ts`（`formatSkillsForPromptBounded`，确认prompt目录只含name+description）。
- MCP Prompts原语对比：见[MCPProtocol.md](../mcp-protocol/MCPProtocol.md)。
