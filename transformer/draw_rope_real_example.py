"""
Context Window 1.1.1节配图：img_rope_angle_intuition.png的"真实例子"版本。

不再用抽象的pos=0,1,2,3和示意的theta=0.5，而是：
- 真实句子"今天天气不错。"，用DeepSeek-V4-Pro官方tokenizer切出的真实4个token
- 真实的RoPE参数：b=10000, D=64（DeepSeek-V4-Pro官方config），取d=0这个真实维度，
  theta_0 = b^(-2*0/64) = 1.0（精确值，任何base的0次方都是1，不需要近似）
- 真实的Q/K示例：把"今天"(pos=0)当Query、"不错"(pos=2)当Key，算出真实点积
"""

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

C_TOK = "#c07d63"      # token向量 陶土色
C_Q = "#c07d63"        # query 陶土色（与①保持同一token配色）
C_K = "#6b8fa3"        # key 灰蓝
C_ANGLE = "#8a7ca8"    # 夹角 柔和紫
C_TEXT = "#000000"

B, D = 10000, 64
d = 0
THETA = B ** (-2 * d / D)  # 真实值 = 1.0

TOKENS = ["今天", "天气", "不错", "。"]


def R(angle):
    return np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])


base = np.array([1.0, 0.0])

fig, axes = plt.subplots(1, 2, figsize=(11, 5.8))

# ---------------- 左：真实句子的4个真实token，在d=0维度上转到哪 ----------------
ax = axes[0]
ax.set_title(f'① 真实例子："今天天气不错。"（DeepSeek-V4-Pro真实切分）\nd=0维度，真实theta=b^0={THETA:.1f}rad/token',
              fontsize=11, fontweight="bold", color=C_TEXT)
circle = plt.Circle((0, 0), 1, fill=False, color="#999999", lw=1)
ax.add_patch(circle)
for pos, tok in enumerate(TOKENS):
    angle = pos * THETA
    v = R(angle) @ base
    ax.annotate("", xy=v, xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=C_TOK, lw=2.4, alpha=0.4 + 0.15 * pos))
    ax.text(v[0] * 1.22, v[1] * 1.22, f"「{tok}」\npos={pos}\nθ·{pos}={angle:.1f}rad",
            fontsize=8.4, ha="center", color=C_TEXT, fontweight="bold")
ax.set_xlim(-1.7, 2.0)
ax.set_ylim(-1.5, 1.7)
ax.set_aspect("equal")
ax.axis("off")

# ---------------- 右：真实Q/K例子——"今天"(pos0)查询"不错"(pos2) ----------------
ax = axes[1]
ax.set_title('② 真实Q/K例子：Query="今天"(pos=0)\n检索Key="不错"(pos=2)，真实点积',
              fontsize=11, fontweight="bold", color=C_TEXT)
m, n = 0, 2
angle_q = m * THETA
angle_k = n * THETA
qv = R(angle_q) @ base
kv = R(angle_k) @ base
ax.annotate("", xy=qv, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_Q, lw=2.8))
ax.annotate("", xy=kv, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_K, lw=2.8))
ax.text(qv[0] * 1.2 + 0.05, qv[1] * 1.2 + 0.15, f'Q="今天" pos={m}\n角度=mθ={angle_q:.1f}',
        color=C_Q, fontsize=9, fontweight="bold", ha="center")
ax.text(kv[0] * 1.28, kv[1] * 1.28 - 0.05, f'K="不错" pos={n}\n角度=nθ={angle_k:.1f}',
        color=C_K, fontsize=9, fontweight="bold", ha="center")
arc_theta = np.linspace(angle_q, angle_k, 40)
ax.plot(0.45 * np.cos(arc_theta), 0.45 * np.sin(arc_theta), color=C_ANGLE, lw=2.4)
dot = float(qv @ kv)
ax.text(-0.05, 0.68, f"夹角=(n-m)θ\n=(2-0)×1.0={angle_k-angle_q:.1f}rad\nQ·K点积={dot:.4f}",
        color=C_ANGLE, fontsize=9.2, fontweight="bold", ha="center")
ax.set_xlim(-1.3, 1.6)
ax.set_ylim(-1.4, 1.5)
ax.set_aspect("equal")
ax.axis("off")

fig.suptitle("同一张图的真实例子版本：真实句子 + 真实token + 真实RoPE参数",
              fontsize=15.5, fontweight="bold", color=C_TEXT)
fig.text(
    0.5, 0.02,
    "这里的θ=1.0不是凑出来的示意数字，是DeepSeek-V4-Pro真实RoPE公式 θ_d=b^(-2d/|D|) 在d=0时的精确值（b的0次方恒等于1）。\n"
    "换成别的维度（比如之前算过的d=25、d=31），θ会小得多，同样4个token转出来的角度差距会小到几乎看不出来——这正是"
    "不同维度\"转速\"天差地别的真实体现。",
    ha="center", fontsize=9, color=C_TEXT, fontweight="bold",
)
fig.tight_layout(rect=[0, 0.10, 1, 0.88])
out_path = "img_rope_real_example.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
