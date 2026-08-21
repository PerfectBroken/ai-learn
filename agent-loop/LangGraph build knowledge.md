# LangGraph Build Knowledge

实操性质的配置笔记，不是学习笔记——记录怎么把"IDE能标红的类型契约检查"落地成CI里真正拦人合并的强制门禁，方便以后工作直接抄。背景讨论见`agent-loop/TurnLoop.md`和`Graph API overview（LangGraph）学习笔记.md`：LangGraph的`InputState`/`OutputState`/`PrivateState`这套schema拆分，本质是类型契约、不是运行时隔离，`mypy`是把这份契约从"建议"升级成"强制"的现成工具。

## 1. mypy

### 安装

```bash
pip install mypy
# 或者项目用uv/poetry管理依赖
uv add --dev mypy
poetry add --group dev mypy
```

### 配置（`pyproject.toml`）

```toml
[tool.mypy]
python_version = "3.12"
strict = true                    # 打包了一整套严格检查，包括对TypedDict/返回值的检查
warn_unused_ignores = true       # 防止留下已经失效的 # type: ignore
warn_redundant_casts = true
disallow_untyped_defs = true     # 禁止没写类型标注的函数
no_implicit_optional = true

# 只在你的源码目录上跑，不要扫第三方依赖
files = ["src"]

[[tool.mypy.overrides]]
module = "langgraph.*"
ignore_missing_imports = true    # 如果langgraph自己的类型stub不全，先放行第三方包本身
```

`strict = true`已经包含了`TypedDict`字段访问/返回值形状的检查，不需要额外开关——这正是能拦住"`node_1`标了`state: InputState`、函数体里却写`state["graph_output"]`"这类问题的能力来源。

### 运行

```bash
mypy .
# 只查某个目录
mypy src/agents/
```

### 能拦住 vs 拦不住（复述一下，落地前心里要有数）

- **能拦住**：代码里字面写死的、访问了`TypedDict`未声明字段的情况；返回值字面量里塞了声明类型里没有的key。
- **拦不住**：运行时动态拼出来的key（比如`state[some_variable]`），静态分析工具在检查阶段没法预判`some_variable`的值。

## 2. 接入CI（GitHub Actions）

光有配置文件、本地能跑，不代表能拦人——**必须让CI在每次PR上都跑一遍**。`.github/workflows/type-check.yml`：

```yaml
name: Type Check

on:
  pull_request:
  push:
    branches: [main]

jobs:
  mypy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install mypy
          pip install -e .          # 装上项目本身和它的依赖，mypy才能解析import
      - name: Run mypy
        run: mypy .
```

## 3. 关键的最后一步：设成"required check"——这一步最容易被漏掉

**光有上面这个workflow文件，PR页面会显示一个✅/❌的状态，但默认情况下这个检查失败照样能合并**——除非仓库管理员显式把它设成"必须通过才能合并"的强制门禁。这一步是纯配置，不是代码，两种做法：

### 方式一：GitHub网页操作（一次性设置，最直观）

仓库 → **Settings** → **Branches** → 给`main`（或目标分支）**Add branch protection rule** → 勾选**"Require status checks to pass before merging"** → 在搜索框里找到刚才workflow里的job名字（`mypy`）勾上 → Save。

### 方式二：用`gh api`脚本化设置（适合批量给多个仓库配置、或者写进仓库初始化脚本）

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "repos/{owner}/{repo}/branches/main/protection" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=mypy" \
  -F "enforce_admins=true" \
  -F "required_pull_request_reviews=null" \
  -F "restrictions=null"
```

`{owner}`/`{repo}`会自动替换成当前目录对应的仓库（也可以显式写死）；`required_status_checks[contexts][]=mypy`里的`mypy`要跟workflow文件里定义的**job名字**完全一致（上面例子里`jobs:`下面那个`mypy:`）。这条命令是**覆盖式**的——如果分支已经有其他保护规则（比如要求review），要先用`gh api repos/{owner}/{repo}/branches/main/protection`（不带`--method PUT`，默认GET）读出现有配置，合并后再整体PUT回去，不要用这条命令直接覆盖一个已经配置过的分支。

<!-- 未查证：这里用的是Branch Protection的经典REST接口（长期稳定、文档明确），GitHub近两年主推的是更新的Rulesets接口（`gh api repos/{owner}/{repo}/rulesets`），两者可以共存但语义上有重叠，具体该用哪个取决于团队现有的分支管理方式是不是已经上了Rulesets，用之前建议先跑一次GET确认现状，没有验证过两者混用会不会冲突。 -->

## 4. 尚未验证的开放问题：LangGraph图拓扑专属的静态检查

`mypy`只懂Python的类型系统，不懂`StateGraph`/`add_conditional_edges`这些LangGraph特有的语义——比如"某个key被两个节点在同一超步里并行写、但没配reducer"、"某节点声明的`input_schema`跟它实际能被路由到的边是否自洽"，这类跟**图拓扑**绑定的规则，通用类型检查器管不到。这块有没有现成的社区工具，讨论时没有查证过，如果以后要认真治理这类问题，值得专门搜一次、或者参考当年写Maven插件拦bad case的思路自己写一个理解图结构的AST/静态分析工具。
