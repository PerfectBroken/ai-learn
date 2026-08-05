"""
Context Window 1.1.2节配图：YaRN具体怎么把DeepSeek-V4-Pro训练时的65,536位置，
映射/拉伸到宣称的1,048,576（1M）上下文。

数据全部按论文公式(arXiv:2309.00071) + DeepSeek-V4-Pro官方config.json真实参数算出来的，
不是编的示意数字：
  L(原生训练长度)=65536, base(RoPE theta)=10000, D(qk_rope_head_dim)=64,
  alpha(=beta_slow)=1, beta(=beta_fast)=32, factor(s)=16

核心公式（论文3.2节）：
  wavelength(d) = 2*pi * base^(2d/D)          # 第d个频率维度的"转一圈"需要多少个位置
  r(d) = L / wavelength(d)                     # 训练长度内转了多少圈
  gamma(r) = 0 (r<alpha) / 1 (r>beta) / 线性斜坡 (alpha<=r<=beta)
  有效缩放系数(d) = (1-gamma)*(1/s) + gamma    # 这个维度的"转速"打了多少折
"""

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

# ---- 真实参数（DeepSeek-V4-Pro官方config.json + YaRN论文公式） ----
L = 65536
BASE = 10000
D = 64
ALPHA, BETA = 1, 32
S = 16
TARGET = L * S  # 1,048,576

# ---- 莫兰迪色系 ----
C_INTERP = "#8fb0c9"      # 插值区（柔和蓝）
C_TRANS = "#d9c48f"       # 过渡区（柔和米黄）
C_PRESERVE = "#a3b98f"    # 保留区（柔和灰绿）
C_CURVE = "#6b5b73"       # 缩放曲线（柔和紫灰）
C_MARK = "#c07d63"        # 示例维度标记点（柔和陶土）
C_TEXT = "#000000"


def wavelength(d):
    return 2 * math.pi * (BASE ** (2 * d / D))


def r_of(d):
    return L / wavelength(d)


def gamma(r):
    if r < ALPHA:
        return 0.0
    if r > BETA:
        return 1.0
    return (r - ALPHA) / (BETA - ALPHA)


def eff_scale(d):
    r = r_of(d)
    g = gamma(r)
    return (1 - g) / S + g, r, g


examples = [0, 25, 31]  # 真实挑出来的3个代表维度

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11.5, 12.5),
                                gridspec_kw={"height_ratios": [1.15, 1], "hspace": 0.42})

# ================= 上图：gamma斜坡函数 / 有效缩放系数曲线 =================
r_vals = [10 ** (x / 20) for x in range(-20, 90)]  # 0.1 ~ ~3000, 对数分布
scale_vals = []
for r in r_vals:
    g = gamma(r)
    scale_vals.append((1 - g) / S + g)

ax1.set_xscale("log")
ax1.axvspan(0.08, ALPHA, color=C_INTERP, alpha=0.35, lw=0)
ax1.axvspan(ALPHA, BETA, color=C_TRANS, alpha=0.35, lw=0)
ax1.axvspan(BETA, 15000, color=C_PRESERVE, alpha=0.35, lw=0)

ax1.plot(r_vals, scale_vals, color=C_CURVE, lw=3)
ax1.axvline(ALPHA, color=C_TEXT, lw=1.2, linestyle="--")
ax1.axvline(BETA, color=C_TEXT, lw=1.2, linestyle="--")

ax1.text(0.3, 1.06, f"插值区 r<{ALPHA}\n(完全压缩1/{S})", ha="center", fontsize=9.5,
          fontweight="bold", color=C_TEXT)
ax1.text(5.6, 1.06, f"过渡区 {ALPHA}≤r≤{BETA}\n(线性混合)", ha="center", fontsize=9.5,
          fontweight="bold", color=C_TEXT)
ax1.text(500, 1.06, f"保留区 r>{BETA}\n(完全不压缩)", ha="center", fontsize=9.5,
          fontweight="bold", color=C_TEXT)

for d in examples:
    scale, r, g = eff_scale(d)
    ax1.scatter([r], [scale], color=C_MARK, s=90, zorder=5, edgecolor="white", linewidth=1.2)
    ax1.annotate(
        f"d={d}\nr(d)={r:.2f}\n缩放={scale:.3f}",
        xy=(r, scale), xytext=(r, scale + 0.16),
        ha="center", fontsize=8.6, fontweight="bold", color=C_TEXT,
    )

ax1.set_xlim(0.08, 15000)
ax1.set_ylim(-0.02, 1.18)
ax1.set_xlabel("r(d) = L / wavelength(d)  ——  这个维度在训练长度L内转了多少圈（对数刻度）",
               fontsize=10, fontweight="bold", color=C_TEXT)
