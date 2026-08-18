"""Cross-references GitNexus's `impact` blast radius against our own
route table (route_extractor.extract_routes), to answer the question
GitNexus can't answer on its own: which HTTP endpoints does a change
to this symbol actually reach.

See README.md for the ApiImpactResult / RouteRecord field reference.
"""
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass

from route_extractor import RouteRecord, extract_routes

logger = logging.getLogger(__name__)

# class_name/method_name最终会拼进cypher查询字符串里——校验成合法的Java标识符，
# 避免注入（这个函数以后要包成MCP工具，输入来自Agent，不能默认它总是干净的）
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ApiImpactResult:
    """见README.md"ApiImpactResult"一节的权威字段说明，这里不重复写一遍，
    避免两个地方各改各的、慢慢就对不上。
    """
    target_class: str
    target_method: str
    direction: str
    risk: str
    total_impacted_count: int
    affected_routes: list[RouteRecord]


def _run_gitnexus(repo_path: str, args: list[str], timeout: int = 60):
    proc = subprocess.run(
        ["gitnexus", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(proc.stdout)


def _parse_cypher_single_column_rows(markdown: str) -> list[dict]:
    """解析`RETURN {...} AS info`这种单列map查询的markdown输出，
    每一行是`| {json} |`——把json取出来。前两行是表头和分隔线，跳过。
    """
    rows = []
    for line in markdown.splitlines()[2:]:
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        payload = line[1:-1].strip()
        try:
            rows.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return rows


def _resolve_uids(repo_path: str, class_name: str, method_name: str) -> list[str]:
    """用cypher直接按类名+方法名查UID，绕开`gitnexus impact`自带的、只能按文件
    路径消歧的机制——我们手上只有类名，没有文件路径。一个类名+方法名可能对应
    多个重载方法（比如HttpResponseUtils.createSuccessHttpResponse就有两个），
    全部返回，调用方自己决定要不要把它们的blast radius取并集。
    """
    if not _IDENTIFIER_RE.match(class_name) or not _IDENTIFIER_RE.match(method_name):
        raise ValueError(f"不是合法的Java标识符：{class_name}.{method_name}")

    query = (
        f"MATCH (m:Method) WHERE m.name = '{method_name}' "
        f"AND m.filePath CONTAINS '{class_name}.java' "
        f"RETURN {{id: m.id}} AS info"
    )
    result = _run_gitnexus(repo_path, ["cypher", query, "--limit", "20"])
    if isinstance(result, list):
        # gitnexus cypher在零匹配结果时返回裸的[]，不是{"markdown": ...}这个
        # 包装格式——只有真的查到结果才会用markdown包装，这是它自己的行为。
        # 说明类名/方法名在这个仓库里根本不存在，正常情况，不是错误
        return []
    rows = _parse_cypher_single_column_rows(result.get("markdown", ""))
    return [row["id"] for row in rows if "id" in row]


def _impact_for_uid(repo_path: str, uid: str, direction: str, depth: int):
    """跑一次gitnexus impact，带耗时监控——depth调大之后（复杂业务链路可能到30层），
    调用链越深、blast radius可能越大，这一步是整个函数里最可能变慢的地方，
    单独打点方便以后定位是哪个环节拖慢了整体响应。
    """
    start = time.perf_counter()
    result = _run_gitnexus(
        repo_path,
        ["impact", "--uid", uid, "--direction", direction, "--depth", str(depth), "--limit", "200"],
    )
    elapsed = time.perf_counter() - start
    logger.info(
        "gitnexus impact耗时%.3fs（uid=%s，direction=%s，depth=%d，impactedCount=%s）",
        elapsed, uid, direction, depth, result.get("impactedCount", "?"),
    )
    return result


def _collect_impacted_symbols(impact_result: dict) -> set[tuple[str, str]]:
    """从`gitnexus impact`的返回里，摊平出所有(类名, 方法名)对——不管在哪个depth。
    只挑Method/Function这两种kind，别的节点类型（比如Class本身）跟"哪个方法受影响"
    这个问题无关。
    """
    symbols = set()
    for depth_list in impact_result.get("byDepth", {}).values():
        for item in depth_list:
            file_path = item.get("filePath", "")
            class_name = file_path.rsplit("/", 1)[-1].removesuffix(".java")
            symbols.add((class_name, item["name"]))
    return symbols


def find_affected_routes(
    repo_path: str,
    class_name: str,
    method_name: str,
    *,
    direction: str = "upstream",
    depth: int = 50,
) -> ApiImpactResult:
    """给定一个改动点（类名+方法名），返回这次改动会波及哪些HTTP接口。

    流程：① 用cypher按类名+方法名解析出UID（可能不止一个，重载方法都要算）
    → ② 对每个UID分别跑gitnexus impact，取blast radius的并集（去重）
    → ③ 用extract_routes()建好的路由表，反查这些受影响的符号里哪些是路由。

    Args:
        repo_path: 目标Java仓库的根目录（绝对路径），必须是已经用`gitnexus analyze`
            建过索引的仓库——这个函数不负责建索引，只负责查询已有的索引。
        class_name: 改动点所在的类名（不含包名），比如"HttpResponseUtils"。
            必须是合法的Java标识符，会被直接拼进cypher查询里做类名过滤
            （`m.filePath CONTAINS '{class_name}.java'`），格式不对会抛ValueError。
        method_name: 改动点所在的方法名，比如"createSuccessHttpResponse"。
            同样必须是合法的Java标识符。如果这个类名+方法名对应多个重载方法，
            全部会被算进去，取blast radius的并集，不会因为重载而漏算或选错。
        direction: 传给`gitnexus impact`的`--direction`参数。目前场景只用得上
            "upstream"（默认值）——"改这个方法，会往上波及哪些调用它的地方"，
            也是我们唯一验证过的方向；"downstream"（这个方法依赖谁）理论上
            这套跨引用逻辑也能跑，但还没有真实案例验证过。
        depth: 传给`gitnexus impact`的`--depth`参数，blast radius最多往上追溯
            几层调用关系。默认50——两个已验证的真实案例（见README.md）实际用到
            的深度都不超过2层，但这只是promotion-api这个练习项目的规模；
            按真实生产项目的工程经验，复杂业务逻辑的调用链能到30层，50是在此
            基础上留出的余量，不能只照着练习项目的样本量定这个默认值。
            调大这个值意味着blast radius可能显著变大、`gitnexus impact`本身
            也可能变慢——`_impact_for_uid`对每次调用都做了耗时打点，日志里
            能看到具体是哪次调用慢。

    Returns:
        ApiImpactResult——字段说明见README.md的"ApiImpactResult"一节。
        如果class_name.method_name在仓库里一个符号都查不到（比如拼错了），
        不会报错，返回的是一个all-empty的结果（affected_routes是空列表，
        risk是"UNKNOWN"），调用方自己判断这种"查无此符号"的情况。
    """
    uids = _resolve_uids(repo_path, class_name, method_name)
    if not uids:
        logger.info("在%s.%s上没查到任何符号，可能类名/方法名拼错了（repo=%s）", class_name, method_name, repo_path)
        return ApiImpactResult(
            target_class=class_name,
            target_method=method_name,
            direction=direction,
            risk="UNKNOWN",
            total_impacted_count=0,
            affected_routes=[],
        )

    impact_start = time.perf_counter()
    all_symbols: set[tuple[str, str]] = set()
    max_risk = "LOW"
    risk_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "UNKNOWN": -1}
    for uid in uids:
        impact_result = _impact_for_uid(repo_path, uid, direction, depth)
        all_symbols |= _collect_impacted_symbols(impact_result)
        risk = impact_result.get("risk", "UNKNOWN")
        if risk_order.get(risk, -1) > risk_order.get(max_risk, -1):
            max_risk = risk
    impact_elapsed = time.perf_counter() - impact_start

    route_start = time.perf_counter()
    routes = extract_routes(repo_path)
    route_lookup = {(r.class_name, r.method_name): r for r in routes}
    affected_routes = [route_lookup[sym] for sym in all_symbols if sym in route_lookup]

    # 改动点自己如果就是一条路由入口，这条路由100%受影响——upstream blast radius
    # 天然不会包含目标符号自己（它只报告"谁调用了它"，Controller入口方法通常没有
    # 任何内部代码调用它），但改你自己就是在改这个接口本身，必须单独补上，不能
    # 因为它是"起点"而不是"被波及的下游"就被漏报。故意不计入total_impacted_count——
    # 那个字段的语义是"blast radius原始大小"，跟"改动点自己是不是入口"是两件事。
    target_key = (class_name, method_name)
    if target_key in route_lookup and target_key not in all_symbols:
        affected_routes.append(route_lookup[target_key])

    route_elapsed = time.perf_counter() - route_start

    logger.info(
        "%s.%s：blast radius共%d个符号，命中%d条路由——"
        "%d次gitnexus impact调用共%.3fs，路由表交叉比对%.3fs（repo=%s，depth=%d）",
        class_name, method_name, len(all_symbols), len(affected_routes),
        len(uids), impact_elapsed, route_elapsed, repo_path, depth,
    )

    return ApiImpactResult(
        target_class=class_name,
        target_method=method_name,
        direction=direction,
        risk=max_risk,
        total_impacted_count=len(all_symbols),
        affected_routes=affected_routes,
    )


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="给定一个改动点（类名+方法名），查它会影响哪些HTTP接口"
    )
    parser.add_argument("repo_path", help="Java仓库根目录（必须已经用gitnexus analyze建过索引）")
    parser.add_argument("class_name", help="类名，比如HttpResponseUtils")
    parser.add_argument("method_name", help="方法名，比如createSuccessHttpResponse")
    parser.add_argument("--direction", default="upstream", choices=["upstream", "downstream"])
    parser.add_argument("--depth", type=int, default=50)
    parser.add_argument("-v", "--verbose", action="store_true", help="打印耗时等详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        result = find_affected_routes(
            args.repo_path, args.class_name, args.method_name,
            direction=args.direction, depth=args.depth,
        )
    except ValueError as e:
        print(f"参数错误：{e}", file=sys.stderr)
        sys.exit(1)

    print(f"目标：{result.target_class}.{result.target_method}（{result.direction}, depth={args.depth}）")
    print(f"风险等级：{result.risk}")
    print(f"blast radius原始符号数：{result.total_impacted_count}")
    if not result.affected_routes:
        print("没有命中任何HTTP接口。")
    else:
        print(f"命中的HTTP接口（{len(result.affected_routes)}条）：")
        for r in result.affected_routes:
            print(f"  {r.http_method:6s} {r.url:40s} {r.class_name}.{r.method_name}  [{r.pattern}]")
