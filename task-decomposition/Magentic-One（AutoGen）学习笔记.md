# Magentic-One（Microsoft AutoGen）

官方文档：[Magentic-One user guide](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html)
技术报告：[arXiv 2411.04468](https://arxiv.org/abs/2411.04468)（HTML全文版：`arxiv.org/html/2411.04468`）
源码：`microsoft/autogen`仓库——`autogen_agentchat/teams/_group_chat/_magentic_one/_prompts.py`（Orchestrator的完整prompt模板）、`_magentic_one_orchestrator.py`（失速计数器实现）、`_magentic_one_group_chat.py`（默认参数）

**范围说明**：本章重点精读对象——目前查到的、唯一一个把"失败/卡住后怎么重新规划"做成显式命名机制的官方系统。user guide给概念/架构，技术报告给具体机制描述（五个问题、失速阈值、消融实验），源码用来交叉验证机制是否真的这样实现，而且这次核实过程中发现论文描述和当前开源代码的默认值**不完全一致**，要如实标注。

## 1 整体架构——外层Task Ledger循环，内层Progress Ledger循环

Orchestrator agent负责高层规划、指挥其他agent、追踪任务进度，用**两份结构化账本**来做这件事，工作分成两层循环：

- **外层循环（outer loop）**：维护**Task Ledger（任务账本）**——包含事实、猜测、和整体计划。触发一次，在任务开始时创建，之后只在需要重新规划时才会再触发一次。
- **内层循环（inner loop）**：维护**Progress Ledger（进度账本）**——每一步都指挥、评估具体的执行步骤，把指令派发给专门agent。

团队构成：**Orchestrator**（首席agent，负责任务分解和规划、指挥其他agent执行子任务、追踪整体进度、按需采取纠正措施）+ **WebSurfer**（操作浏览器）+ **FileSurfer**（读本地文件）+ **Coder**（写代码）+ **ComputerTerminal**（执行代码、装依赖）。

## 2 Task Ledger怎么建立——先摸底事实，再定计划

外层循环由初始任务触发，分两步：

**第一步：事实摸底（pre-survey）**——源码`ORCHESTRATOR_TASK_LEDGER_FACTS_PROMPT`原文要求Orchestrator把关于这个任务的信息分四类列出来：

1. **GIVEN OR VERIFIED FACTS**——请求本身直接给出的事实/数字
2. **FACTS TO LOOK UP**——需要另外查的事实，以及具体去哪查
3. **FACTS TO DERIVE**——需要推导出来的事实（逻辑推理/模拟/计算）
4. **EDUCATED GUESSES**——凭记忆/直觉/合理推测得出的猜测

**第四类"教育性猜测"值得单独记**：技术报告明确指出这些猜测的价值——让Orchestrator能够"以受限、带条件的方式表达记忆里的闭卷知识"，agent可以在卡住或者时间不够时依赖这些猜测给出一个最佳猜测答案，同时降低系统对错误/幻觉的整体敏感度。这些猜测会随着外层循环的推进被周期性更新，不是一次性写死的。

**第二步：制定计划**——只有事实摸底完成后，Orchestrator才会结合团队构成（每个agent的能力描述）和已知的Task Ledger，用自然语言写一份**逐条列出的分步计划**（bullet-point形式）。技术报告特别指出这份计划的定位——"以类似思维链提示的方式使用，更像是分步执行的一个提示（hint），Orchestrator和其他agent都不需要严格照着执行"。计划每次被重新审视（即每次外层循环重跑）时，**所有agent都会被强制清空上下文、重置状态**，防止旧计划的执行痕迹干扰新一轮尝试。

## 3 Progress Ledger——内层循环每一步要回答的五个问题，结构化JSON输出

内层循环的每一轮，Orchestrator要回答五个问题来生成Progress Ledger（源码`ORCHESTRATOR_PROGRESS_LEDGER_PROMPT`原文）：

1. **请求是否已经完全满足？**（True=完成，False=原始请求还没被成功、完全地处理）
2. **团队是不是在循环/重复自己？**（循环可以跨多轮，包括反复上下滚动这类重复动作）
3. **是不是在往前推进？**（刚开始算True；最近的消息在增加价值算True；如果最近消息显示卡在循环里，或者有明显障碍（比如读不了必须的文件）算False）
4. **接下来该谁发言？**（从团队成员里选）
5. **该给这个成员什么指令/问题？**（像直接对ta说话一样措辞，包含ta需要的具体信息）

这五个问题被要求输出成严格的JSON（源码给了完整schema，每个字段都带`reason`+`answer`两个子字段，也就是**每个判断都强制带一段推理说明，不是直接给结论**）。回答这五个问题时，Orchestrator会同时参考Task Ledger（事实、猜测、计划）和当前的agent对话上下文。

## 4 失速检测与重新规划——一个会升会降的计数器，触发后怎么重新来

**计数器机制**（源码`_magentic_one_orchestrator.py`，比论文原文的描述更精确）：

```python
# Check for stalling
if not progress_ledger["is_progress_being_made"]["answer"]:
    self._n_stalls += 1
elif progress_ledger["is_in_loop"]["answer"]:
    self._n_stalls += 1
else:
    self._n_stalls = max(0, self._n_stalls - 1)

# Too much stalling
if self._n_stalls >= self._max_stalls:
    await self._log_message("Stall count exceeded, re-planning with the outer loop...")
    await self._update_task_ledger(cancellation_token)
    await self._reenter_outer_loop(cancellation_token)
    return
```

**这不是一个只增不减的计数器**——"没有进展"或"在循环"会让计数器`+1`；但如果既有进展、又没在循环，计数器会`-1`（下限是0）。也就是说系统会**原谅偶发的小卡顿**，只要后续能重新走上正轨，之前累积的"可疑值"会被逐渐消解，不会因为中间某一步不顺就直接触发重新规划。

**阈值——论文和当前源码不一致，如实记录两个数字**：技术报告原文说实验里用的阈值是"≤2"；但当前`microsoft/autogen`仓库`_magentic_one_group_chat.py`里`max_stalls`的**默认值是3**（`max_stalls: int = 3`，"The maximum number of stalls allowed before re-planning. Defaults to 3."）。不确定是论文发表后代码调整过默认值，还是论文里指的是另一层含义的"2"，这次没有深挖版本历史，如实标注这个数字差异，不强行统一成一个。

**超过阈值后的重新规划，走两步固定的prompt**（源码`_prompts.py`）：

1. **`ORCHESTRATOR_TASK_LEDGER_FACTS_UPDATE_PROMPT`**——原文明确说"我们没有取得预期的进展，但可能学到了一些新东西"，要求重写事实清单，**特别要求"这是更新教育性猜测的好时机，请至少新增或更新一条猜测，并解释理由"**。
2. **`ORCHESTRATOR_TASK_LEDGER_PLAN_UPDATE_PROMPT`**——原文要求"简要说明上一轮到底哪里出了问题（失败的根因），然后给出一份新计划，这份计划要包含具体步骤和/或提示，专门用来克服之前遇到的障碍、尤其要避免重复同样的错误"。

**这两步合起来就是技术报告讲的"reflection and self-refinement step"**——重新规划不是简单地"再试一次"，是先强制做根因分析（"哪里出了问题"），再针对性地把这次学到的东西写进新计划里，而且更新事实清单和更新计划是两个独立的prompt步骤，不是一次性完成的。

**另有一层完全独立的团队级总轮次上限**：`max_turns`默认`20`（`_magentic_one_group_chat.py`），管的是整个团队对话的总轮次，触发条件是`self._n_rounds > self._max_turns`（`_magentic_one_orchestrator.py`第303行）——这跟"失速计数器"是两个完全独立的机制，一个管"卡住了要不要重新规划"，一个管"总共聊了多少轮该不该整个停下"，跟前一章（子Agent终止条件）学过的OpenAI`max_turns`/LangGraph`recursion_limit`是同一类"总量硬上限"，只是这次是加在整个多agent团队而不是单个agent身上。

## 5 消融实验：去掉ledger机制，性能掉多少

技术报告在GAIA验证集上做了消融实验，对照组是"把Orchestrator换成AutoGen的`GroupChat`机制"——这个baseline"简单地决定接下来该哪个agent发言，去掉了两份账本、规划、进度追踪、循环检测、以及给其他agent的明确指令"。**结果：没有完整的ledger机制，性能下降31%**。这是目前查到的、少数几个用量化消融实验直接证明"任务分解+进度追踪机制本身的价值"的官方材料，不是靠一句"我们认为这样更好"带过。

## 值得记的点

- **Progress Ledger强制每个判断都带`reason`**，是这次材料里对"怎么让LLM的自我评估更可靠"最具体的一个设计——不是直接问"卡住了吗"要一个bool，是要求先给推理再给结论，这跟"思维链"的原理是一致的，只是被结构化成了JSON schema的形式。
- **失速计数器是升降双向的，不是只增不减**——这个细节在user guide和论文的散文描述里都没有讲清楚，只有翻源码才看到`max(0, self._n_stalls - 1)`这一行。"给小错误一点容错空间"这个设计意图，靠这一行代码才真正落地。
- **重新规划走的是"先根因分析、再重新定计划"两步，且明确要求更新教育性猜测**——这比Anthropic博客那句"完善其策略"具体得多，是本章一直在找的"失败后怎么重新规划"这个问题目前查到的最详细答案。
- **论文数字（≤2）和当前源码默认值（3）不一致**，如实记录、不强行统一，这也是这次翻源码而不是只信任论文/文档转述的价值所在。
- **团队级`max_turns`（默认20）和失速计数器是两个独立机制**，跟"子Agent终止条件"那一章学过的"总量上限 vs 失速检测是两个不同维度"的结论完全对得上，只是这次的主体是"整个多agent团队"而不是单个subagent。
