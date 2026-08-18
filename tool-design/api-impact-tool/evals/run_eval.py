"""find_apis_affected_by_change 的评估runner。

做法对应Anthropic《Writing tools for agents》"Running an evaluation"一节：
  "We recommend running your evaluation programmatically with direct LLM API calls.
   Use simple agentic loops (while-loops wrapping alternating LLM API and tool calls):
   one loop for each evaluation task."
以及要收集的指标原文列了四项：
  "the total runtime of individual tool calls and tasks, the total number of tool
   calls, the total token consumption, and tool errors"

跑法：
1. 起一个到本地server.py的MCP连接（跟mcp-protocol那一章的脚本用的是同一套verified机制）
2. 把MCP的tool schema转成Claude API的tool格式（字段名本来就都叫input_schema，不用改key）
3. 场景2额外挂一个范围很窄的git_diff工具（只能跑`git diff <base>..<head>`，不是通用Bash——
   自动化跑评估、无人值守的场景下，不该给模型开放执行任意命令的权限）
4. 每条任务一个while循环：LLM生成tool_use → 执行 → 结果喂回 → 直到LLM不再调工具
5. 每条任务跑完，用「硬事实字符串匹配」+「LLM judge」两层校验——硬事实（比如具体接口
   路径）用字符串精确匹配；定性结论（比如"超出预期"）交给judge做语义判断，不死抠措辞
   （原文："avoid overly strict verifiers that reject correct responses due to
   spurious differences like formatting, punctuation, or valid alternative phrasings"）

运行前提：
- 依赖 ../venv 这个虚拟环境（已装好 mcp、pydantic、anthropic）
- 需要设置 ANTHROPIC_API_KEY，或者用 `ant auth login` 登录过——这里没做这层校验，
  没配凭证的话Anthropic SDK自己会抛认证错误
"""
import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from tasks import TASKS, EvalTask

PROJECT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PYTHON = os.path.join(PROJECT_DIR, "venv", "bin", "python3")
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

