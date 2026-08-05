"""
Context Window 1节配图：agent和LLM交互时，context window里实际装的是什么、
怎么随着轮次增长、输入输出如何共用同一个窗口、以及撞到上限时发生什么。

画的是真实的请求payload构成随轮次演变的过程（不是抽象方框）：固定前缀只装一次，
之后每一轮的「用户消息/模型输出/工具结果」都以追加的方式接在后面，直到撞到窗口上限。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

# 配色：柔和一点的莫兰迪色系，冷色系 = input类型，暖色系 = output类型
C_PREFIX = "#7a8ba6"     # 固定前缀（system prompt + CLAUDE.md + 工具定义）——柔和灰蓝
C_USER = "#8fb8d6"       # 用户消息（input）——柔和浅蓝
C_TOOLRES = "#b6a0c9"    # 工具结果（input，来自上一轮工具调用的执行结果）——柔和淡紫
C_OUTPUT = "#e3a58c"     # 模型输出：文本/工具调用请求（output）——柔和陶土色
C_TEXT = "#000000"       # 纯黑文字，配柔和底色更清晰
LIMIT = 34.0             # 图示的"上下文窗口上限"（示意刻度，非真实token数）

segments_by_row = [
    # 每行 = 这一轮发给模型的完整payload，从左到右按追加顺序排列
    # (宽度, 颜色, 标签)
    [(6, C_PREFIX, "固定前缀\nSystem Prompt\n+CLAUDE.md\n+工具定义"),
     (3, C_USER, "用户消息①")],

    [(6, C_PREFIX, "固定前缀"),
     (3, C_USER, "用户消息①"),
     (2.5, C_OUTPUT, "模型输出①\n(文本+工具调用)"),
     (4, C_TOOLRES, "工具结果①\n(读文件/跑命令)")],

    [(6, C_PREFIX, "固定前缀"),
     (3, C_USER, "用户消息①"),
     (2.5, C_OUTPUT, "模型输出①"),
     (4, C_TOOLRES, "工具结果①"),
     (2, C_OUTPUT, "模型输出②"),
     (2, C_USER, "用户消息②"),
     (2.5, C_OUTPUT, "模型输出③\n(文本+工具调用)"),
     (5, C_TOOLRES, "工具结果②\n(较大：比如读了个大文件)")],

    [(6, C_PREFIX, "固定前缀"),
     (3, C_USER, "用户消息①"),
     (2.5, C_OUTPUT, "模型输出①"),
     (4, C_TOOLRES, "工具结果①"),
     (2, C_OUTPUT, "模型输出②"),
     (2, C_USER, "用户消息②"),
     (2.5, C_OUTPUT, "模型输出③"),
     (5, C_TOOLRES, "工具结果②"),
     (2, C_OUTPUT, "模型输出④"),
     (2.6, None, "撞到上限！\nstop_reason=\nmodel_context_\nwindow_exceeded")],
]

row_titles = [
    "Turn 1 发送给模型的内容",
    "Turn 2 发送给模型的内容（Turn1的输出+工具结果被追加在后面）",
    "Turn 3 发送给模型的内容（继续累积，只增不减）",
    "继续几轮后：撞到Context Window上限",
]

fig, axes = plt.subplots(4, 1, figsize=(13, 9.6))

for row_idx, (ax, segs, title) in enumerate(zip(axes, segments_by_row, row_titles)):
    ax.set_xlim(0, LIMIT + 1.5)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left",
                 color=(C_OUTPUT if row_idx == 3 else "#222222"))

    x = 0.0
    for width, color, label in segs:
        if color is None:
            # 最后一格：超出上限的部分，画成斜线警示框
            rect = mpatches.FancyBboxPatch(
                (x, 0.15), width, 0.7, boxstyle="round,pad=0.02,rounding_size=0.05",
                linewidth=2, edgecolor=C_OUTPUT, facecolor="white", hatch="////",
            )
            ax.add_patch(rect)
            ax.text(x + width / 2, 0.5, label, ha="center", va="center",
                     fontsize=8.5, fontweight="bold", color=C_TEXT)
        else:
            rect = mpatches.FancyBboxPatch(
                (x, 0.15), width, 0.7, boxstyle="round,pad=0.02,rounding_size=0.05",
                linewidth=1.3, edgecolor="white", facecolor=color, alpha=0.95,
            )
            ax.add_patch(rect)
            n_lines = label.count("\n") + 1
            fontsize = 7.6 if (width < 3 or n_lines >= 3) else 8.6
            ax.text(x + width / 2, 0.5, label, ha="center", va="center",
                     fontsize=fontsize, color=C_TEXT, fontweight="bold", wrap=True, linespacing=1.4)
        x += width

    # 窗口上限竖线
    ax.axvline(LIMIT, color="#111111", lw=2, linestyle=(0, (5, 3)))
    if row_idx == 0:
        ax.text(LIMIT, 0.98, "Context Window 上限", ha="center", va="bottom",
                 fontsize=9.5, fontweight="bold")

# 图例
legend_items = [
    mpatches.Patch(color=C_PREFIX, label="固定前缀（每轮不变，最容易命中缓存）"),
    mpatches.Patch(color=C_USER, label="用户消息 —— input"),
    mpatches.Patch(color=C_TOOLRES, label="工具调用结果 —— input"),
    mpatches.Patch(color=C_OUTPUT, label="模型输出（文本/工具调用请求）—— output"),
]
fig.legend(handles=legend_items, loc="lower center", ncol=2, fontsize=9.5,
           frameon=False, bbox_to_anchor=(0.5, 0.005))

fig.suptitle("Agent与LLM交互时，Context Window里实际装的是什么", fontsize=16, fontweight="bold")
fig.text(
    0.5, 0.065,
    "input(蓝/紫)和output(红)共用同一个窗口额度，不是两个独立空间；每一轮只能在末尾追加，历史内容原样保留（回顾1.3节）；\n"
    "撞到上限后要么请求直接被拒绝（400错误），要么生成过程中途停止（stop_reason: model_context_window_exceeded）。",
    ha="center", fontsize=9.3, color="#444444",
)
fig.tight_layout(rect=[0, 0.11, 1, 0.93])
out_path = "img_agent_context_window_composition.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
