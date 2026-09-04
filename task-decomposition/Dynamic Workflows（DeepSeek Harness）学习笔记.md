# Dynamic Workflows（DeepSeek Harness）

官方来源：GitHub仓库[`deepseek-ai/deepseek-harness`](https://github.com/deepseek-ai/deepseek-harness)（MIT协议，开发者预览版，2026-08-13建仓库，截至学习时已20万+星）
本篇翻译的原文：仓库内部设计文档`.agents/notes/implemented/feature/2026-07-05-dynamic-workflows.md`（"Agent Note"，DeepSeek工程团队自己写的设计决策记录，不是面向用户的产品文档）
配套文档：`docs/subsystems/workflow.md`（面向开发者的接口/事件参考）
源码：`packages/workflow/`目录下`workflow`（核心引擎接口）、`workflow-worker-thread`（worker_threads实现）、`tool-workflow`（模型侧工具封装）

**范围说明**：这篇设计文档篇幅不长但信息密度很高，逐节翻译，不省略；源码部分只摘录了跟`parallel()`/`pipeline()`实现直接相关的片段（已source-verified）。

## 1 Problem——为什么要做这个功能

原文：

> The harness can delegate ONE task to ONE child (`dsh-tool-subagent`), but work that fans out across many independent pieces — an audit over many files, a migration, multi-angle research, adversarial verification of findings — forces the model to orchestrate turn by turn: every intermediate result lands in the parent context, the plan lives nowhere durable, and coordination costs a model round-trip per step. Claude Code ships this capability as [dynamic workflows](https://code.claude.com/docs/en/workflows): the model writes a JavaScript orchestration script, a runtime executes it, and the script — not the conversation — holds the loop, the branching, and the intermediate results.

翻译：Harness原本能把**一个**任务委派给**一个**子agent（靠`dsh-tool-subagent`这个工具），但遇到那种要扇出成很多独立小块的工作——对着一堆文件做审计、做迁移、多角度调研、对发现做对抗式验证——就只能逼着模型自己逐轮编排：每个中间结果都要落进父级上下文，计划本身没有一个持久存放的地方，每协调一步都要搭进去一次模型往返。Claude Code把这个能力做成了dynamic workflows：模型写一段JavaScript编排脚本，由一个runtime去执行它，**是这段脚本、而不是对话本身，拿着循环、分支判断和中间结果**。

## 2 Decision——设计决策

### 2.1 脚本约定："跟Claude Code兼容"

原文：

> A workflow call contains JSON `meta` (`name`, `description`, and optional `whenToUse`/`phases`) and a JavaScript `script` body with top-level `await` that returns a JSON value. Metadata is validated as data and never evaluated. The body receives `agent(prompt, options)`, `parallel(thunks)`, `pipeline(items, ...stages)`, `phase(title)`, `log(message)`, and `args`. Pipeline stages receive `(prev, item, index)` with no cross-stage barrier; failed children and ordinary stage errors resolve the affected item to `null` and skip its remaining stages. Claude Code's determinism restrictions are deferred with journaling, so compatible bodies may use clock and randomness after moving their meta header into the parameter.

翻译：一次workflow调用包含一份JSON格式的`meta`（`name`、`description`，可选的`whenToUse`/`phases`）和一段带顶层`await`、最终返回一个JSON值的JavaScript`script`脚本体。元数据是当作**数据**来校验的，**永远不会被求值执行**。脚本体能拿到`agent(prompt, options)`、`parallel(thunks)`、`pipeline(items, ...stages)`、`phase(title)`、`log(message)`和`args`这几个hook。`pipeline`的每个stage拿到的是`(prev, item, index)`，**stage之间没有屏障**；子任务失败和普通stage报错都会让对应的item降级成`null`、跳过它剩下的stage。Claude Code那套"禁止脚本碰时钟/随机数以保证可重放"的限制，这边跟带journal的resume功能一起被推迟了，所以只要把meta头挪到参数里，兼容的脚本体是可以用时钟和随机数的。

**接下来一句是唯一一处明确的分歧点**，原文：

> One deliberate strictness DIVERGENCE from CC: hook misuse — unknown or deferred options (`effort`/`isolation`/`agentType`), malformed arguments, schemas outside the supported subset, tripped caps, seam start failures — throws a `WorkflowError` with `fatal: true`, and the combinators RE-THROW fatal errors instead of nulling the item. Without this, a typo'd option dissolves into a `null` indistinguishable from a child failure — the accepted-then-ignored failure mode this repo bans. One addition: the tool's `args` parameter is a JSON OBJECT (a bare list is wrapped as a field) so the wire schema stays honest.

翻译：跟Claude Code之间**一处刻意的、更严格的分歧**：hook被误用的情况——未知或被推迟支持的选项（`effort`/`isolation`/`agentType`）、参数格式错误、schema超出支持的子集、撞到上限、seam启动失败——会抛出一个`fatal: true`的`WorkflowError`，`parallel()`/`pipeline()`这两个组合子会**把fatal错误重新抛出去**，而不是把对应item降级成`null`。**不这么做的话，一个写错的选项就会悄悄变成一个跟"子任务正常失败"分不清的`null`**——这正是这个仓库要禁止的"被接受了却被无声忽略"的失败模式。另加一条：这个工具的`args`参数被强制成JSON**对象**（如果传的是一个裸列表，会被包进一个字段里），为的是让接口的schema保持"诚实"。

### 2.2 Seam（`dsh-workflow`）

原文：

> `ctx.workflowEngine` is an abstract `WorkflowEngine` in the bash shape — one engine per context, no named-provider registry (engines are deployment swaps, not co-residents). `start(request)` throws synchronously for a script that cannot begin; a returned `WorkflowRun`'s `result` NEVER rejects (failures resolve as `stopReason: 'error' | 'cancelled'`). The `workflow/*` events are observe-only emits carrying DATA SNAPSHOTS (id + meta; `workflow/end` omits the result value), per-listener contained, mirroring `subagent/start`/`subagent/end` — control stays with the run's holder.

翻译：`ctx.workflowEngine`是一个抽象的`WorkflowEngine`，走的是跟bash那套一样的"seam"设计——每个context只有一个engine，没有按名字区分的provider注册表（多个engine是部署时互相替换的关系，不是同时共存的关系）。`start(request)`遇到一个根本没法启动的脚本会**同步**抛出；返回的`WorkflowRun`的`result`**永远不会reject**（失败会以`stopReason: 'error' | 'cancelled'`的形式resolve）。`workflow/*`这一组事件是只读的观察者事件，携带的是**数据快照**（id+meta；`workflow/end`故意不带result本身的值），每个监听器互相隔离不干扰，跟`subagent/start`/`subagent/end`是同一套设计——**运行的控制权始终留在持有这次run的调用方手里**。

### 2.3 引擎（`dsh-workflow-worker-thread`）：每次run一个worker线程

**信任前提**，原文：

> workflow scripts have the same trust as the model's bash access. The engine contains buggy scripts and guarantees settled results, JSON-safe values, and cancellation quiescence; it does not defend against hostile code. A vm context and worker thread are not security boundaries: a script can escape to Node APIs with process-wide authority. Sandboxing requires a separate-process or isolated-vm engine behind this seam.

翻译：workflow脚本享有的信任级别，跟模型能直接访问bash是一样的。引擎能兜住**有bug的**脚本、保证结果一定会settle、值是JSON安全的、取消操作最终会安静下来——但**不防御恶意代码**。vm context加worker线程**不是安全边界**：脚本能够逃逸到拥有整个进程权限的Node API上去。真要做沙箱，需要在这个seam背后换成独立进程或者`isolated-vm`引擎。

**为什么选`node:worker_threads`**，原文：

> each run gets one unpooled worker. A vm context limits the documented script API, while message-port RPC bridges `agent()` to host-side child loops. The worker prevents synchronous script work from blocking the host, provides a serialization boundary, and permits forced termination after cancellation. `isolated-vm` was rejected because of its maintenance state and deployment requirements.

翻译：每次run都拿到一个不复用的worker。vm context把脚本能用的API限制在文档写明的那些上，`agent()`通过message-port做的RPC，把调用桥接到host一侧真正的子agent循环里去。用worker能防止脚本里的同步代码卡住host主进程，还提供了一道序列化边界，取消之后能真正强制终止。`isolated-vm`被否决了，原因是它的维护状态和部署要求。

**Meta是数据，不是代码**，原文：

> The schema-validated `meta` field reaches the seam as JSON and is only shape-validated. The host never evaluates a metadata literal, which would let script-controlled accessors run outside the worker's isolation.

翻译：经过schema校验的`meta`字段是以JSON形式到达seam的，只做形状校验。**host永远不会去求值一个元数据字面量**——如果那样做，就等于让脚本能控制的getter之类的东西跑到worker的隔离范围之外去执行。

**值边界（`materializeFromRealm`）**，原文：

> copies outbound values and rejects functions, symbols, nested `undefined`, exotic prototypes, cycles, sparse arrays, and non-finite numbers. Data-property copies make `"__proto__"` safe; getters are read normally and a throwing getter fails loudly. `args` crosses through `workerData` and is cloned again before exposure.

翻译：这个函数复制所有要送出worker的值，同时拒绝函数、symbol、嵌套的`undefined`、异常的原型链、循环引用、稀疏数组和非有限数字。用"数据属性拷贝"的方式让`"__proto__"`这种键变得安全；getter会被正常读取，一个会抛异常的getter会直接、响亮地报错（不会被悄悄吞掉）。`args`要穿过`workerData`，暴露给脚本之前还会再clone一次。

### 2.4 Consumer（`dsh-tool-workflow`）

原文：

> A `workflow` tool mirroring `dsh-tool-subagent`'s synchronous shape: start, await, `try/finally` dispose, abort-bridge `exec.signal`, non-`completed` → `isError`. The tool description IS the model-facing authoring spec.

翻译：这是一个跟`dsh-tool-subagent`用的是同一套**同步**形态的工具：启动、等待、用`try/finally`保证一定会dispose、把取消信号桥接到`exec.signal`上、只要结束原因不是`completed`就映射成`isError`。**这个工具的描述文字本身，就是给模型看的、关于怎么写脚本的权威说明**——不是另外单独写一份文档。

### 2.5 结构化输出这项基础能力

原文：

> `SubagentStartRequest.outputSchema` is implemented by `dsh-subagent-in-process-driver`... An output schema makes a schema-valid committed capture mandatory for successful child completion... A validation failure remains a retryable tool error; clean completion without a committed capture settles as an error.

翻译：`outputSchema`这个能力是在子agent这一层（`dsh-subagent-in-process-driver`）实现的。一旦指定了output schema，子agent要**成功结束**就必须提交一份通过schema校验的"捕获结果"——校验失败是一个可以重试的工具错误；如果子agent干净地结束了、但压根没提交任何捕获结果，这次运行会被判定为失败。

## 3 Testing——测试怎么做的

原文提到：worker一侧的逻辑走一条进程内的`MessageChannel`测试路径，这样V8的覆盖率统计才能真正看到worker里跑的代码；单测覆盖脚本hook本身、fatal和可降级失败两种路径、JSON边界、各种上限、取消逻辑、子agent归属关系、以及结构化输出在真实循环里的表现；另外还有一个跑在纯Node环境下的构建产物冒烟测试，一个带真实key的端到端测试驱动真实子agent，模型侧的workflow行为则通过它自带的示例做快照测试。

## 4 Deferred——明确列出"现在故意不做"的功能清单

原文逐条列出（这一节非常值得完整看一遍，因为每一条都带了"为什么现在不做"的理由）：

- **后台执行的采集机制**（启动工具→拿到run id→完成通知→采集结果），要跟shell/subagent的后台统一设计放在一起做，现在还没做
- **Journaling+resume**（`resumeFromRunId`，缓存住`agent()`调用前缀）——原文原话："implementing it reintroduces CC's determinism bans as a script-contract tightening (scripts may read the clock)"，翻译：做这个功能，等于把Claude Code那套"脚本禁止碰时钟"的限制又给加回来了，而这边选择的是"脚本允许碰时钟"这条路，两者互斥
- **保存/打包的workflow**（一个`.deepseek/workflows/`注册表、类似斜杠命令的调用方式）和**脚本持久化到一个专门的run目录**（现在这次工具调用事件本身就已经把脚本记下来了，够用）
- **嵌套`workflow()`**、**token `budget`**、`effort`/`isolation`/`agentType`这几个agent选项——每一个如果被脚本用到，都会**响亮地报错**、并且在报错信息里点名"这个是被推迟的功能"，不是默默忽略
- **整体run的挂钟超时**——原文理由："cancellation always frees the caller (result settles within the grace), so a cap on total run time is a policy knob for the background redesign, not a correctness need here"，翻译：因为取消操作总能让调用方脱身（result会在一个有界的宽限期内settle），所以"整个run最多跑多久"这件事只是一个留给未来后台执行重新设计时的策略开关，不是现在正确性上必须有的东西
- **比worker线程更强的引擎加固**（真正的沙箱、内存限制，需要`isolated-vm`或独立进程）
- **ACP后端的结构化输出**和**`toolFilter`**——这两个能力目前都被标记成`false`

## 5 Alternatives considered——被否决的方案，附理由

摘几条最有代表性的（完整原文见仓库文档，这里翻译核心论点）：

- **在host一侧做"防恶意值"的额外防护**（比如无陷阱的proxy拒绝、永不触发getter的descriptor遍历）——被否决，理由是这类防护针对的是"信任前提里本来就接受的作者"，而worker线程自带的序列化边界已经天然让跨realm的值变成"安全的"了，没必要再加一层
- **纯`node:vm`（不用worker线程）**——机制上更简单（没有RPC、没有线程），但`start()`会在脚本第一次`await`之前的同步这一段**卡住调用方**，而这段同步执行一旦开始就杀不掉（vm的timeout只能管住这一段），`dispose()`也只能放弃一个没settle的脚本，管不了别的
- **把meta写在脚本体内的`export const meta = {...}`（照搬Claude Code的确切格式）**——能让脚本自包含、CC的脚本可以直接拿来用，但**拿到meta就得先在host上执行一部分模型写的文本**，哪怕是一个加了超时的空vm context，也管不住脚本控制的getter在host读取结果对象时被触发。改成一个独立的JSON参数，就不需要这套"扫描+执行+host被占用"的风险了；代价是CC脚本的meta头得挪个位置，脚本主体不用动
- **provider的JSON mode，用来代替"捕获工具"这套结构化输出机制**——被否决，理由是JSON mode只保证"这是合法JSON"，不保证"这符合你要的schema"，而且它跟工具调用怎么互相配合也说不清楚；"捕获工具"这条路能保留住"同一轮里校验失败可以重试"这个能力

## 6 Consequences——这个设计带来的后果

原文总结了几条实际后果：扇出式的计划现在能活在一份可以重新运行的脚本里；`outputSchema`能给出权威的、结构化的子任务结果；每次run都要付出worker启动和消息端口RPC的成本，但host启动不会被阻塞，取消操作能真正终止worker，序列化强制守住了值的边界；worker线程**不是**安全边界；参数写错会直接失败，而不是像Claude Code那样降级成`null`；调用方通过run handle始终保有控制权，观察者只能拿到快照；顶层Web用户还能获得一份持久、可回放的workflow记录，且不需要为此扩大执行层的seam、也不需要让原本通用的工具卡片去耦合workflow专属的UI。

## 附：`parallel()`/`pipeline()`的实际实现（源码验证，非文档转述）

源码位置：`packages/workflow/workflow-worker-thread/src/runtime.ts`

```typescript
/** The `parallel(thunks)` hook: each thunk caught → `null`; fatal errors propagate. */
private async parallel(rawThunks: unknown): Promise<unknown[]> {
  // ...参数校验、上限检查（略）
  return Promise.all(thunks.map(async (thunk) => {
    try {
      return await thunk()
    } catch (error: unknown) {
      // Hook failures are WorkflowErrors built OUTSIDE the script's realm;
      // fatality is recognized by `instanceof` against this realm's class —
      // a script-built object can never pass it, so fatality cannot be
      // forged (nor accidentally dissolved).
      if (isFatalWorkflowError(error)) throw error
      return null
    }
  }))
}

/** The `pipeline(items, ...stages)` hook: per-item stage chains, NO cross-stage barrier. */
private async pipeline(rawItems: unknown, rawStages: unknown[]): Promise<unknown[]> {
  // ...参数校验、上限检查（略）
  return Promise.all(rawItems.map(async (item: unknown, index) => {
    let value: unknown = item
    try {
      for (const stage of stages) {
        value = await stage(value, item, index)
      }
      return value
    } catch (error: unknown) {
      // An ordinary stage throw drops the ITEM to null and skips its
      // remaining stages; a fatal WorkflowError (see parallel()) kills the
      // whole script.
      if (isFatalWorkflowError(error)) throw error
      return null
    }
  }))
}
```

Tool description
```text
`Run a JavaScript workflow script that orchestrates subagents at scale. Use this for work that fans out across many independent pieces — an audit over many files, a migration, multi-angle research, adversarial verification of findings — where you write the orchestration as a script instead of delegating turn by turn.

The workflow's identity rides the \`meta\` parameter as JSON: required \`name\` (short kebab-case) and \`description\` strings, optional \`whenToUse\` string and \`phases\` array (\`{title, detail?, provider?, model?}\`). The \`script\` parameter is the plain JavaScript body ONLY (NOT TypeScript, and NO \`export const meta\` statement — meta is a parameter, not code), running with top-level await; end with \`return <value>\` — the value must be JSON-serializable and is this tool's result.

Script-body hooks:
- \`agent(prompt, opts?): Promise<any>\` — run one subagent to completion. Without \`opts.schema\` it resolves to the child's final text; with \`opts.schema\` (an object-rooted JSON Schema using ONLY type/properties/required/additionalProperties/items/enum/const/oneOf — no pattern/format/numeric bounds) it resolves to the validated object. Resolves \`null\` when the child fails (filter with \`.filter(Boolean)\`). Other opts: \`label\` (display), \`phase\` (progress group), and independent \`provider\`/\`model\` LLM target overrides (either may be provided alone). Anything else (\`effort\`/\`isolation\`/\`agentType\`) is rejected loudly.
- \`pipeline(items, ...stages): Promise<any[]>\` — run each item through the stages independently with NO barrier between stages (prefer this for multi-stage work). Each stage receives \`(prev, item, index)\`. An ordinary stage throw drops that ITEM to \`null\` and skips its remaining stages.
- \`parallel(thunks): Promise<any[]>\` — run zero-argument functions concurrently and await ALL of them (a barrier; use only when a stage genuinely needs every prior result together). A throwing thunk resolves to \`null\`.
- \`phase(title)\` — start a progress phase; \`log(message)\` — narrate progress; \`args\` — the tool call's \`args\` input, verbatim.

Misused hooks (bad arguments, unknown options, unsupported schemas, tripped caps) throw errors that ALWAYS kill the script — they never dissolve into a per-item \`null\`.

Constraints: concurrency and total-agent caps apply; no filesystem, network, timers, or Node.js APIs are provided — the agents do the work, the script only coordinates them. The run executes in the foreground: this call returns when the whole script finishes.`
```

```text
运行一个 JavaScript 工作流脚本，用于大规模编排子智能体。将其用于跨许多独立部分扇出的工作 —— 对许多文件的审计、迁移、多角度研究、对发现的对抗性验证 —— 在这些场景中，你将编排编写为脚本，而不是逐轮委派。

工作流的标识通过 `meta` 参数以 JSON 形式传递：必需的 `name`（短的 kebab-case 格式）和 `description` 字符串，可选的 `whenToUse` 字符串和 `phases` 数组（`{title, detail?, provider?, model?}`）。`script` 参数仅是普通 JavaScript 主体（不是 TypeScript，也没有 `export const meta` 语句 ——meta 是参数，不是代码），使用顶层 `await` 运行；以 `return <value>` 结束 —— 该值必须是 JSON 可序列化的，并且是此工具的结果。

**脚本主体钩子：**

- `agent(prompt, opts?): Promise<any>` — 运行一个子智能体直到完成。没有 `opts.schema` 时，它解析为子智能体的最终文本；有 `opts.schema`（一个对象根的 JSON Schema，仅使用 type/properties/required/additionalProperties/items/enum/const/oneOf—— 不使用 pattern/format/ 数值边界）时，它解析为验证后的对象。当子智能体失败时解析为 `null`（用 `.filter(Boolean)` 过滤）。其他选项：`label`（显示）、`phase`（进度组），以及独立的 `provider`/`model` LLM 目标覆盖（两者都可以单独提供）。任何其他内容（`effort`/`isolation`/`agentType`）都会被明确拒绝。
- `pipeline(items, ...stages): Promise<any[]>` — 独立地通过各个阶段运行每个项目，阶段之间没有屏障（多阶段工作优先使用此方法）。每个阶段接收 `(prev, item, index)`。普通阶段抛出异常会将该项目置为 `null` 并跳过其剩余阶段。
- `parallel(thunks): Promise<any[]>` — 并发运行零参数函数并等待所有函数完成（一个屏障；仅在某个阶段确实需要将所有先前结果放在一起时使用）。抛出异常的 thunk 解析为 `null`。
- `phase(title)` — 开始一个进度阶段；`log(message)` — 叙述进度；`args` — 工具调用的 `args` 输入，原样传递。

误用的钩子（错误的参数、未知的选项、不支持的模式、触发上限）会抛出错误，这些错误**总是**终止脚本 —— 它们永远不会消解为每个项目的 `null`。

**约束：** 并发和总智能体上限适用；不提供文件系统、网络、计时器或 Node.js API—— 智能体做工作，脚本只协调它们。运行在前台执行：当整个脚本完成时，此调用返回。
```

代码注释翻译：hook失败产生的`WorkflowError`是在脚本所在realm**之外**构造出来的；"是不是fatal"靠对着这个realm自己的类做`instanceof`判断——脚本自己造的对象天然过不了这个判断，所以fatal状态**既不能被伪造，也不会意外被消解掉**。普通的stage抛错会让**这一个item**降级成`null`、跳过它剩下的stage；一个真正的fatal `WorkflowError`则会杀死**整个脚本**。
