"""
Context Window 1.3节配图：为什么KV Cache只能"追加到末尾"，不能"插入到中间"。

画的是真实的依赖链条，不是抽象方框：每个token下面标出它的K/V实际依赖哪些前缀token
（因果掩码决定的），用颜色区分"缓存依然有效(绿)"、"新算的token(橙)"、"缓存作废需要重算(红)"。
对比"追加到末尾"和"插入到中间"这两种编辑方式，分别会让哪些token的K/V失效。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

GREEN = "#27ae60"   # 缓存依然有效
ORANGE = "#e67e22"  # 新token，本来就要算
RED = "#c0392b"     # 缓存作废，必须重算
GREY = "#7f8c8d"


def draw_row(ax, y, tokens, box_w=0.8, box_h=0.5, gap=1.15):
    """tokens: list of (label, pos_idx, color, depends_str, note)"""
    for i, (label, pos_idx, color, depends_str, note) in enumerate(tokens):
        x = i * gap
        # token box
        rect = mpatches.FancyBboxPatch(
            (x, y), box_w, box_h,
            boxstyle="round,pad=0.04,rounding_size=0.06",
            linewidth=2, edgecolor=color, facecolor=color, alpha=0.18,
        )
        ax.add_patch(rect)
        ax.text(x + box_w / 2, y + box_h / 2 + 0.06, label,
                 ha="center", va="center", fontsize=13, fontweight="bold", color=color)
        ax.text(x + box_w / 2, y + box_h / 2 - 0.16, f"pos {pos_idx}",
                 ha="center", va="center", fontsize=8, color=GREY)
        # 依赖标注（这个token的K/V实际attends到哪些前缀）
        ax.text(x + box_w / 2, y - 0.22, f"K/V看到:\n[{depends_str}]",
                 ha="center", va="top", fontsize=7.8, color="#444444")
        if note:
            ax.text(x + box_w / 2, y + box_h + 0.14, note,
                     ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=color)
    return len(tokens) * gap - (gap - box_w)


fig, axes = plt.subplots(3, 1, figsize=(11, 10.5))
for ax in axes:
    ax.set_xlim(-0.5, 6.6)
    ax.set_ylim(-0.9, 1.1)
    ax.axis("off")

# ---------- Row 1: 原始已缓存序列 ----------
ax = axes[0]
ax.set_title("原始序列（K/V已全部算好并缓存）", fontsize=13, fontweight="bold", loc="left")
tokens0 = [
    ("A", 1, GREEN, "A", ""),
    ("B", 2, GREEN, "A,B", ""),
    ("C", 3, GREEN, "A,B,C", ""),
    ("D", 4, GREEN, "A,B,C,D", ""),
    ("E", 5, GREEN, "A,B,C,D,E", ""),
]
draw_row(ax, 0.15, tokens0)

# ---------- Row 2: 追加到末尾 ----------
ax = axes[1]
ax.set_title("① 追加到末尾：A~E的K/V完全不变，只需新算F", fontsize=13, fontweight="bold", loc="left", color=GREEN)
tokens1 = [
    ("A", 1, GREEN, "A", ""),
    ("B", 2, GREEN, "A,B", ""),
    ("C", 3, GREEN, "A,B,C", ""),
    ("D", 4, GREEN, "A,B,C,D", ""),
    ("E", 5, GREEN, "A,B,C,D,E", ""),
    ("F", 6, ORANGE, "A,B,C,D,E,F", "新算"),
]
draw_row(ax, 0.15, tokens1)
ax.text(6.55, 0.4, "缓存\n100%复用", ha="left", va="center",
        fontsize=10.5, fontweight="bold", color=GREEN)

# ---------- Row 3: 插入到中间 ----------
ax = axes[2]
ax.set_title("② 插入到中间（B、C之间插入X）：C、D、E的位置和前缀全变，缓存作废", fontsize=13, fontweight="bold", loc="left", color=RED)
tokens2 = [
    ("A", 1, GREEN, "A", ""),
    ("B", 2, GREEN, "A,B", ""),
    ("X", 3, ORANGE, "A,B,X", "新算"),
    ("C", 4, RED, "A,B,X,C", "作废重算"),
    ("D", 5, RED, "A,B,X,C,D", "作废重算"),
    ("E", 6, RED, "A,B,X,C,D,E", "作废重算"),
]
draw_row(ax, 0.15, tokens2)
ax.text(6.55, 0.4, "插入点之后\n全部要重算", ha="left", va="center",
        fontsize=10.5, fontweight="bold", color=RED)
# 标注C token"以前"依赖什么，做对比（C是tokens2里第4个，index=3）
ax.annotate(
    "C原来在pos 3，只看到[A,B,C]；\n插入X后C挪到pos 4，看到的变成[A,B,X,C]\n——位置和前缀都变了，K/V数学上不再成立",
    xy=(3 * 1.15 + 0.4, 0.15), xytext=(3.0, -0.75),
    fontsize=9, color=RED,
    arrowprops=dict(arrowstyle="->", color=RED, lw=1.3),
    ha="center",
)

fig.suptitle("Context Window只能追加、不能中间插入的根本原因：因果掩码下K/V的依赖链", fontsize=15.5, fontweight="bold")
fig.text(
    0.5, 0.012,
    "每个token的K/V只取决于「自己 + 前面的token」（因果掩码）。追加不改变任何已有token的前缀和位置，缓存全部有效；\n"
    "插入会改变插入点之后每个token的位置编号和其能看到的前缀内容，这些token的K/V必须重新计算，等于局部重做了一遍prefill。",
    ha="center", fontsize=9.3, color="#555555",
)
fig.tight_layout(rect=[0, 0.035, 1, 0.94])
out_path = "img_context_window_append_vs_insert.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
