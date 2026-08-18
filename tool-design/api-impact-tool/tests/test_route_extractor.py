"""TDD ground truth for route_extractor.extract_routes().

All 9 expected routes below were hand-derived by reading every Controller in
~/Documents/projects/promotion-api directly (not inferred, not guessed).
They cover the 3 distinct Spring annotation shapes we found in that repo:

  explicit_value               @PostMapping("/x") or @PostMapping(value="/x")
  bare_inherits_prefix         @GetMapping with no arguments — path is 100%
                                the class-level @RequestMapping prefix
  request_mapping_with_method  @RequestMapping(value="/x", method=RequestMethod.POST)

GitNexus's native Route nodes only capture the first shape (3 of these 9) —
see ToolDesign.md for the source-level root cause. This test's job is to
prove our own extractor covers all three, not just the one GitNexus handles.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from route_extractor import (
    RouteRecord,
    extract_routes,
    _find_class_declaration_index,
    _find_method_name_after,
)

PROMOTION_API_PATH = os.path.expanduser("~/Documents/projects/promotion-api")

CONTROLLER_DIR = "src/main/java/com/sankuai/service/promotion/api/controller"

EXPECTED_ROUTES = [
    RouteRecord(
        http_method="POST",
        url="/aladdin/doctorEducateCardLike",
        class_name="AladdinController",
        method_name="doctorEducateCardLike",
        file_path=f"{CONTROLLER_DIR}/AladdinController.java",
        line_number=42,
        pattern="explicit_value",
    ),
    RouteRecord(
        http_method="POST",
        url="/audit/image",
        class_name="ContentAuditController",
        method_name="auditImage",
        file_path=f"{CONTROLLER_DIR}/ContentAuditController.java",
        line_number=42,
        pattern="explicit_value",
    ),
    RouteRecord(
        http_method="POST",
        url="/promotion/maoyan/assignCoupon",
        class_name="PromotionApiController",
        method_name="grabCoupon",
        file_path=f"{CONTROLLER_DIR}/PromotionApiController.java",
        line_number=42,
        pattern="explicit_value",
    ),
    RouteRecord(
        http_method="POST",
        url="/content/collect",
        class_name="ContentInteractionController",
        method_name="collect",
        file_path=f"{CONTROLLER_DIR}/ContentInteractionController.java",
        line_number=54,
        pattern="request_mapping_with_method",
    ),
    RouteRecord(
        http_method="POST",
        url="/content/like",
        class_name="ContentInteractionController",
        method_name="like",
        file_path=f"{CONTROLLER_DIR}/ContentInteractionController.java",
        line_number=69,
        pattern="request_mapping_with_method",
    ),
    RouteRecord(
        http_method="GET",
        url="/content/commentCount",
        class_name="ContentInteractionController",
        method_name="commentCount",
        file_path=f"{CONTROLLER_DIR}/ContentInteractionController.java",
        line_number=84,
        pattern="request_mapping_with_method",
    ),
    RouteRecord(
        http_method="GET",
        url="/content/commentList",
        class_name="ContentInteractionController",
        method_name="commentList",
        file_path=f"{CONTROLLER_DIR}/ContentInteractionController.java",
        line_number=90,
        pattern="request_mapping_with_method",
    ),
    RouteRecord(
        http_method="GET",
        url="/comparePrice",
        class_name="PromotionController",
        method_name="comparePrice",
        file_path=f"{CONTROLLER_DIR}/PromotionController.java",
        line_number=131,
        pattern="bare_inherits_prefix",
    ),
    RouteRecord(
        http_method="GET",
        url="/togetherCard",
        class_name="TogetherCardController",
        method_name="callOrderCard",
        file_path=f"{CONTROLLER_DIR}/TogetherCardController.java",
        line_number=102,
        pattern="bare_inherits_prefix",
    ),
]


@pytest.fixture(scope="module")
def extracted():
    """公共前置步骤：对真实的promotion-api仓库跑一次extract_routes()，
    结果在本文件内所有测试之间共享（scope="module"表示整个文件只跑一次，
    不用每个测试都重新扫一遍源码，省时间）。
    如果这台机器上没有promotion-api这个目录，直接跳过（不是失败）。
    """
    if not os.path.isdir(PROMOTION_API_PATH):
        pytest.skip(f"promotion-api not found at {PROMOTION_API_PATH}")
    return extract_routes(PROMOTION_API_PATH)


def test_finds_exactly_nine_routes_no_more_no_less(extracted):
    """粗粒度校验：总数必须正好是9条。
    多了说明有误报（比如把非路由的方法也当成了路由），
    少了说明有漏报（某种注解写法没覆盖到）。
    """
    urls = [(r.http_method, r.url) for r in extracted]
    assert len(urls) == 9, f"expected 9 routes, got {len(urls)}: {urls}"


@pytest.mark.parametrize("expected", EXPECTED_ROUTES, ids=lambda r: f"{r.http_method} {r.url}")
def test_each_known_route_is_found(extracted, expected):
    """细粒度校验：EXPECTED_ROUTES里的9条，每一条单独校验一次。
    用@pytest.mark.parametrize拆成9个独立的测试用例（而不是一个大for循环+一次assert），
    这样跑测试时能清楚看到具体是哪一条路由没通过，不用去猜是9条里的哪一条出了问题。

    每条校验两层：
    1. 先按(http_method, url)能不能在结果里找到对应的记录——找不到说明这条路由被完全漏掉了
    2. 找到了之后，再逐字段比对class_name/method_name/file_path/pattern是否都对得上——
       避免"URL蒙对了，但挂在了错误的方法/文件上"这种看似正确实则错误的情况
    """
    matches = [
        r for r in extracted
        if r.http_method == expected.http_method and r.url == expected.url
    ]
    assert matches, f"route {expected.http_method} {expected.url} not found at all"
    found = matches[0]
    assert found.class_name == expected.class_name
    assert found.method_name == expected.method_name
    assert found.file_path == expected.file_path
    assert found.pattern == expected.pattern


# 单独的回归测试：class级别@RequestMapping带method=参数的情况。
# 查过Spring官方源码的javadoc才知道，这个写法完全合法且有明确语义（class级别的method=
# 会被这个class下所有方法级别的映射继承），不是"不会有人这么写"的假设——
# 之前"没有method=就当作class前缀"这条推断规则，遇到这种写法会直接把class声明误判成
# 一条方法路由。这里用独立的临时目录测试，不动EXPECTED_ROUTES那9条真实数据。
CLASS_LEVEL_METHOD_CONTROLLER = """\
package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping(value = "/widgets", method = RequestMethod.GET)
public class WidgetController {

