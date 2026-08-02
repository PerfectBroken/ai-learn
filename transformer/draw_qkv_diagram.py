"""
苹果 QKV / 注意力消歧 图解。

对应 Transformer.md 里 QKV 矩阵一节的讲解示例：
同一个"苹果" Embedding，在不同上下文里，通过 Query-Key 匹配得到不同的注意力权重，
再按权重对 Value 加权求和，最终被"改写"成不同语义方向的输出向量。

注意：图里的权重数字是手工设定的示意值，用来展示"注意力权重不同 -> 输出语义不同"这个机制，
不是真实模型跑出来的数值。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

SENT_A = ["我", "买了", "新鲜的", "苹果", "很甜"]
SENT_B = ["苹果", "发布了", "新手机", "股价", "大涨"]
TARGET_A_IDX = 3
TARGET_B_IDX = 0

# 手工设定的示意权重：苹果对其余token的注意力（跳过苹果自己），总和为1
WEIGHTS_A = [0.05, 0.30, 0.45, 0.20]  # 对应 我 / 买了 / 新鲜的 / 很甜
WEIGHTS_B = [0.35, 0.25, 0.30, 0.10]  # 对应 发布了 / 新手机 / 股价 / 大涨


def draw_panel(ax, tokens, target_idx, weights, title, out_label, out_color):
    n = len(tokens)
    xs = [1 + i * (8 / (n - 1)) for i in range(n)]
    y_top = 8.3
    y_bottom = 1.6

    for i, (x, tok) in enumerate(zip(xs, tokens)):
        is_target = i == target_idx
        box = FancyBboxPatch(
            (x - 0.75, y_top - 0.4),
            1.5,
            0.8,
            boxstyle="round,pad=0.05,rounding_size=0.08",
            linewidth=2.2 if is_target else 1,
            edgecolor="#c0392b" if is_target else "#555555",
            facecolor="#fdecea" if is_target else "#f2f2f2",
            zorder=3,
        )
        ax.add_patch(box)
        ax.text(
            x, y_top, tok, ha="center", va="center", fontsize=12,
            fontweight="bold" if is_target else "normal", zorder=4,
        )

    others = [i for i in range(n) if i != target_idx]
    for w, i in zip(weights, others):
        x_from, x_to = xs[target_idx], xs[i]
        rad = 0.35 if x_to > x_from else -0.35
        ax.annotate(
            "",
            xy=(x_to, y_top - 0.55),
            xytext=(x_from, y_top - 0.55),
            arrowprops=dict(
                arrowstyle="-|>",
                color="#2e86c1",
                lw=1 + w * 9,
                alpha=0.35 + w * 0.6,
                connectionstyle=f"arc3,rad={rad}",
            ),
            zorder=2,
        )
        mid_x = (x_from + x_to) / 2
        ax.text(
            mid_x, y_top - 1.55 - abs(rad) * 0.6, f"{w:.2f}",
            fontsize=9, color="#2e86c1", ha="center", fontweight="bold",
        )

    out_box = FancyBboxPatch(
        (xs[target_idx] - 1.5, y_bottom - 0.55),
        3.0,
        1.1,
        boxstyle="round,pad=0.05,rounding_size=0.1",
        linewidth=2,
        edgecolor=out_color,
        facecolor=out_color,
        alpha=0.15,
        zorder=3,
    )
    ax.add_patch(out_box)
    ax.text(
        xs[target_idx], y_bottom, out_label, ha="center", va="center",
        fontsize=10.5, color=out_color, fontweight="bold", zorder=4,
    )

    ax.annotate(
        "",
        xy=(xs[target_idx], y_bottom + 0.6),
        xytext=(xs[target_idx], y_top - 0.9),
        arrowprops=dict(arrowstyle="-|>", color="#333333", lw=2),
    )
    ax.text(
        xs[target_idx] + 0.25, (y_top + y_bottom) / 2 + 0.3,
        "按权重加权\n求和V", fontsize=9, color="#333333",
    )

    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.set_title(title, fontsize=13, fontweight="bold")


fig, axes = plt.subplots(1, 2, figsize=(15, 7.5))
draw_panel(
    axes[0], SENT_A, TARGET_A_IDX, WEIGHTS_A,
    "句子A：我买了一个新鲜的苹果，很甜",
    "苹果 的输出向量\n(偏向「水果」语义)",
    "#27ae60",
)
draw_panel(
    axes[1], SENT_B, TARGET_B_IDX, WEIGHTS_B,
    "句子B：苹果发布了新手机，股价大涨",
    "苹果 的输出向量\n(偏向「科技公司」语义)",
    "#2980b9",
)

fig.suptitle("同一个「苹果」Embedding，经QKV注意力匹配后被上下文改写", fontsize=16, fontweight="bold")
fig.text(
    0.5, 0.02,
    "红框 = 苹果自己(发出Query)　蓝色弧线 = Q·K匹配后的注意力权重(线越粗/越深代表借用该token的Value越多，数字为示意权重，非真实模型输出)",
    ha="center", fontsize=9.5, color="#555555",
)
fig.tight_layout(rect=[0, 0.05, 1, 0.94])
out_path = "img_transformer_qkv_apple.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
