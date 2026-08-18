"""MCP stdio Server：把api_impact.find_affected_routes包装成一个Agent能调用的工具。

只暴露config.json白名单里配置好的仓库——Agent传的是"仓库名"，不是任意路径字符串，
不能让它随便指一个路径去扫描。这是Roots被废弃后官方推荐的替代方案之一（"用Server
自身配置传递目录范围"）的具体实践，见MCPProtocol.md 1.3节。
"""
import json
import logging
import os
from typing import Annotated

from pydantic import Field

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from api_impact import find_affected_routes

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

server = MCPServer(name="api-impact-tool")


def _load_repos() -> dict[str, str]:
    """读config.json，返回{仓库名: 仓库路径}这份白名单映射。"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    return {entry["name"]: entry["path"] for entry in config.get("repos", [])}


def _format_result(result) -> str:
    lines = [
        f"目标：{result.target_class}.{result.target_method}（{result.direction}）",
        f"风险等级：{result.risk}",
        f"blast radius原始符号数：{result.total_impacted_count}",
    ]
    if result.risk == "UNKNOWN":
        # risk=UNKNOWN只在_resolve_uids()完全查不到符号时才会出现（见api_impact.py），
        # 不是"确认没有下游影响"——把这句解释直接写进返回文本本身，不能只靠Agent记得
        # 工具description里<output_caveats>那段说明，那是读一次就要记住的隐性知识，
        # 这里改成每次调用都显式带出来，更稳。
        lines.append(
            f"查不到 {result.target_class}.{result.target_method} 这个符号，"
            "可能是拼写有误或者不在这个仓库里。"
        )
    elif not result.affected_routes:
        lines.append("没有命中任何HTTP接口。")
    else:
        lines.append(f"命中的HTTP接口（{len(result.affected_routes)}条）：")
        for r in result.affected_routes:
            lines.append(f"  {r.http_method} {r.url}  ({r.class_name}.{r.method_name}, {r.pattern})")
    return "\n".join(lines)


@server.tool(
    description="""给定一个代码改动点（类名+方法名），返回这次改动实际会波及哪些对外HTTP接口。

背景：通用的代码影响分析工具（比如GitNexus）能算出精确的方法调用blast radius，
但它们不理解Spring MVC的路由注解语义，无法把"这个方法受影响"翻译成"这个HTTP接口受影响"——
这个工具专门补上这一层，自己维护了一份更完整的路由表（覆盖了裸注解、通用@RequestMapping
等常见框架工具会漏掉的写法），跟blast radius做跨引用。

<when_to_use>
不是单纯的探索性查询，而是拿一个已有的预期去核对改动点实际波及的接口列表——这个预期
可以来自下面两种不同阶段：

<scenario name="方案设计阶段">
确定了具体的代码改动方案（要改哪个类、哪个方法）之后、改动落地前，用这个工具反向核对
一下实际影响范围是否符合预期——是一个改动前的安全检查。如果返回的接口列表超出了预期
范围，说明这次改动的影响面比想象的大，需要重新评估方案。
</scenario>

<scenario name="code_review阶段">
review一个改动的PR/diff时，如果技术方案文档写明了预期影响的接口范围，用这个工具核对
改动点实际波及的接口列表是否跟文档描述一致。如果不一致——多出文档未提及的接口，或者
文档提到的接口没有出现——说明实现跟方案脱节了，需要在review意见里指出具体的差异。
</scenario>
</when_to_use>

<output_caveats>
返回结果里的"风险等级"如果是UNKNOWN、且没有命中任何接口，这不等于"确认这次改动没有
影响"——UNKNOWN专门表示在仓库里完全查不到这个类名+方法名对应的符号（最常见的原因是
拼写错误，或者这个符号根本不在传入的这个仓库里）。这种情况下不能直接得出"可以放心
修改"的结论，应该先核实类名/方法名是否正确、以及改动是不是发生在预期的这个仓库里。
真正"确认没有下游调用方、可以放心修改"的情况，风险等级会是LOW/MEDIUM/HIGH这类正常
等级，而不是UNKNOWN——两种情况必须区分开，不能混为一谈。
</output_caveats>""",
    # 只读、不产生副作用——声明给MCP client，用来决定要不要在调用前弹确认框。
    # 见MCPProtocol.md Tools spec、ToolDesign.md 3.5节。
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def find_apis_affected_by_change(
    repo_name: Annotated[str, Field(
        description='配置文件里注册的仓库"名字"，不是文件系统路径。传错名字会返回错误并列出当前所有可用的仓库名，不需要提前枚举。',
        examples=["promotion-api"],
    )],
    class_name: Annotated[str, Field(
        description="改动点所在的类名，不含包名前缀，且必须是合法的Java标识符。",
        examples=["HttpResponseUtils"],
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )],
    method_name: Annotated[str, Field(
        description="改动点所在的方法名，必须是合法的Java标识符，不带括号和参数列表。如果这个类名+方法名对应多个重载方法，会自动合并所有重载的blast radius，不需要额外区分。",
        examples=["createSuccessHttpResponse"],
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    )],
    depth: Annotated[int, Field(
        description="blast radius最多向上追溯的调用层数，默认50，一般改动不需要调整。调大意味着可能捕获更深层的间接影响，但查询会变慢、结果也可能显著膨胀。",
        gt=0,
    )] = 50,
) -> str:
    repos = _load_repos()
    if repo_name not in repos:
        available = ", ".join(sorted(repos)) or "（配置文件里一个仓库都没有）"
        return f"未知的仓库名：{repo_name}。当前配置里可用的仓库：{available}"

    try:
        result = find_affected_routes(repos[repo_name], class_name, method_name, depth=depth)
    except ValueError as e:
        return f"参数错误：{e}"

    return _format_result(result)


if __name__ == "__main__":
    server.run(transport="stdio")
