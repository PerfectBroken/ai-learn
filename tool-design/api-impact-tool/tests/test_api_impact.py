"""TDD ground truth for api_impact.find_affected_routes().

两条真实案例都是先用`gitnexus impact`实测拿到blast radius，再人工核对哪些受影响的
方法真的是路由（对照route_extractor.py那9条已验证的路由表），写成的标准答案——
不是靠猜测拼出来的，具体实测过程记在README.md的"已验证的真实案例"一节。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api_impact import find_affected_routes

PROMOTION_API_PATH = os.path.expanduser("~/Documents/projects/promotion-api")


@pytest.fixture(autouse=True)
def _skip_if_repo_missing():
    if not os.path.isdir(PROMOTION_API_PATH):
        pytest.skip(f"promotion-api not found at {PROMOTION_API_PATH}")


def test_deep_utility_method_affects_two_bare_annotation_routes():
    """HttpResponseUtils.createSuccessHttpResponse——实测(gitnexus impact --uid
    ...HttpResponseUtils.createSuccessHttpResponse#1 --direction upstream)的
    blast radius，depth 1上正好是comparePrice和callOrderCard这两个方法，
    没有更深层级。这两个都是GitNexus原生Route节点漏掉的"裸注解"路由。
    """
    result = find_affected_routes(
        PROMOTION_API_PATH, "HttpResponseUtils", "createSuccessHttpResponse"
    )

    assert result.target_class == "HttpResponseUtils"
    assert result.target_method == "createSuccessHttpResponse"
    assert result.direction == "upstream"

    urls = sorted((r.http_method, r.url) for r in result.affected_routes)
    assert urls == [("GET", "/comparePrice"), ("GET", "/togetherCard")]


def test_shared_service_method_affects_two_routes_and_filters_out_non_routes():
    """CollectionService.addCollection——实测blast radius有4个符号（collect、
    commentList、getCommentListResponse、getCommentListResponseV2），后两个是
    普通内部方法，不是路由，不应该出现在affected_routes里；total_impacted_count
    则应该如实反映"过滤前一共有几个符号"，不能悄悄把这个数字也改成2。
    """
    result = find_affected_routes(PROMOTION_API_PATH, "CollectionService", "addCollection")

    assert result.total_impacted_count == 4, (
        f"gitnexus impact实测blast radius是4个符号，不应该被过滤逻辑污染，"
        f"实际：{result.total_impacted_count}"
    )

    urls = sorted((r.http_method, r.url) for r in result.affected_routes)
    assert urls == [("GET", "/content/commentList"), ("POST", "/content/collect")], (
        f"getCommentListResponse/getCommentListResponseV2不是路由，"
        f"不应该出现在affected_routes里，实际：{result.affected_routes}"
    )


def test_target_that_is_itself_a_route_handler_reports_itself_as_affected():
    """边界情况：改动点本身就是一条路由入口（PromotionController.comparePrice）。

    实测过gitnexus impact comparePrice --direction upstream，impactedCount是0——
    Controller入口方法天然没有任何内部代码调用它（是被HTTP请求触发的），
    upstream blast radius对它来说永远是空的。但"改这个方法"显然100%会影响到
    它自己对应的这条路由，不能因为blast radius是空的就报告"没有命中任何接口"。
    """
    result = find_affected_routes(PROMOTION_API_PATH, "PromotionController", "comparePrice")

    urls = sorted((r.http_method, r.url) for r in result.affected_routes)
    assert urls == [("GET", "/comparePrice")], (
        f"改动点自己就是路由入口，应该报告自己这条路由，实际：{result.affected_routes}"
    )
    # total_impacted_count依然如实反映blast radius原始大小（这里是0），
    # 不能因为补上了目标自己而悄悄把这个数字也改掉——这两件事语义不同：
    # 一个是"这次改动波及了多少下游"，一个是"改动点自己是不是入口"
    assert result.total_impacted_count == 0


def test_nonexistent_class_or_method_returns_empty_result_instead_of_crashing():
    """边界情况：用户输入一个仓库里压根不存在的类名/方法名（实测确认过，
    LionContext.newFoodTemplateCtIds整个仓库都查不到）。

    实测发现gitnexus cypher在零匹配结果时返回裸的`[]`，不是`{"markdown": ...}`
    这个包装格式——之前的代码没处理这个分支，直接在result.get("markdown", "")
    这一步崩了（AttributeError: 'list' object has no attribute 'get'）。
    """
    result = find_affected_routes(PROMOTION_API_PATH, "LionContext", "newFoodTemplateCtIds")

    assert result.affected_routes == []
    assert result.total_impacted_count == 0
    assert result.risk == "UNKNOWN"
