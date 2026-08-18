# api-impact-tool

给一个改动点（类名+方法名，或者文件+行号），算出这次改动会波及哪些对外HTTP接口。

背景：GitNexus的`impact`工具能在符号层面（方法调用图）算出精确的blast radius，
但它自带的Spring路由抽取器有结构性覆盖盲区（详见`ai-learn/tool-design/ToolDesign.md`），
漏掉了裸注解、通用`@RequestMapping(method=...)`这类写法的路由。这个项目做的事情，
是自己用FTS5+正则把路由表精确建全，再跟GitNexus算出来的blast radius做跨引用，
拿到"这次改动到底波及哪几个HTTP接口"这个GitNexus自己回答不出来的问题。

## 数据结构

### `RouteRecord`（定义于`route_extractor.py`）

一条HTTP路由，解析到具体的类+方法。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `http_method` | `str` | `"GET"`/`"POST"`等，大写；或者`"ANY"`——class和方法两级都没写`method=`时，按Spring运行时的真实语义（见`RequestMethodsRequestCondition`源码），这是一条明确定义的、接受所有HTTP方法的路由，不是该跳过的模糊情况 |
| `url` | `str` | 拼好的完整路径（class前缀+方法路径），永远以`/`开头 |
| `class_name` | `str` | 类名（不含包名），比如`PromotionController` |
| `method_name` | `str` | 处理这条路由的方法名，比如`comparePrice` |
| `file_path` | `str` | 相对仓库根目录的路径 |
| `line_number` | `int` | 方法级别路由注解所在的行号（1-based） |
| `pattern` | `str` | 这条记录是靠哪种注解写法解析出来的，五种取值： |

`pattern`的五种取值：

- `explicit_value`：`@PostMapping("/x")`或`@PostMapping(value="/x")`
- `bare_inherits_prefix`：`@GetMapping`裸写、无参数，路径完全继承class前缀
- `request_mapping_with_method`：`@RequestMapping(value="/x", method=RequestMethod.POST)`，方法自己指定了动词
- `request_mapping_inherits_class_method`：方法级别`@RequestMapping`没写`method=`，但class级别写了，继承class的动词
- `request_mapping_no_restriction`：class和方法两级都没写`method=`，`http_method`是`"ANY"`

### `ApiImpactResult`（定义于`api_impact.py`，设计中）

给定一个改动点，跨引用GitNexus的blast radius和我们自己的路由表之后的结果。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `target_class` | `str` | 改动点所在的类名 |
| `target_method` | `str` | 改动点所在的方法名 |
| `direction` | `str` | 传给`gitnexus impact`的方向，目前固定`"upstream"`（改这个方法，会往上波及谁） |
| `risk` | `str` | 透传自`gitnexus impact`自己给出的风险等级（`LOW`/`MEDIUM`/`HIGH`等） |
| `total_impacted_count` | `int` | blast radius里符号的原始总数（过滤成路由之前），用来看"过滤掉了多少非路由符号"，保留透明度、方便debug |
| `affected_routes` | `list[RouteRecord]` | blast radius里，跟我们自己的路由表匹配上的那部分——这才是最终想要的答案 |

## 已验证的真实案例（作为TDD的标准答案来源）

1. **`HttpResponseUtils.createSuccessHttpResponse`**（`gitnexus impact --uid ... --direction upstream`实测）
   → 波及 `PromotionController.comparePrice`（`GET /comparePrice`）、`TogetherCardController.callOrderCard`（`GET /togetherCard`）
   两个都是GitNexus原生Route节点漏掉的裸注解路由，只有我们自己的路由表能识别。

2. **`CollectionService.addCollection`**（`gitnexus impact addCollection --direction upstream`实测）
   → blast radius有4个符号（`collect`、`commentList`、`getCommentListResponse`、`getCommentListResponseV2`），
   其中只有`collect`（`POST /content/collect`）和`commentList`（`GET /content/commentList`）是真正的路由，
   后两个是普通内部方法——用来验证跨引用逻辑必须正确过滤掉非路由符号，不能blast radius有几个就算几个。

## 已实现

- `find_affected_routes(repo_path, class_name, method_name, *, direction="upstream", depth=50) -> ApiImpactResult`
  （`api_impact.py`）——核心入口，用cypher按类名+方法名解析UID（重载方法取blast radius并集），
  shell调用`gitnexus impact`拿blast radius，跟`extract_routes()`建好的路由表交叉比对。
  `depth`默认值从最初的5调整为50——两个已验证案例实际深度都不超过2层，但那只是练习项目的样本量，
  按真实生产项目的工程经验（复杂业务逻辑调用链能到30层），50是留出的余量，不能只照练习项目定。
  `_impact_for_uid`和整个跨引用流程都做了耗时打点（`logging`，not `print`——原因见1.5节MCP日志规范）。

## 待实现

- 文件+行号定位到类名+方法名的输入方式——待调研，可能借助GitNexus自带的`detect-changes`命令