    @GetMapping("/list")
    public String list() {
        return "ok";
    }
}
"""


def test_class_level_request_mapping_with_method_is_not_treated_as_a_route(tmp_path):
    (tmp_path / "WidgetController.java").write_text(CLASS_LEVEL_METHOD_CONTROLLER)

    routes = extract_routes(str(tmp_path))

    # 只应该有WidgetController.list()这一条真实方法路由——
    # 如果class声明本身（@RequestMapping(value="/widgets", method=RequestMethod.GET)）
    # 被误判成了第二条路由，这里的数量就会变成2，而不是1
    assert len(routes) == 1, f"expected exactly 1 route (list), got: {routes}"
    route = routes[0]
    assert route.url == "/widgets/list"
    assert route.method_name == "list"
    assert route.class_name == "WidgetController"


# 回归测试：class声明之前的注释/javadoc里，恰好提到了"class 类名"这几个字，
# 不能被误判成真正的类声明位置——纯文本正则没有"这是不是在注释里"的概念，
# 必须靠额外的锚定条件（行首+可选修饰符）把这类巧合排除掉。
FALSE_POSITIVE_COMMENT_CONTROLLER = """\
package demo;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Handles widget requests, similar to class WidgetController in the legacy module.
 */
@RestController
@RequestMapping("/widgets")
public class WidgetController {

