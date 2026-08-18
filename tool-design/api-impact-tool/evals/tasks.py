"""find_apis_affected_by_change 的评估任务清单。

设计标准来自Anthropic《Writing tools for agents》"Running an evaluation"一节：
- prompt不直接喂参数（repo_name/class_name/method_name），逼Agent自己从场景描述里判断
  该传什么、该不该用这个工具——避免"weak task"（原文反例：单步、参数已经喂好的调用）
- 全部基于promotion-api这个真实仓库上跑出来的真实结果，不是编造的sandbox数据
- 每条任务搭配一个可验证的outcome，但验证时不死抠措辞（原文："avoid overly strict
  verifiers that reject correct responses due to spurious differences...phrasings"）

每条任务的字段：
- prompt: 喂给Agent的原始场景描述
- needs_git: 是否需要git_diff工具（目前只有场景2需要）
- required_facts: 必须原样出现在最终回答里的事实性字符串（比如具体接口路径），
  这类是"硬事实"，允许精确字符串匹配，不算"过严"
- judge_rubric: 交给LLM judge去判断的定性结论，措辞不强制，只判断语义是否达标
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalTask:
    id: str
    scenario: str  # 对应我们之前讨论的两个使用场景 / 边界情况分类，仅用于报告分组
    prompt: str
    needs_git: bool
    required_facts: list[str]
    judge_rubric: str
    source: str  # 这条任务的ground truth数据来自哪里，方便复查


TASKS: list[EvalTask] = [
    EvalTask(
        id="design_exceeds_expectation",
        scenario="方案设计阶段",
        prompt=(
            "我打算修改 promotion-api 项目里 HttpResponseUtils 类的 "
            "createSuccessHttpResponse 方法的返回格式，加一个新字段。麻烦帮我确认一下"
            "这次改动会不会波及超出预期的对外接口——我以为顶多影响 /comparePrice 这一个接口。"
        ),
        needs_git=False,
        required_facts=["/comparePrice", "/togetherCard"],
        judge_rubric=(
            "回答必须明确指出：这次改动实际波及的接口范围超出了用户原本的预期——用户以为"
            "只影响 /comparePrice，但实际上还影响了 /togetherCard。只要清楚传达了"
            "'比预想的范围更大/超出预期'这个结论就算通过，不要求逐字匹配特定措辞。"
        ),
        source="README.md「已验证真实案例1」",
    ),
    EvalTask(
        id="review_matches_expectation",
        scenario="code review阶段",
        prompt=(
            "review 一下 promotion-api 项目 `eval-task/add-collection-null-check` 这个分支"
            "相对 `master` 的改动（仓库路径：/Users/guoxun/Documents/projects/promotion-api）。"
            "我们技术方案文档里写的预期影响接口是 POST /content/collect 和 "
            "GET /content/commentList 两个，帮我确认实现是否跟方案一致。"
        ),
        needs_git=True,
        required_facts=["/content/collect", "/content/commentList"],
        judge_rubric=(
            "回答必须确认改动波及的接口跟文档预期一致——POST /content/collect 和 "
            "GET /content/commentList 两个，不多不少，得出'一致/符合预期'这样的结论。"
        ),
        source="README.md「已验证真实案例2」+ 本次为评估专门在promotion-api建的真实分支",
    ),
    EvalTask(
        id="target_is_route_itself",
        scenario="边界情况",
        prompt=(
            "review时看到PR改了 promotion-api 的 PromotionController.comparePrice "
            "方法本身，帮我看下这次改动的影响范围。"
        ),
        needs_git=False,
        required_facts=["/comparePrice"],
        judge_rubric=(
            "回答必须明确指出 GET /comparePrice 这个接口受影响，不能因为工具返回的"
            "blast radius原始符号数是0，就误判成'这次改动没有影响任何接口'。"
        ),
        source="tests/test_api_impact.py::test_target_that_is_itself_a_route_handler...",
    ),
    EvalTask(
        id="nonexistent_symbol",
        scenario="边界情况",
        prompt=(
            "同事说要重构 promotion-api 项目的 LionContext.newFoodTemplateCtIds 方法，"
            "想确认下这次改动会不会影响到线上接口。"
        ),
        needs_git=False,
        required_facts=[],
        judge_rubric=(
            "回答必须说明查不到 LionContext.newFoodTemplateCtIds 这个符号（可能是类名/"
            "方法名拼写有误，或者这个符号根本不在这个仓库里），不能把'工具返回空结果'"
            "误判并直接给出'确认没有任何接口受影响，可以放心修改'这种过度肯定的安全结论——"
            "这两种情况（真的没有下游影响 vs 查无此符号）必须被明确区分开。"
        ),
        source="tests/test_api_impact.py::test_nonexistent_class_or_method_returns_empty...",
    ),
    EvalTask(
        id="unknown_repo",
        scenario="边界情况",
        prompt=(
            "确认下 payment-service 项目里 PaymentProcessor.chargeCard 这次改动的影响范围。"
        ),
        needs_git=False,
        required_facts=["promotion-api"],
        judge_rubric=(
            "回答必须说明 payment-service 这个仓库不在当前可用/已注册的仓库列表里，"
            "不能凭空编造一个查询结果；应该告知用户当前实际可用的仓库有哪些（比如promotion-api）。"
        ),
        source="config.json白名单机制",
    ),
]
