# ToolAnnotations vs Elicitation：两种容易被当成同一件事的"确认机制"

**结论：官方没有定义这两者之间的映射关系——命中`ToolAnnotations`里任何一个hint（包括`destructiveHint`），都不会触发Elicitation。这是两套独立机制，分别管"要不要允许这个动作发生"和"执行过程中还缺什么信息"，只是因为都长得像"弹个框问用户"，容易被当成同一件事。**

## 为什么会搞混

[MCPProtocol.md §5](../mcp-protocol/MCPProtocol.md#5-trust--safety权限与同意机制)把Trust & Safety拆成四条原则时，Tool Safety对应`ToolAnnotations`，User Consent and Control对应Elicitation——两条原则挨在一起讲、又都落地成"用户看到一个交互界面"，很容易顺着以为它们是同一套机制的两个开关，或者以为hint的取值会决定要不要走Elicitation流程。

## 核心区别

| | ToolAnnotations（含`destructiveHint`） | Elicitation |
| --- | --- | --- |
| 谁来触发 | Client根据hint自行决定要不要弹确认框 | Server自己的业务代码在执行过程中决定 |
| 发生在什么时候 | **调用工具之前**——动作还没发生 | **执行过程中**——已经在执行了，但缺数据 |
| 回答的问题 | "要不要允许这个动作发生" | "我还需要哪些信息才能把这件事做完" |
| 强制性 | 纯hint，**不是enforcement**，Client可以忽略，对不可信Server的hint必须当成不可信数据 | Server主动发起的协议请求，Client按能力协商决定接不接 |
| 协议机制 | 静态元数据字段，随`tools/list`一起声明 | 动态协议消息，通过[MRTR](../mcp-protocol/MCPProtocol.md#24-mrtrmulti-round-trip-requests为什么上面这张图长这样)在`tools/call`过程中来回 |

## 权威依据

MCP官方博客专门有一篇文章讨论这四个hint的定位——[Tool Annotations as Risk Vocabulary: What Hints Can and Can't Do](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)，原文给的例子是：

> "A tool marked `readOnlyHint: true` from a trusted server might be auto-approved, while `destructiveHint: true` gets a confirmation step."

关键在"**might**"这个词——文章明确说这只是"Client可以怎么做"的示例，不是协议规定的必须行为，并且反复强调：

> "They aren't enforcement." ——hint不是强制机制，不能替代确定性的安全控制。

另一侧，[Elicitation官方规范](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)通篇没有出现过"annotation"或"hint"字样——触发Elicitation的唯一依据是Server自己的业务逻辑判断（比如订单金额超过阈值），跟这个工具声明了什么hint毫无关系。

## 常见误区纠正

- **"这个工具是`readOnlyHint: true`，所以不需要Elicitation"——结论没错，但因果关系写反了。** 真正的原因是这个工具的业务逻辑里根本不存在"执行到一半需要问用户要更多信息"的场景，`readOnlyHint: true`只是这个事实的**结果**，不是**原因**。反过来，一个`readOnlyHint: true`的纯查询工具，理论上完全可以用Elicitation（比如查询条件太模糊，弹个表单问"你是指A还是B"）。
- **`destructiveHint: true`不会自动触发Elicitation。** 它最多让Client在调用前多弹一个"是否允许执行"的确认框（yes/no级别），跟Elicitation能收集结构化表单数据、甚至跳到URL做带外交互，是完全不同量级的交互。

## 参考来源

- MCP官方博客，[Tool Annotations as Risk Vocabulary](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)
- [Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)（Data Types / annotations一节）
- [Elicitation specification](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation)