ax1.set_ylabel("有效缩放系数\n(该维度转速打的折扣)", fontsize=10, fontweight="bold", color=C_TEXT)
ax1.set_title(
    f"DeepSeek-V4-Pro真实YaRN参数：α(beta_slow)={ALPHA}, β(beta_fast)={BETA}, factor={S}",
    fontsize=13, fontweight="bold", color=C_TEXT, loc="left",
)
for label in ax1.get_xticklabels() + ax1.get_yticklabels():
    label.set_color(C_TEXT)
    label.set_fontweight("bold")

# ================= 下图：3个真实维度，1M位置被"拉回"到哪里 =================
ax2.set_xlim(0, TARGET * 1.08)
ax2.set_ylim(-0.8, len(examples) - 0.2)
bar_h = 0.42

for i, d in enumerate(examples):
    scale, r, g = eff_scale(d)
    equiv_pos = TARGET * scale  # 这个维度在1,048,576位置时，"看起来"像走到了原来的第几个位置
    y = len(examples) - 1 - i

    # 背景条：训练时见过的范围 [0, L]
    ax2.add_patch(mpatches.FancyBboxPatch(
        (0, y - bar_h / 2), L, bar_h, boxstyle="round,pad=0,rounding_size=0.02",
        facecolor=C_PRESERVE, alpha=0.28, edgecolor="none",
    ))
    # 完整条：从0到1,048,576的真实位置轴
    ax2.add_patch(mpatches.FancyBboxPatch(
        (0, y - bar_h / 2), TARGET, bar_h, boxstyle="round,pad=0,rounding_size=0.02",
        facecolor="none", edgecolor=C_TEXT, linewidth=1.3,
    ))
    # 训练边界竖线 L
    ax2.axvline(L, color=C_PRESERVE, lw=2.2, ymin=(y - bar_h / 2 - (-0.8)) / (len(examples) - 0.2 - (-0.8)),
                ymax=(y + bar_h / 2 - (-0.8)) / (len(examples) - 0.2 - (-0.8)))
    # 真实目标位置 1,048,576 的标记（外推终点）
    ax2.scatter([TARGET], [y], marker="v", color=C_TEXT, s=70, zorder=6)
    # 该维度"等效走到"的位置
    ax2.scatter([equiv_pos], [y], marker="o", color=C_MARK, s=140, zorder=6,
                edgecolor="white", linewidth=1.3)
    ax2.plot([equiv_pos, equiv_pos], [y - bar_h / 2 - 0.05, y + bar_h / 2 + 0.05],
             color=C_MARK, lw=2, linestyle=":")

    ax2.text(-TARGET * 0.012, y, f"d={d}\nr(d)={r:.2f}", ha="right", va="center",
              fontsize=9.5, fontweight="bold", color=C_TEXT)
    ax2.text(
        equiv_pos, y - bar_h / 2 - 0.22,
        f"等效位置≈{equiv_pos:,.0f}\n(压缩了{1/scale:.2f}倍)",
        ha="center", va="top", fontsize=8.4, fontweight="bold", color=C_MARK,
    )

top_label_y = len(examples) - 1 + bar_h / 2 + 0.16
ax2.text(L, top_label_y, f"训练边界 L={L:,}", ha="center", va="bottom",
          fontsize=9, fontweight="bold", color=C_TEXT)
ax2.text(TARGET, top_label_y, f"外推终点 {TARGET:,}\n(▽ 真实新位置)", ha="right", va="bottom",
          fontsize=9, fontweight="bold", color=C_TEXT)
ax2.set_yticks([])
ax2.set_xlabel("位置（真实token序号）", fontsize=10, fontweight="bold", color=C_TEXT)
ax2.set_title("同一个「位置1,048,576」，YaRN让不同频率维度感受到的「等效位置」完全不同",
               fontsize=13, fontweight="bold", color=C_TEXT, loc="left")
for label in ax2.get_xticklabels():
    label.set_color(C_TEXT)
    label.set_fontweight("bold")

fig.suptitle("YaRN如何把DeepSeek-V4-Pro训练时的65,536位置，拉伸映射到1,048,576（1M）",
              fontsize=16, fontweight="bold", color=C_TEXT)
fig.text(
    0.5, 0.012,
    "d=0这类高频维度训练时已转了上万圈，不压缩也不会遇到陌生角度；d=31这类最慢的维度，"
    "被压缩了13倍多，等效位置已经很接近训练边界65,536——但即便是DeepSeek这个RoPE子空间里最慢的维度，\n"
    "也没有完全落入「纯插值区」（r(d)最小只到1.39，还差一点才到α=1），这是从真实config反推出来的，不是凑出来的整数。",
    ha="center", fontsize=9.2, color=C_TEXT, fontweight="bold",
)
fig.tight_layout(rect=[0.01, 0.05, 1, 0.94])
out_path = "img_yarn_scaling.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
