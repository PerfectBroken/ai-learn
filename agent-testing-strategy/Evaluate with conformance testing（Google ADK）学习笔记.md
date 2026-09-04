# Evaluate with conformance testing 学习笔记

来源：Google Agent Development Kit（ADK）官方文档"Why evaluate agents"里的"Evaluate with conformance testing"小节，地址 https://adk.dev/evaluate/#evaluate-with-conformance-testing 。本笔记不逐字翻译，是转述机制和操作流程，短句用引用块标出。

**这篇在本章的位置**：上一篇Anthropic的事故复盘只讲清楚了"为什么需要parity测试"（动机），完全没涉及"这套机制真跑起来长什么样"。这一篇是**机制篇**——具体讲清楚"parity/快照测试"落地成一套可执行工具时，该有哪些组件、怎么运作。

## 目录

- [1 是什么、解决什么问题](#1-是什么解决什么问题)
- [2 准备工作：先建一份金标准基线](#2-准备工作先建一份金标准基线)
- [3 目录结构和spec.yaml](#3-目录结构和specyaml)
- [4 自动录制基线，不要手写](#4-自动录制基线不要手写)
- [5 两种运行模式：Replay和Live](#5-两种运行模式replay和live)
- [6 怎么执行](#6-怎么执行)
- [7 对照问题二：这套机制能不能拦住那个bug](#7-对照问题二这套机制能不能拦住那个bug)

## 1 是什么、解决什么问题

`adk conformance test`命令做的事情，原文一句话概括：

> ensures that updates to your codebase or models don't introduce regressions by validating current agent outputs against baseline data

翻译：验证agent的行为随时间推移是否保持一致，确保代码或模型的更新不会引入回归，做法是把**当前的agent输出**拿去跟**基线数据**做校验。这是"parity测试"里"跟过去的自己比"这个变体的标准实现——本质是把《Demystifying evals》里"regression eval"这个抽象概念，落成了一套具体可执行的工具。

## 2 准备工作：先建一份金标准基线

在`adk conformance`命令能跑出有意义的回归测试结果之前，必须先建立一份"最优的金标准基线"（golden baseline）——conformance testing的运作方式，就是拿实时的agent行为去跟这份**预先录制、经过验证的交互记录**做对比。没有这份基线，这套机制就无从谈起。

## 3 目录结构和spec.yaml

Conformance test依赖一套固定的文件布局才能自动发现和匹配测试用例：

```
tests
└── category_name/
    └── test_case_name/
        ├── spec.yaml                  # 测试用例规格
        ├── generated-recordings.yaml   # 录制好的基线交互记录
        └── generated-session.yaml      # 基线session数据
```

如果agent用的是Server-Sent Events（SSE），同一个文件夹下还会额外找`generated-recordings-sse.yaml`和`generated-session-sse.yaml`这两个文件。

`spec.yaml`定义的是agent在录制基线、以及后续每次conformance跑的时候，要执行的初始条件、配置和用户输入。原文给的一个天气agent示例，大致结构是：说明这个用例要验证什么、指定用哪个agent、列出要发给agent的用户消息。测试用例的名字和分类，是从它所在的文件夹路径自动推断出来的，不需要在文件里重复写。

## 4 自动录制基线，不要手写

原文明确建议：

> Because the background data (like LLM requests and tool calls) is complex, you shouldn't try to write or save the baseline files manually. Instead, let ADK generate them for you.

翻译：LLM请求和工具调用这些背景数据太复杂，不该手写基线文件，应该让ADK自动生成。具体两步：先带着录制插件启动ADK的web server，再用`adk conformance record`命令、指向具体的测试用例路径，告诉ADK照着`spec.yaml`跑一遍场景并录制下来。命令末尾要带一个"流式模式"参数——`none`对应录制普通的`generated-recordings.yaml`/`generated-session.yaml`，`sse`对应录制SSE版本的两个文件；`bidi`（双向）模式目前不支持录制。跑完这一步，场景会被自动执行、交互被完整记录、生成的文件会被存到正确的位置，基线就算建好了。

## 5 两种运行模式：Replay和Live

基线建好之后，`adk conformance`支持两种运行模式：

- **Replay模式（默认）**：跑一遍你的agent，把它这次真实产生的LLM请求、响应、工具调用，**直接**跟之前录制好的交互记录做比对，抓取出意外的偏差。
- **Live模式**：针对活跃环境跑基于评估的验证，原文特别标注这个模式目前还在开发中（work in progress）。

## 6 怎么执行

跑全部测试（不指定路径时，工具会自动去找workspace里的`tests/`目录，跑里面所有内容）：直接执行`adk conformance test`。想缩小范围，可以传一个或多个文件夹路径，跑某个分类下的全部用例，或者精确到某一个具体用例。还可以加`--generate_report`标志生成一份Markdown格式的测试摘要报告，用`--report_dir`指定报告存放的位置。

## 7 对照问题二：这套机制能不能拦住那个bug

回到上一篇的背景——那个让Claude变"健忘"的缓存优化bug，只在"会话闲置超过一小时后恢复"这个边缘场景才触发。拿conformance testing这套机制对照一下，能不能拦住它，答案是**不一定，取决于两个前提条件**：

**第一个前提：测试用例的场景覆盖面够不够**。conformance testing的运作方式是"拿实时行为去跟一份预录的基线比"，但这份基线来自`spec.yaml`里定义的具体场景——如果当初没有一条用例专门覆盖"会话闲置超过一小时后恢复、再继续多轮对话"这种情况，那不管Replay模式跑得多严格，都没有对应的基线可以拿来比对，这个bug照样测不出来。**这一点跟上一轮我们讨论过的"eval覆盖面不够"是同一个坑**——conformance testing这套diff机制本身解决的是"拿什么去比"这个技术问题，不负责"该测哪些场景"这个覆盖面问题，两者是分开的。

**第二个前提：是不是拿同一套用例去跑了内部build和外部build两边**。原文这套机制描述的是"当前行为 vs 历史录制的基线"，如果一直只在内部环境里录基线、内部环境里跑Replay，那即便某条用例真的覆盖了闲置会话这个场景，测出来的也只是"内部环境这次的行为跟内部环境上次录的基线是否一致"——不会自动帮你发现"内部环境的行为，跟用户实际用的public build是否一致"这另一层parity问题。要拦住问题二那种bug，得**额外**拿这同一套conformance用例，专门对着public build也跑一遍、录一份独立的基线去对比，这是conformance testing这套机制之上，还需要主动加的一步，不是工具自带的默认行为。

一句话总结：conformance testing提供的是"怎么比对"这个通用机制，但"比对的对象覆不覆盖到关键场景"和"比对的双方是不是真的代表了内部/外部这两个该被比较的环境"，都需要使用者自己主动配置，机制本身不会替你把这两件事想清楚。

## 参考资料

- *Why evaluate agents* — Evaluate with conformance testing, Agent Development Kit (ADK) Docs, Google, https://adk.dev/evaluate/#evaluate-with-conformance-testing
