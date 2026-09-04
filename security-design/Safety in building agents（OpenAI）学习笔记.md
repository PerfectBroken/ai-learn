# Safety in building agents 学习笔记

来源：OpenAI Platform文档，嵌在Agent Builder文档里，地址 https://platform.openai.com/docs/guides/agent-builder-safety 。

> Agent Builder已被OpenAI标记为废弃，定于2026-11-30下线；现役等价页面是Agents SDK下的[Guardrails](https://platform.openai.com/docs/guides/agents/guardrails-approvals)。

**读后结论**：逐条跟本章前面Anthropic三篇（sandboxing、how-we-contain-claude、auto-mode）核对下来，这篇文档整体偏浅——模型防护只说"用GPT-5/mini"没有数据支撑（对比Anthropic给的Gray Swan 0.1%/5-6%、auto-mode的FPR/FNR表）；"保持工具批准开启"完全没提审批疲劳这个Anthropic反复验证过、会让"始终要求批准"失效的现象；"用示例引导agent"只有两句空话，远不如`PromptEngineering.md`里对比过的具体模板和标签格式。原文七条建议里，只有以下一条半真正有信息量，值得留存复习，其余不再收录。

## 值得留存的内容

**不要在developer消息里用不可信变量**：developer消息的优先级高于user和assistant消息，直接把不可信输入注入developer消息，等于给了攻击者最大的控制力。应该把不可信输入放进user消息里传递，限制它的影响力——对那些把用户输入传给敏感工具或高权限上下文的工作流尤其重要。这是一个直接利用消息角色优先级这个既有机制的做法，不需要额外检测逻辑，是七条里最具体、最能直接照搬的一条。

**用结构化输出约束数据流（只有机制，没有落地细节）**：prompt注入往往依赖模型自由生成意料之外的文本或命令、再顺流传播下去；在节点之间定义结构化输出（枚举、固定schema、必填字段名），就能消灭掉攻击者可以用来夹带指令或数据的自由文本通道。**这条只给了"用什么类型的约束"这个概念层面的答案，没有给任何具体schema示例或配置步骤**，所以只能算半条——机制思路可以迁移到其他项目里，但没法直接照抄用法。

## 参考资料

- OpenAI, *Safety in building agents*, https://platform.openai.com/docs/guides/agent-builder-safety