    @GetMapping("/list")
    public String list() {
        return "ok";
    }
}
"""


def test_class_index_ignores_coincidental_mentions_in_comments():
    body = FALSE_POSITIVE_COMMENT_CONTROLLER
    class_index = _find_class_declaration_index(body, "WidgetController")
    real_decl_index = body.index("public class WidgetController")
    assert class_index == real_decl_index, (
        "应该定位到真正的class声明，不是注释里提到的\"class WidgetController\"这句话"
    )


# 三个回归测试，覆盖"方法级别@RequestMapping没写method="时的三种真实情况——
# 全部依据Spring官方RequestMapping.method()的javadoc（"type级别的method=会被
# 方法级别继承"）和RequestMethodsRequestCondition的运行时源码（"method为空数组=
# 匹配所有HTTP方法，不是默认成某个动词"）。

# 情况1：方法带自己的path，但没写method=；class级别有method=限定——应该继承class的动词
INHERITS_CLASS_METHOD_CONTROLLER = """\
package demo;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping(value = "/widgets", method = RequestMethod.POST)
public class WidgetController {

    @RequestMapping("/list")
    public String list() {
        return "ok";
    }
}
"""


def test_method_level_request_mapping_inherits_class_level_method(tmp_path):
    (tmp_path / "WidgetController.java").write_text(INHERITS_CLASS_METHOD_CONTROLLER)
    routes = extract_routes(str(tmp_path))
    assert len(routes) == 1, f"expected exactly 1 route, got: {routes}"
    route = routes[0]
    assert route.http_method == "POST", "应该继承class级别@RequestMapping的method=POST"
    assert route.url == "/widgets/list"
    assert route.pattern == "request_mapping_inherits_class_method"


# 情况2：方法带自己的path，且方法完全裸写（连括号都没有）；class级别也有method=限定——
# 应该同时继承class的路径前缀和动词，方法自己一点信息都不贡献
FULLY_BARE_INHERITS_CONTROLLER = """\
package demo;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping(value = "/widgets", method = RequestMethod.DELETE)
public class WidgetController {

    @RequestMapping
    public String removeAll() {
        return "ok";
    }
}
"""


def test_fully_bare_method_level_request_mapping_inherits_path_and_method(tmp_path):
    (tmp_path / "WidgetController.java").write_text(FULLY_BARE_INHERITS_CONTROLLER)
    routes = extract_routes(str(tmp_path))
    assert len(routes) == 1, f"expected exactly 1 route, got: {routes}"
    route = routes[0]
    assert route.http_method == "DELETE"
    assert route.url == "/widgets"
    assert route.pattern == "request_mapping_inherits_class_method"


# 情况3：class和方法两级都没写method=——按Spring运行时的真实语义，这是一条
# "接受所有HTTP方法"的路由，不是"动词不明确所以跳过"
NO_METHOD_RESTRICTION_ANYWHERE_CONTROLLER = """\
package demo;

import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/widgets")
public class WidgetController {

    @RequestMapping("/anyMethod")
    public String anyMethod() {
        return "ok";
    }
}
"""


def test_no_method_restriction_anywhere_produces_any_route(tmp_path):
    (tmp_path / "WidgetController.java").write_text(NO_METHOD_RESTRICTION_ANYWHERE_CONTROLLER)
    routes = extract_routes(str(tmp_path))
    assert len(routes) == 1, f"expected exactly 1 route, got: {routes}"
    route = routes[0]
    assert route.http_method == "ANY", "两级都没有method=限定，应该是ANY，不是被跳过"
    assert route.url == "/widgets/anyMethod"
    assert route.pattern == "request_mapping_no_restriction"


# 回归测试：注解和方法声明之间夹了一段javadoc块注释——当前的过滤条件只挡住了
# "//"和"*"开头的行，没挡住"/**"这种块注释起始行，会导致往下找方法名的逻辑
# 直接放弃、返回(None, None)。
def test_find_method_name_after_skips_javadoc_block_between_annotation_and_method():
    body = (
        '@GetMapping("/list")\n'
        "/**\n"
        " * Lists all widgets.\n"
        " */\n"
        "public String list() {\n"
        '    return "ok";\n'
        "}\n"
    )
    lines = body.splitlines()
    method_name, line_number = _find_method_name_after(lines, 0)
    assert method_name == "list", f"应该找到list这个方法名，实际返回：{method_name}"
    assert line_number == 5  # public String list() { 在第5行（1-based）
