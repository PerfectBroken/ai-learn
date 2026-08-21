# Agent Skills Specification

来源：`agentskills.io/specification`——Agent Skills这个开放格式规范的官方权威文档页面。规范本身的治理归属见`Skills.md`§1"背景"一节已经核实过的原文："The Agent Skills format was originally developed by Anthropic, released as an open standard..."——**当前由GitHub社区组织`agentskills/agentskills`（github.com/agentskills/agentskills）维护，规范正文里点名的官方校验工具`skills-ref`也放在这个组织下**（`github.com/agentskills/agentskills/tree/main/skills-ref`），不再是Anthropic一家闭门定义。

下面是规范正文的完整中文翻译（结构对照原文，字段表格逐条翻译，代码/YAML示例保留原文不译，因为是功能性语法而非叙述性文字）。

## 一、目录结构

一个skill是一个目录，最起码要包含一个`SKILL.md`文件：

```
skill-name/
├── SKILL.md          # 必需：元数据 + 指令正文
├── scripts/          # 可选：可执行代码
├── references/       # 可选：文档资料
├── assets/           # 可选：模板、素材资源
└── ...                # 其他任意文件/目录
```

## 二、`SKILL.md`格式

`SKILL.md`文件必须是"YAML frontmatter + Markdown正文"这个结构。

### 2.1 Frontmatter字段表（规范原文完整翻译）

| 字段 | 是否必需 | 约束条件 |
|---|---|---|
| `name` | 是 | 最长64字符；只能是小写字母、数字、连字符；不能以连字符开头或结尾 |
| `description` | 是 | 最长1024字符；不能为空；要描述这个skill是做什么的、什么时候该用 |
| `license` | 否 | 许可证名称，或指向一份随包附带的许可证文件 |
| `compatibility` | 否 | 最长500字符；说明运行环境要求（目标产品、系统依赖包、是否需要联网等） |
| `metadata` | 否 | 任意的字符串键值映射（key/value都是字符串） |
| `allowed-tools` | 否 | 空格分隔的字符串，列出这个skill可以免审批直接用的工具名（**实验性字段**） |

**最简示例**：
```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

**带可选字段的示例**：
```yaml
---
name: pdf-processing
description: Extract PDF text, fill forms, merge files. Use when handling PDFs.
license: Apache-2.0
metadata:
  author: example-org
  version: "1.0"
---
```

### 2.2 各字段详解（规范原文逐条翻译）

#### `name`字段（必需）

- 长度1-64字符
- 只能包含unicode小写字母数字（`a-z`、`0-9`）和连字符（`-`）
- 不能以连字符开头或结尾
- 不能出现连续连字符（`--`）
- **必须跟父目录名一致**（这一条容易被忽略——`name`不是随便起的显示名，规范层面要求跟目录名对上）

合法例子：`pdf-processing`、`data-analysis`、`code-review`
非法例子：`PDF-Processing`（不能大写）、`-pdf`（不能以连字符开头）、`pdf--processing`（不能连续连字符）

#### `description`字段（必需）

- 长度1-1024字符
- 应该同时说清楚"这个skill做什么"和"什么时候该用它"
- 应该包含具体的关键词，帮助agent识别相关任务

规范给的"好例子"和"差例子"对比很直观：

好例子：
```yaml
description: Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
```
差例子：
```yaml
description: Helps with PDFs.
```

#### `license`字段（可选）

指定这个skill适用的许可证。建议保持简短——要么直接写许可证名字，要么指向一份随包附带的许可证文件名。

```yaml
license: Proprietary. LICENSE.txt has complete terms
```

#### `compatibility`字段（可选）

- 提供的话，长度1-500字符
- **只有当这个skill确实有特定环境要求时才应该写**（规范原文特别提示："Most skills do not need the `compatibility` field."）
- 可以用来说明目标产品、需要的系统包、是否需要联网等

```yaml
compatibility: Designed for Claude Code (or similar products)
compatibility: Requires git, docker, jq, and access to the internet
compatibility: Requires Python 3.14+ and uv
```

#### `metadata`字段（可选）

字符串键到字符串值的映射，供客户端存放规范本身没有定义的额外属性。规范建议：**key的命名要有一定辨识度，避免不同客户端之间意外撞车**。

```yaml
metadata:
  author: example-org
  version: "1.0"
