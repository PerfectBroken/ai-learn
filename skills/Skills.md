# Skills

Layer 2新增的一项，暂缓正式学习——先把Layer 3的Turn Loop这一章学完，再回头补这里。这份文档目前只是占位+记一条TODO，避免线索断掉。

## TODO：正式学习时要覆盖的内容

来自之前讨论已经确认的几个关键点（详见`agent-loop/`目录下的对话记录），正式展开时要覆盖：

- **Skills ≠ MCP的Prompts原语**——两者只是表面上都是"可复用的指令模板"，实际在归属层次（协议原语 vs 本地文件）、触发机制（MCP官方原文"Prompts are user-controlled" vs Skills"Claude dynamically decides"）、加载机制（渐进式披露 progressive disclosure）三个维度都不同，这条对比已经在对话里讲透，正式写文档时可以直接搬过去，不用重新调研。
- **Skill的调用没有专属语法掩码**——已经用当前会话自己的`Skill`工具JSON Schema验证过：`skill`参数是`"type": "string"`，不是`enum`，说明"选中哪个skill"完全靠模型自由语义推理，没有掩码兜底，跟"选哪个工具"这一步（有语法约束解码保证）是不同可靠度的两件事。
- **Skill和Tool同等相关度时选谁，官方承认没有确定性规则**——Claude Code官方文档原话："the model is choosing other tools or approaches... Strengthen the skill's description... or use hooks to enforce behavior deterministically"，没有优先级参数，需要确定性结果只能靠hooks硬编码。

## TODO：OpenClaw源码和流程会是很好的示例

在学`agent-loop/TurnLoop.md`里OpenClaw那两张图（`openclaw-loop-trigger-flow.svg` / `openclaw-architecture.svg`）时，发现`runEmbeddedAgent`内部"Prompt组装"这一步的组成是——

> base prompt + **skills prompt** + bootstrap上下文 + 本次运行覆盖项

**skills prompt是系统提示词里独立的一段**，跟`Skills`这个机制怎么把"有哪些skill可用"塞进模型看到的上下文，是直接对应的真实工程案例。正式学习Skills时，值得回到OpenClaw源码里查证：

- `skills prompt`具体在哪个文件里拼装（沿用当时验证`before_model_resolve`用的方法：`gh search code`直接搜关键词，别猜）
- OpenClaw的skills快照（"loads the skills snapshot"）机制，跟Claude Code官方文档说的"渐进式披露"（先加载name+description，命中才加载完整内容）是不是同一套实现思路，还是有自己的差异
- OpenClaw的skill发现/加载时机（Run sequence第2步"agentCommand...loads the skills snapshot"）跟Claude Code的"session开始时加载description，调用时才加载全文"这个时序对不对得上

## 参考资料（先记下来，正式学习时再精读）

- Claude Code Docs，[Extend Claude with skills](https://code.claude.com/docs/en/skills)——官方产品文档，`SKILL.md`格式、`disable-model-invocation`/`user-invocable`等frontmatter字段、渐进式披露的token预算机制（`skillListingBudgetFraction`等）
- Anthropic Blog，[Skills explained](https://claude.com/blog/skills-explained)——理念层，Skills vs Prompts（注意这里的"Prompts"指对话里临时给的指令，不是MCP的Prompts原语，别搞混）、Skills vs MCP的定位区分
- OpenClaw，[Agent loop](https://docs.openclaw.ai/concepts/agent-loop)——已经翻译在`agent-loop/Agent loop（OpenClaw）学习笔记.md`里，Prompt组装那节提到skills prompt，是这里TODO的源头
