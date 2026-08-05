"""
Context Window 1.1.1节配图：为什么RoPE能把"位置"理解成"角度"。

核心不是隐喻，是真实的计算步骤：
1. 把Q/K向量切成一对对二维子向量(x1,x2)
2. 每一对乘一个固定频率theta，用 position*theta 当旋转角度，把这对子向量在二维平面里转一下
3. 旋转之后，Q和K的点积在数学上只取决于两者的相对距离(n-m)，跟各自绝对位置无关
   （这是真实的旋转矩阵性质：R(m*theta)^T R(n*theta) = R((n-m)*theta)）
"""

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

C_Q = "#c07d63"       # query 陶土色
C_K = "#6b8fa3"       # key 灰蓝
C_ANGLE = "#8a7ca8"   # 夹角 柔和紫
C_TEXT = "#000000"
THETA = 0.5


def R(angle):
    return np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])


fig, axes = plt.subplots(1, 3, figsize=(15, 5.6))

# ---------------- 左：单个维度对，位置怎么变成角度 ----------------
ax = axes[0]
ax.set_title("① 一对维度(x1,x2)\n乘以频率θ，位置变成旋转角度",
              fontsize=11.5, fontweight="bold", color=C_TEXT)
circle = plt.Circle((0, 0), 1, fill=False, color="#999999", lw=1)
ax.add_patch(circle)
base_vec = np.array([1.0, 0.0])
for pos in [0, 1, 2, 3, 4]:
    angle = pos * THETA
    v = R(angle) @ base_vec
    ax.annotate("", xy=v, xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=C_Q, lw=2.2, alpha=0.35 + 0.13 * pos))
    ax.text(v[0] * 1.18, v[1] * 1.18, f"pos={pos}\nθ·{pos}={angle:.1f}rad",
            fontsize=7.6, ha="center", color=C_TEXT, fontweight="bold")
ax.set_xlim(-1.6, 1.9)
ax.set_ylim(-1.4, 1.6)
ax.set_aspect("equal")
ax.axis("off")

# ---------------- 中：Q、K各自旋转后，夹角只看相对距离 ----------------
# 注意：Q、K的"原始朝向"用同一个基准向量(1,0)，这样两者夹角在旋转后就精确等于(n-m)θ，
# 不会被"Q、K本来就不指向同一方向"这个额外偏移干扰，方便干净地验证"只看相对距离"这件事。
ax = axes[1]
ax.set_title("② Q在位置m、K在位置n各自旋转后\n夹角只取决于(n-m)θ",
              fontsize=11.5, fontweight="bold", color=C_TEXT)
m, n = 3, 7
base = np.array([1.0, 0.0])  # Q、K共用同一个原始朝向，排除额外的固定偏移角
angle_q = m * THETA
angle_k = n * THETA
qv = R(angle_q) @ base
kv = R(angle_k) @ base
ax.annotate("", xy=qv, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_Q, lw=2.8))
ax.annotate("", xy=kv, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_K, lw=2.8))
ax.text(qv[0] * 1.2, qv[1] * 1.2 + 0.12, f"Q转到位置m={m}\n角度=mθ={angle_q:.1f}",
        color=C_Q, fontsize=8.6, fontweight="bold", ha="center")
ax.text(kv[0] * 1.25, kv[1] * 1.25, f"K转到位置n={n}\n角度=nθ={angle_k:.1f}",
        color=C_K, fontsize=8.6, fontweight="bold", ha="center")
# 圆弧严格按signed差值(angle_k-angle_q)扫，不用atan2差值（避免跨±π时扫错方向）
arc_theta = np.linspace(angle_q, angle_k, 40)
ax.plot(0.45 * np.cos(arc_theta), 0.45 * np.sin(arc_theta), color=C_ANGLE, lw=2.4)
dot1 = float(qv @ kv)
ax.text(0.02, 0.68, f"夹角=(n-m)θ\n=({n}-{m})×{THETA}={(n-m)*THETA:.1f}rad\nQ·K点积={dot1:.4f}",
        color=C_ANGLE, fontsize=8.6, fontweight="bold", ha="center")
ax.set_xlim(-1.4, 1.6)
ax.set_ylim(-1.5, 1.5)
ax.set_aspect("equal")
ax.axis("off")

# ---------------- 右：换一组绝对位置，相对距离不变，夹角完全一样 ----------------
ax = axes[2]
ax.set_title("③ 换成m=103,n=107(相对距离还是4)\n夹角数值完全一样——只认相对位置",
              fontsize=11.5, fontweight="bold", color=C_TEXT)
m2, n2 = 103, 107
angle_q2 = (m2 * THETA) % (2 * np.pi)
angle_k2 = angle_q2 + (n2 - m2) * THETA  # 保证圆弧扫的角度和左图严格一致，只是起始朝向不同
qv2 = R(angle_q2) @ base
kv2 = R(angle_k2) @ base
ax.annotate("", xy=qv2, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_Q, lw=2.8))
ax.annotate("", xy=kv2, xytext=(0, 0), arrowprops=dict(arrowstyle="-|>", color=C_K, lw=2.8))
ax.text(qv2[0] * 1.25, qv2[1] * 1.25, f"Q转到位置m={m2}\n角度=mθ(mod 2π)",
        color=C_Q, fontsize=8.6, fontweight="bold", ha="center")
ax.text(kv2[0] * 1.25, kv2[1] * 1.25 - 0.15, f"K转到位置n={n2}\n角度=nθ(mod 2π)",
        color=C_K, fontsize=8.6, fontweight="bold", ha="center")
arc_theta2 = np.linspace(angle_q2, angle_k2, 40)
ax.plot(0.45 * np.cos(arc_theta2), 0.45 * np.sin(arc_theta2), color=C_ANGLE, lw=2.4)
dot2 = float(qv2 @ kv2)
ax.text(0.02, 0.68, f"夹角同样=(n-m)θ={(n2-m2)*THETA:.1f}rad\nQ·K点积={dot2:.4f}\n(和左图{dot1:.4f}完全相等)",
        color=C_ANGLE, fontsize=8.6, fontweight="bold", ha="center")
ax.set_xlim(-1.4, 1.6)
ax.set_ylim(-1.5, 1.5)
ax.set_aspect("equal")
ax.axis("off")

fig.suptitle("RoPE：为什么“位置”能被当成“角度”来处理", fontsize=16, fontweight="bold", color=C_TEXT)
fig.text(
    0.5, 0.02,
    "RoPE不是把position本身叫做角度，是设计了一个映射：取Q/K向量里的一对维度，用position×θ当旋转角度把它转一下。\n"
    "这么设计的回报是数学上的：两个转过的向量做点积（=attention打分），结果只跟(n-m)θ有关，跟m、n各自绝对多大无关——这正是attention要学的\"相对距离\"。",
    ha="center", fontsize=9.6, color=C_TEXT, fontweight="bold",
)
fig.tight_layout(rect=[0, 0.09, 1, 0.90])
out_path = "img_rope_angle_intuition.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