def _resolve_model() -> str:
    """根据ANTHROPIC_BASE_URL自动识别当前指向哪家provider，选对应的模型名——
    这样切换provider（比如DeepSeek的Anthropic兼容端点 vs 真正的Claude API）时，
    只需要改环境变量，不用再回来改这行代码。
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if "deepseek" in base_url.lower():
        return "deepseek-v4-pro"
    return "claude-sonnet-5"


MODEL = _resolve_model()
MAX_TURNS = 10  # 防止agent loop因为异常状态死循环

GIT_DIFF_TOOL = {
    "name": "git_diff",
    "description": (
        "查看指定Git仓库里，两个分支/commit之间的diff内容，用来发现一次改动具体改了"
        "哪些文件、哪些类/方法。只能做只读的diff对比，不能执行其他git操作。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "repo_path": {"type": "string", "description": "仓库的本地绝对路径"},
            "base_ref": {"type": "string", "description": "对比基准，比如 master"},
            "head_ref": {"type": "string", "description": "要看改动的分支/commit"},
        },
        "required": ["repo_path", "base_ref", "head_ref"],
    },
}

def run_git_diff(repo_path: str, base_ref: str, head_ref: str) -> str:
    """执行范围被锁死的`git diff <base>..<head>`，不接受任何其他git子命令或参数。"""
    result = subprocess.run(
        ["git", "diff", f"{base_ref}..{head_ref}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return f"git diff执行失败：{result.stderr}"
    return result.stdout or "(两个ref之间没有差异)"


@dataclass
class TaskMetrics:
    turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    tool_call_seconds: float = 0.0
    wall_seconds: float = 0.0


async def mcp_tools_to_anthropic_format(mcp_session: ClientSession) -> list[dict]:
    result = await mcp_session.list_tools()
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in result.tools
    ]


async def execute_tool_call(mcp_session: ClientSession, name: str, tool_input: dict) -> tuple[str, bool]:
    """返回(结果文本, 是否出错)。git_diff走本地函数，其余走MCP的call_tool。"""
    if name == "git_diff":
        try:
            return run_git_diff(**tool_input), False
        except Exception as e:
            return f"git_diff执行异常：{e}", True

    try:
        result = await mcp_session.call_tool(name, tool_input)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        return text, bool(result.is_error)
    except Exception as e:
        return f"MCP工具调用异常：{e}", True


async def run_agent_loop(
    client: AsyncAnthropic, mcp_session: ClientSession, task: EvalTask, mcp_tool_defs: list[dict]
) -> tuple[str, list[dict], TaskMetrics]:
    tools = mcp_tool_defs + ([GIT_DIFF_TOOL] if task.needs_git else [])
    messages: list[dict] = [{"role": "user", "content": task.prompt}]
    metrics = TaskMetrics()
    wall_start = time.perf_counter()

    for turn in range(1, MAX_TURNS + 1):
        # 加这行打印是因为实测踩过一次坑：模型响应慢（尤其是开了adaptive thinking）
        # 跟真的卡死，从终端上看是一样的——沉默。没有这行进度提示，没法区分这两种情况
        print(f"  [第{turn}轮] 等待模型响应...")
        turn_start = time.perf_counter()
        response = await client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            tools=tools,
            messages=messages,
        )
        print(f"  [第{turn}轮] 响应耗时{time.perf_counter() - turn_start:.1f}s，stop_reason={response.stop_reason}")
        metrics.turns += 1
        metrics.input_tokens += response.usage.input_tokens
        metrics.output_tokens += response.usage.output_tokens
        metrics.cache_read_tokens += response.usage.cache_read_input_tokens or 0
        metrics.cache_creation_tokens += response.usage.cache_creation_input_tokens or 0

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = next((b.text for b in response.content if b.type == "text"), "")
            metrics.wall_seconds = time.perf_counter() - wall_start
            return final_text, messages, metrics

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            metrics.tool_calls += 1
            print(f"    → 调用工具 {block.name}（{block.input}）...")
            call_start = time.perf_counter()
            text, is_error = await execute_tool_call(mcp_session, block.name, block.input)
            call_seconds = time.perf_counter() - call_start
            metrics.tool_call_seconds += call_seconds
            print(f"    ← 工具返回（{'出错' if is_error else '正常'}），用时{call_seconds:.1f}s")
            if is_error:
                metrics.tool_errors += 1
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error}
            )
        messages.append({"role": "user", "content": tool_results})

    metrics.wall_seconds = time.perf_counter() - wall_start
    return "(超过MAX_TURNS轮次限制，任务未正常结束)", messages, metrics


def _extract_json_object(text: str) -> dict:
    """从judge模型的回复里尽量抠出一个JSON对象——不依赖`output_config.format`这类
    Claude专属的结构化输出保证（DeepSeek等其他Anthropic兼容端点不一定支持这个字段，
    实测DeepSeek的兼容层明确写了"仅支持effort"，format不在支持范围内）。

    容错程度从严到松依次尝试：整段本身就是合法JSON → 被markdown代码块包住的JSON →
    文本里第一段花括号配对出来的子串。全部失败就抛异常，交给调用方当失败处理，
    不能让判分逻辑本身的解析失败被误判成任务failed。
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start != -1:
        depth, in_string, escape = 0, False, False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = not in_string
            elif in_string:
                continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"judge返回的内容里解析不出JSON对象：{text[:200]!r}")


