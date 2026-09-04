# Dynamic Workflows（Claude Code）

官方文档：[Orchestrate subagents at scale with dynamic workflows](https://code.claude.com/docs/en/workflows.md)（全文409行，`.md`源）
补充来源：[Run agents in parallel](https://code.claude.com/docs/en/agents.md)（67行，"Choose an approach"节）、[Track todos](https://code.claude.com/docs/en/agent-sdk/todo-tracking.md)（377行，"When Claude creates todos"节）

**为什么优先学这篇**：这是之前完全没学过的Claude Code机制（`Multi-Agent 编排`那一章只学了Fleet/Subagents/Agent Teams，漏了这个），而且官方文档里的"谁掌握plan"四路对比表，是目前查到的、对"静态规划 vs 动态决定"这个问题回答得最直接的官方材料——比预期要读的OpenAI材料更清晰、更具体，所以插到LangChain前面优先学。

**范围说明**：`workflows.md`全文是完整的产品文档（怎么运行、怎么保存复用、成本、限制等），只精读跟任务分解直接相关的部分：核心对比表、JS API的分解原语、典型分解模式、size guideline、resume语义。`agents.md`只摘"Choose an approach"节（三问决策框架）。`todo-tracking.md`只摘"When Claude creates todos"节（阈值+模型演进趋势）。

## 1 核心对比表——"谁掌握plan"，四路对比

官方原文："A dynamic workflow is a JavaScript script that orchestrates subagents at scale. Claude writes the script for the task you describe, and a runtime executes it in the background while your session stays responsive."——workflow是一段JavaScript脚本，由Claude针对任务写出来，runtime在后台执行，session本身保持响应。

**四路对比表**（原文表格，翻译）：

| | Subagents | Skills | Agent teams | Workflows |
|---|---|---|---|---|
| 是什么 | Claude派生的一个worker | Claude遵循的一套指令 | lead agent监督一组peer session | runtime执行的一段脚本 |
| 谁决定接下来跑什么 | Claude，逐轮决定 | Claude，跟着提示词走 | lead agent，逐轮决定 | **脚本本身** |
| 中间结果存在哪 | Claude的上下文窗口 | Claude的上下文窗口 | 一份共享任务列表 | 脚本变量 |
| 什么东西是可复用的 | worker的定义 | 这套指令 | team的定义 | **整个编排过程本身** |
| 规模 | 每轮几个委派任务 | 跟subagents一样 | 少数几个长驻peer | 每次运行几十到几百个agent |
| 中途打断怎么办 | 重启这一轮 | 重启这一轮 | teammate继续跑 | **在同一session内可恢复** |

**核心结论原文**："A workflow moves the plan into code. With subagents, skills, and agent teams, Claude is the orchestrator: it decides turn by turn what to spawn or assign next, and every result lands in a context window. A workflow script holds the loop, the branching, and the intermediate results itself, so Claude's context holds only the final answer."——**把plan整个搬进代码里**：前三种模式Claude自己就是编排者，逐轮决定接下来派生/分配什么，每个结果都要进上下文窗口；workflow脚本自己拿着循环、分支判断和中间结果，Claude的上下文里最终只需要看到答案。

**把plan搬进代码，还带来一个额外好处**——原文："Moving the plan into code also lets a workflow apply a repeatable quality pattern, not just run more agents: it can have independent agents adversarially review each other's findings before they're reported, or draft a plan from several angles and weigh them against each other."——不只是能跑更多agent，还能固化一套**可复用的质量把关模式**：比如让独立的agent互相对抗式审查彼此的发现再上报，或者从几个不同角度分别起草方案再互相权衡，这是纯靠Claude逐轮决策很难稳定做到的。

## 2 JS API——分解原语与一个真实脚本示例

官方给出了`/deep-research`存下来之后生成的脚本长什么样（简化版示例）：
```text
<Steps>
  <Step title="Run the workflow">
    Run `s` with a question you want investigated. It fans out web searches across several angles, fetches and cross-checks the sources it finds, and synthesizes a cited report.

    ```text wrap theme={null}
    /deep-research What changed in the Node.js permission model between v20 and v22?
    ```
  </Step>

  <Step title="Allow workflows">
    Claude Code asks whether to allow the workflow. Select **Yes** to continue. The exact prompt depends on your permission mode. See [Approve the plan before it runs](#approve-the-plan-before-it-runs) for the per-mode options.
  </Step>

  <Step title="Watch progress">
    The run starts in the background. Run `/workflows`, use the arrow keys to select the run, and press Enter to open its progress view:

    ```text wrap theme={null}
    /workflows
    ```

    The view shows each phase with its agent count, token total, and elapsed time. Drill into any phase to see its agents and what each one found. See [Watch the run](#watch-the-run) for the full set of controls.

    You can also watch from the task panel below the input box: a one-line progress summary appears there while the run is going. Press the down arrow to focus it, then Enter to expand.
  </Step>

  <Step title="Read the report">
    When the run finishes, the report lands in your session. It cites the sources each claim came from, with claims that didn't survive cross-checking already filtered out.

    When the verifier agents can't check a claim, such as after a rate limit or API error, the report lists that claim as unverified instead of counting it as refuted.
  </Step>
</Steps>

```
```javascript
export const meta = {
  name: 'audit-routes',
  description: 'Audit every route handler for missing auth checks',
}

const found = await agent('List every .ts file under src/routes/.', {
  schema: { type: 'object', required: ['files'], properties: { files: { type: 'array', items: { type: 'string' } } } },
})

const audits = await pipeline(found.files, file =>
  agent(`Audit ${file} for missing authentication checks.`, { label: file }),
)

return audits.filter(Boolean)
```

**两个核心原语**：`agent()`派生**一个**子agent（可以带`schema`要求结构化输出）；`pipeline()`对一个列表里的**每一项**跑一个`agent()`调用——这是最直接的"map式扇出"分解原语，把"对N个文件分别做同一件事"这类任务拆解表达成一行代码。`agent()`调用如果中途被停掉或撞上不可恢复的API错误，会resolve成`null`，`pipeline()`把这个`null`原样留在结果数组里，所以示例结尾要`.filter(Boolean)`把这些条目滤掉。

原文强调脚本本身是**纯JavaScript，支持顶层`await`**，body里**不能**用`import()`（"a script that contains `import()` fails before the run starts"）——脚本只负责协调，真正需要用到某个库的工作要放进某个agent的任务里去做，不是脚本自己直接调库。

## 3 六种典型分解模式——官方给的example workflow prompts

原文列出了六个"workflow最适合的场景"，每个都是一种分解模式的具体案例：

| 分解模式 | 具体做法 |
|---|---|
| **逐项审计+对抗验证** | 每个文件派一个agent审计，再对抗式验证每条发现（`use a workflow to audit every route handler...and adversarially verify each finding`） |
| **反复修复直到检查通过** | 跑一次检查器，修复报出的问题，重复，直到通过或连续两轮没有进展（`keep fixing the reported errors until the type check passes or two rounds in a row make no progress`）——**这是本章一直在找的"失败后怎么办"的另一种具体答案：不是重新规划，是原地重试，用"连续N轮无进展"当停止条件** |
| **隔离副本迁移** | 先发现要迁移的文件，每个文件在自己独立的副本里改，避免互相冲突，再逐一验证结果 |
| **逐项审查后合并** | 每个改动文件跑一个reviewer，再把所有发现交给一个agent做排名去重 |
| **多源调研后综合** | 并行读changelog/issue/文档，再综合对比——`/deep-research`就是这个模式的内置实现 |
| **分轮搜索直到没有新发现** | 反复跑，记录哪些结果是新的，**连续两轮没有新发现就停**——跟上面"修复直到通过"共享同一种"收敛判据"设计：不是靠固定步数停，是靠"最近几轮有没有产出新东西"来判断该不该继续 |

**这六个模式里，"反复修复直到通过"和"分轮搜索直到没有新发现"这两条，是这次读到的、跟"任务什么时候算做完/要不要继续投入"这个问题最直接相关的两条**——判据都是"连续N轮没有进展"，用的是"进展停滞"而不是"总资源耗尽"作为停止信号，这跟Magentic-One的失速计数器（`is_progress_being_made`为False才计数）是同一类判据，只是Magentic-One是靠一个agent自我评估打分，这里是靠脚本层面显式记录"这一轮有没有找到新东西"这类具体产出来判断。

## 4 Size guideline——量化的复杂度旋钮

`workflowSizeGuideline`告诉Claude写workflow时应该瞄准多少个agent，官方明确"是给Claude的建议，不是硬上限"（"advice, not a cap"，一个要求不同规模的prompt仍然可以override）：

| 取值 | 目标agent数量 |
|---|---|
| `unrestricted` | 不设指导，Claude按任务本身的规模来定 |
| `small` | 少于5个agent |
| `medium`（默认） | 少于15个agent |
| `large` | 少于50个agent |

**运行时另有硬性上限，不受这个guideline的软约束限制**：单次并发最多16个agent（CPU受限环境更少）；单次运行总共最多1000个agent（"Prevents runaway loops"）。当一次运行调度超过25个agent、或预计token总量超过150万，任务面板会显示"Large workflow"警告（这个25的阈值如果自己设置了size guideline会被guideline的agent数取代，默认guideline下维持25不变）——**这条警告只是提示性的，不会暂停或限制运行**。

**这是本章目前查到的、跟Anthropic"简单1个agent+3-10次调用/复杂10+个agent"性质最接近的量化复杂度机制**——都是把"任务多大该配多少资源"这件事用具体数字锚定下来，区别是Anthropic的数字写死在提示词里当经验规则，Claude Code这边是一个可以随时调整的配置项（`/config`或`workflowSizeGuideline`设置），而且明确区分了"软性建议"(size guideline)和"硬性上限"(16并发/1000总量)两层。

## 5 Resume语义——按fan-out启动顺序回放，中途停在扇出中间代价最大

停掉一次运行后可以恢复，但规则很反直觉，原文举了具体例子：脚本按顺序启动了A、B、C、D四个agent，在B还没跑完时停掉整个运行。恢复时：

- **A**——已完成，从缓存直接返回
- **B**——之前没跑完，重新跑一遍
- **C和D**——**尽管两个都已经跑完了，也要重新跑一遍**，因为它们是在B之后启动的

**两条规则**：还在跑的agent不会被保存，恢复时从头开始；重放严格按agent的**启动顺序**，缓存的结果只能保留到第一个没跑完的agent那里为止，之后启动的（哪怕已经跑完）全部要重跑。**这也是原文给出的一条实践建议的依据**："A workflow that fans work out across many small agents therefore preserves more progress than one long agent."——把工作拆成很多小agent的workflow，比一个长时间运行的单一agent，在中途暂停恢复时能保住更多已完成的进度（因为拆得越细，恢复时"重新跑一遍"波及的范围相对越小）。

## 6 补充：`agents.md`的三问决策框架

"Choose an approach"这节，原文用三个问题帮你在四种模式里选：

1. **谁负责协调工作？**——Claude在一次对话里委派并收集结果用subagents；你自己交接独立任务、之后再回来看用agent view；Claude规划、分配、监督一组worker用agent teams；脚本掌握plan而不是Claude逐轮判断用dynamic workflows
2. **worker之间需不需要互相说话？**——subagent只向派生它的对话汇报结果，agent view的session只向你汇报（除非用跨session消息）；agent team的teammate之间可以直接互发消息，而且（有Task工具时）共享一份任务列表
3. **任务会不会碰到同一批文件？**——用worktree隔离；subagent和你自己起的session都可以各用一个独立worktree；agent team不隔离teammate的worktree，所以要自己划分好每个teammate负责的文件范围，避免冲突

## 7 补充：`todo-tracking.md`——3步阈值，以及一个model能力演进的信号

**创建todo的条件**（原文"When Claude creates todos"节）：

- **需要三个以上不同动作的复杂多步任务**
- 用户直接给出了一份任务清单（提到多个条目）
- 更长的、能从进度追踪里获益的操作
- 用户明确要求做todo组织

"三个以上不同动作"——跟LangChain`TodoListMiddleware`的"3步以上才用todo list"是两家独立收敛到的同一个数字，值得记一笔。

**一个值得单独拎出来的趋势信号**：原文写"On the models listed under Model availability, Claude tracks multi-step work without a written todo list, and Claude Code leaves the task-tracking tools out of sessions by default."——在Opus 4.8、Sonnet 5、Fable 5、Mythos 5这些较新的模型家族上，**任务追踪工具默认根本不在session里**，因为这些模型不需要写一份外显的todo list也能追踪多步工作。这暗示着：todo list这类"把分解过程显式写出来"的工具，价值可能会随模型自身的多步推理/追踪能力增强而递减——不是所有模型都需要一个外部脚手架才能做任务分解，这是一个跟"怎么拆"这个主题相关、但角度完全不同的观察：**分解能力本身也是模型能力的一部分，不完全依赖外部工具**。

## 值得记的点

- **"把plan搬进代码"是这几篇材料里对"静态vs动态"讲得最直接、最具体的一次**——不是抽象地说"预先规划"，是给出了真实的JS API（`agent()`/`pipeline()`）、真实的脚本示例、还有四路（不是两路）对比表，比预想中要读的OpenAI材料信息量大得多。
- **"连续N轮无进展就停"这个判据，在Claude Code和Magentic-One两家materials里都独立出现**——一个是脚本层面显式记录产出、一个是agent自我评估打分，但判据的性质是一样的："进展停滞"而不是"资源耗尽"，这可能是"任务什么时候算做完"这个问题下一个值得跨厂商总结的通用模式。
- **Resume语义"按启动顺序回放、扇出中间停最贵"这条规则**，是任务分解和上一章"暂停与恢复"两个主题的交叉点——分解成小任务的粒度选择，直接影响暂停恢复时的代价，这是设计任务分解粒度时一个容易被忽略的实际考量。
- **size guideline"软建议+硬上限"两层设计**，跟Anthropic嵌在提示词里的固定经验规则形成对照：一个是可配置项，一个是写死的启发式规则，代表了"怎么让复杂度评估落地"这件事的两种不同工程选择。
