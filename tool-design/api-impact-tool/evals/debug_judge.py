"""单独调试一次judge()调用失败的原因——不重跑整个Agent loop，直接拿已经保存在
results/里的final_text，重放judge()那一步，把原始response打印出来看个究竟：
stop_reason是什么、content里有哪些类型的block、usage是多少。

用法：
    python3 debug_judge.py <结果JSON文件路径> <task_id>
例如：
    python3 debug_judge.py results/20260817-193548.json nonexistent_symbol
"""
import asyncio
import json
import sys

from anthropic import AsyncAnthropic

from tasks import TASKS


async def main(result_path: str, task_id: str) -> None:
    data = json.load(open(result_path, encoding="utf-8"))
    task_record = next(t for t in data["tasks"] if t["task_id"] == task_id)
    task = next(t for t in TASKS if t.id == task_id)
    final_text = task_record["final_text"]

    client = AsyncAnthropic()
    response = await client.messages.create(
        model=data["model"],
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

    print("stop_reason:", response.stop_reason)
    print("content block类型:", [b.type for b in response.content])
    print("usage:", response.usage.model_dump(exclude_none=True))
    print("\n完整content:")
    for b in response.content:
        print(f"--- {b.type} ---")
        print(b.model_dump(exclude_none=True))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