```

#### `allowed-tools`字段（可选，实验性）

空格分隔的字符串，列出这个skill可以免审批直接使用的工具。规范原文明确标注"Experimental. Support for this field may vary between agent implementations"——**不是所有实现都保证支持，也不保证行为一致**（对照我们在`Skills.md`里记的：Claude Code和OpenClaw各自对这类字段的具体处理方式确实不完全一样）。

```yaml
allowed-tools: Bash(git:*) Bash(jq:*) Read
```

### 2.3 正文内容

frontmatter之后的Markdown正文就是skill的具体指令。**规范没有规定任何格式要求**，怎么有利于agent执行任务就怎么写。建议包含的内容：分步骤指令、输入输出示例、常见边界情况。

规范特别提醒一句关键的设计约束：

> Note that the agent will load this entire file once it's decided to activate a skill. Consider splitting longer `SKILL.md` content into referenced files.

翻译：一旦agent决定激活某个skill，它会把这整个文件**完整**加载进去——所以更长的内容应该拆到被引用的独立文件里，而不是全堆在`SKILL.md`正文里。

## 三、可选目录

`SKILL.md`之外，skill目录可以放任意文件/目录。规范给了三类常见内容的组织建议（不是强制规定）：

- **`scripts/`**——存放agent可以执行的代码。脚本应当自包含、或清楚写明依赖，要有帮助性的报错信息，能优雅处理边界情况。具体支持哪种语言取决于agent的实现，常见的是Python、Bash、JavaScript。
- **`references/`**——存放agent按需读取的补充文档，比如`REFERENCE.md`（详细技术参考）、`FORMS.md`（表单模板/结构化数据格式）、或领域专属文件（`finance.md`、`legal.md`等）。规范建议单个参考文件保持聚焦——agent是按需加载这些文件的，文件越小，占用的上下文就越少。
- **`assets/`**——存放静态资源：模板（文档模板、配置模板）、图片（图表、示例图）、数据文件（查找表、schema）。

## 四、渐进式披露（规范层面的正式定义）

规范原文给出的是标准的**三阶段**定义（这是规范本身的措辞，跟Anthropic自家产品文档的"Level 1/2/3"是同一件事，但这里是跨厂商都要遵守的规范条款）：

1. **Metadata（元数据，约100 token）**：所有skill的`name`和`description`字段，在启动时就加载。
2. **Instructions（指令，建议控制在5000 token以内）**：skill被激活时，完整的`SKILL.md`正文才加载。
3. **Resources（资源，按需）**：`scripts/`、`references/`、`assets/`里的文件，只在真正用到时才加载。

配套的两条硬性建议：**`SKILL.md`主文件保持在500行以内**，详细的参考材料挪到独立文件里去。

## 五、文件引用规范

在skill内部引用其他文件时，要用相对skill根目录的相对路径：

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

规范明确要求：**文件引用只能"深一层"**——即`SKILL.md`可以引用`references/REFERENCE.md`，但不建议再从`REFERENCE.md`里链式引用另一份更深的文件，要避免层层嵌套的引用链。

## 六、校验工具

规范推荐用官方参考库`skills-ref`（`github.com/agentskills/agentskills/tree/main/skills-ref`，跟规范本身在同一个GitHub组织`agentskills/agentskills`下）来校验自己写的skill：

```bash
skills-ref validate ./my-skill
```

这个工具会检查`SKILL.md`的frontmatter是否合法、是否遵守了上面所有的命名约定。

## 七、跟本章其他笔记的关系

这份规范是`Skills.md`里"Claude Code实现"（§2）和"OpenClaw实现"（§4）两边共同遵守的底层格式契约——两家在**怎么把skill加载进上下文、怎么触发调用**这些工程细节上做法完全不同（详见`Skills.md`§4.4的对比表），但`SKILL.md`这个文件本身的格式（frontmatter字段、目录结构、渐进式披露三阶段）是共享的、跨厂商统一的。读完这份规范，回头看`Skills.md`里两家具体实现的差异会更清楚——**差异全部出现在"规范没有规定"的那些工程实现细节上，规范本身规定的部分两家是严格一致的**。
