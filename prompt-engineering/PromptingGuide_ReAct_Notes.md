> 原文：[ReAct Prompting](https://www.promptingguide.ai/techniques/react) — DAIR.AI《Prompt Engineering Guide》
>
> 逐节笔记，paraphrase不是逐句机翻。这篇是三篇里和你的"Agent工程师"学习方向关系最近的一篇——ReAct是"让模型交替做推理和行动"这个思路的源头论文，你之前在Context Window章节学到的agent循环、工具调用，理论源头很大程度上就是这篇。

## 这篇文档的定位

ReAct（Reasoning + Acting）由**Yao等人在2022年**的论文提出，核心论点是：把**推理（reasoning）**和**行动（acting）**这两件事**交替**结合起来，而不是分开处理。原文指出单纯用CoT提示（Wei等人2022年那篇）有一个明显短板：模型的推理完全封闭在自己的参数化知识里，**没有接入外部信息的能力**，容易产生事实性错误（说白了就是凭内部记忆瞎编）。ReAct的解法是：让模型在推理过程中**动态地**去查询外部信息源（比如知识库），一边推理、一边根据查到的新信息调整和修正自己的计划——原文提到，ReAct和CoT**结合使用**时效果最好。

## 一、工作原理：Thought → Act → Observation 循环

ReAct让模型生成的不是一整段连续文字，而是交替的三种内容：

- **Thought（思考）**：模型对当前状态的推理、下一步该做什么的判断
- **Act（行动）**：基于这个判断，调用一个具体的外部动作（比如发起一次搜索）
- **Obs（观察）**：外部环境（比如搜索引擎）返回的结果，反馈给模型作为下一轮Thought的输入

原文举了一个**HotPotQA**（一个需要多跳检索的问答数据集）的具体例子，问题是：

```
What is the elevation range for the area that the eastern sector
of the Colorado orogeny extends into?
```

（科罗拉多造山带东段所延伸到的区域，海拔范围是多少？）

模型通过**5轮**Thought-Act-Obs的循环来回答：先搜索"Colorado orogeny"，发现需要进一步定位"东段延伸到了哪个区域"，于是再搜索"High Plains (United States)"，逐步缩小范围，最终确定答案是**"1,800 to 7,000 ft"**。

原文提到一个使用上的经验区分：**需要大量推理的任务**（比如这种多跳问答）需要更多轮的Thought；而**偏决策类的任务**（比如玩一个文字游戏）里Thought可以更稀疏，不需要每一步都详细推理。

## 二、在知识密集型任务上的效果

研究者用**PaLM-540B**作为基座模型，在**HotPotQA**和**FEVER**（事实核查数据集）上评估了ReAct。对比结果：

- ReAct在两个数据集上都**优于Act**（只做行动、不做显式推理的对照组）
- 但在**HotPotQA**这个数据集上，**ReAct反而不如纯CoT**

原文的错误分析给出了三个具体原因：
1. **CoT容易"编造事实"**——因为它完全靠内部知识推理，没有外部校验
2. **ReAct的结构不够灵活**——固定的Thought-Act-Obs格式，限制了模型组织推理内容的自由度
3. **ReAct容易被"没有信息量"的搜索结果带偏**——如果某一步搜到的内容没什么用，模型有时难以从这种误导性信息里恢复过来，继续错下去

原文提到一个关键发现：把**ReAct和CoT+Self-Consistency结合起来的混合方法**，整体表现优于任何单一方法——这也印证了原文开篇的论点，ReAct和CoT不是互斥关系，组合使用效果最好。

## 三、在决策类任务上的效果

ReAct还在**ALFWorld**（基于文字的模拟游戏环境）和**WebShop**（模拟电商购物环境）这两个需要复杂推理和探索的场景下做了测试。原文提到：ReAct的prompt设计会针对具体场景做调整，但"推理和行动交替进行"这个核心结构保持不变。

结果显示：ReAct在这两个场景下都**大幅超过Act**（纯行动、不推理的对照组）——原文指出Act失败的根本原因是**没有能力把一个大目标拆解成一步步可执行的子目标**，而ReAct因为有显式的推理步骤,能做到这一点。不过原文也诚实地指出:即便有了这些改进,基于prompt的方法整体上依然**明显落后于专家级别的人类表现**。

## 四、用LangChain实现ReAct

原文给了一段可以直接运行的Python示例代码，用OpenAI模型配合LangChain库来实现ReAct agent，用来回答一个需要多步检索和计算的问题：

```
Who is Olivia Wilde's boyfriend? What is his current age raised
to the 0.23 power?
```

（Olivia Wilde的男朋友是谁？他现在的年龄的0.23次方是多少？）

Agent的执行过程是**自主**完成的：先搜索"Olivia Wilde boyfriend"，找到答案是Harry Styles；再查到他的年龄是29岁；最后计算29的0.23次方，得出**2.169459462491557**——整个过程**不需要人工手写few-shot示例**，因为LangChain这类框架已经把"Thought/Act/Observation"这套格式封装成了标准的agent执行循环，模型只需要按这套既定格式交替输出就行。

---

**小结**（金字塔顶层）：ReAct的核心贡献是提出了一个具体的**交替格式**（Thought→Act→Observation），把"模型该怎么想"和"模型该怎么用外部工具查证"缝合进了同一个可复现的循环里——这正是你之前在Context Window章节学到的"agent turn loop"（模型生成→调用工具→拿到结果→继续生成）背后的理论源头之一。原文也很诚实地指出了它的局限：**固定格式会限制推理的灵活性，且一旦被无效的检索结果带偏,很难自己纠正回来**——这也是为什么后续研究（比如上面Self-Consistency那篇提到的"多次采样投票"思路）会被拿来和ReAct组合使用,用来弥补单一格式、单一路径容易出错的问题。