async def judge(client: AsyncAnthropic, task: EvalTask, final_text: str) -> tuple[bool, str]:
    missing_facts = [f for f in task.required_facts if f not in final_text]
    if missing_facts:
        return False, f"硬事实校验未通过：回答里没有出现 {missing_facts}"

    response = await client.messages.create(
        model=MODEL,
        # 有些模型（比如deepseek-v4-pro）即便没请求thinking也会自己先做一段内部推理，
        # max_tokens是"思考+正文"的总预算——给太窄会在正文之前就被截断，只剩thinking
        # block没有text block，实测踩过一次坑，这里留足余量
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": (
                    f"评分标准：\n{task.judge_rubric}\n\n"
                    f"待评判的回答：\n{final_text}\n\n"
                    "请判断这个回答是否满足评分标准描述的结论，不要求逐字匹配措辞，只看语义是否达标。\n\n"
                    "只输出一个JSON对象，不要有任何多余文字、不要用markdown代码块包裹，"
                    '格式严格如下：{"passed": true或false, "reasoning": "一到两句话说明判断依据"}'
                ),
            }
        ],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        payload = _extract_json_object(text)
        return bool(payload["passed"]), str(payload.get("reasoning", ""))
    except (ValueError, KeyError) as e:
        # judge本身输出格式不达标，判为FAIL——不同provider对"照格式输出JSON"这个
        # 指令的服从度不一样，这不是任务本身的失败，但也不该悄悄放过，要显式记录
        return False, f"judge输出解析失败：{e}"


async def run_all() -> dict:
    """整个评估流程的编排入口——对应MCPProtocol.md 1.1节里的MCP Host角色。

    跟笔记里的定义对齐："Host：协调、管理一个或多个MCP client的AI应用本身（如Claude
    Code、Cursor）"——这里指的是这一整次脚本运行，从头到尾只有这一个Host，不会因为
    跑了5个task就变成5个Host。下面for循环里反复调用的run_agent_loop()不是另外的
    Host，只是这同一个Host自己内部的编排逻辑，被复用了5次而已——"5"这个数字只发生在
    "同一个Host编排了5次LLM对话"这个层面，跟Host/Client/Server这套协议角色的计数
    无关。
    """
    print(f"使用模型：{MODEL}（根据ANTHROPIC_BASE_URL自动识别）")
    params = StdioServerParameters(command=PYTHON, args=["server.py"], cwd=PROJECT_DIR)  # server.py子进程 = MCP Server，真正对外提供上下文的程序
    client = AsyncAnthropic()  # 不是MCP三角色之一——这是Host用来跟LLM对话的API client

    task_reports = []
    async with stdio_client(params) as (read, write):
        # mcp_session = MCP Client——"活在Host内部的组件，负责维护和某一个MCP server
        # 的连接"。只建一次，5个task共用同一个，不是每个task各自建一个Client
        async with ClientSession(read, write) as mcp_session:
            await mcp_session.initialize()
            mcp_tool_defs = await mcp_tools_to_anthropic_format(mcp_session)

            for task in TASKS:
                print(f"\n===== 跑任务：{task.id}（{task.scenario}） =====")
                final_text, _messages, metrics = await run_agent_loop(client, mcp_session, task, mcp_tool_defs)
                passed, reasoning = await judge(client, task, final_text)
                status = "PASS" if passed else "FAIL"
                print(f"[{status}] {reasoning}")
                print(
                    f"  turns={metrics.turns} tool_calls={metrics.tool_calls} "
                    f"tool_errors={metrics.tool_errors} wall={metrics.wall_seconds:.1f}s "
                    f"tool_time={metrics.tool_call_seconds:.1f}s "
                    f"tokens(in/out/cache_read/cache_write)="
                    f"{metrics.input_tokens}/{metrics.output_tokens}/"
                    f"{metrics.cache_read_tokens}/{metrics.cache_creation_tokens}"
                )
                task_reports.append(
                    {
                        "task_id": task.id,
                        "scenario": task.scenario,
                        "passed": passed,
                        "judge_reasoning": reasoning,
                        "final_text": final_text,
                        "metrics": vars(metrics),
                    }
                )

    accuracy = sum(r["passed"] for r in task_reports) / len(task_reports)
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "accuracy": accuracy,
        "tasks": task_reports,
    }

    print(f"\n===== 汇总：accuracy = {accuracy:.0%}（{sum(r['passed'] for r in task_reports)}/{len(task_reports)}） =====")
    for r in task_reports:
        mark = "✓" if r["passed"] else "✗"
        print(f"  {mark} {r['task_id']}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out_path = os.path.join(RESULTS_DIR, f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果已写入：{out_path}")

    return summary


if __name__ == "__main__":
    asyncio.run(run_all())
