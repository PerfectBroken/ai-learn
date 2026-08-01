"""
V向量加权聚合图解：展示"新鲜的""很甜""苹果自身"这三个token的Value向量，
按注意力权重做加权求和后，如何在语义空间里"聚拢"到水果方向（句子B同理聚拢到科技公司方向）。

重要说明：真实的V向量是384维（或更高）的，人没法直接看。这张图把它压缩成一个
2维的"玩具语义空间"（x轴=科技/品牌性，y轴=食物/水果性）方便直观理解"向量加法"这件事，
不是真实模型跑出来的坐标，只是用来演示"加权求和为什么会让结果偏向某个语义方向"这个机制。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False


def draw_panel(ax, title, terms, proto_fruit, proto_tech, sum_color, closer_to):
    """terms: list of (label, weight, vector(x,y), color)"""
    ax.axhline(0, color="#cccccc", lw=1, zorder=1)
    ax.axvline(0, color="#cccccc", lw=1, zorder=1)

    # 参照原型方向（虚线）
    for label, vec, color in [("水果原型", proto_fruit, "#27ae60"), ("科技公司原型", proto_tech, "#2980b9")]:
        ax.annotate(
            "", xy=vec, xytext=(0, 0),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=1.5, linestyle="dashed", alpha=0.55),
        )
        ax.text(vec[0] * 1.06, vec[1] * 1.06, label, color=color, fontsize=9.5, fontweight="bold")

    # 按权重缩放后的向量，首尾相接做向量加法
    origin = (0.0, 0.0)
    cursor = origin
    for label, weight, vec, color in terms:
        scaled = (vec[0] * weight, vec[1] * weight)
        end = (cursor[0] + scaled[0], cursor[1] + scaled[1])
        ax.annotate(
            "", xy=end, xytext=cursor,
            arrowprops=dict(arrowstyle="-|>", color=color, lw=2.4, alpha=0.85),
        )
        mid = ((cursor[0] + end[0]) / 2, (cursor[1] + end[1]) / 2)
        ax.text(
            mid[0] + 0.12, mid[1], f"{weight:.2f}×V({label})",
            fontsize=9, color=color, fontweight="bold",
        )
        cursor = end

    # 最终加权和向量（从原点直接指向终点）
    ax.annotate(
        "", xy=cursor, xytext=origin,
        arrowprops=dict(arrowstyle="-|>", color=sum_color, lw=3.2),
    )
    ax.scatter(*cursor, color=sum_color, s=60, zorder=5)
    ax.text(
        cursor[0] + 0.15, cursor[1] + 0.15,
        f"苹果最终V向量\n(更接近「{closer_to}」)",
        fontsize=10, color=sum_color, fontweight="bold",
    )

    ax.set_xlim(-0.5, 4.2)
    ax.set_ylim(-0.5, 4.2)
    ax.set_xlabel("← 科技/品牌性 →", fontsize=10)
    ax.set_ylabel("← 食物/水果性 →", fontsize=10)
    ax.set_title(title, fontsize=12.5, fontweight="bold")
    ax.set_aspect("equal")


PROTO_FRUIT = (0.3, 3.6)
PROTO_TECH = (3.6, 0.3)

V_XIANXIANDE = (0.4, 3.2)
V_HENTIAN = (0.3, 2.8)
V_PINGGUO_SELF = (2.0, 2.0)  # 苹果自身：训练出的"基础含义"，落在水果与科技中间，代表天生有歧义
V_FABU = (3.4, 0.3)
V_GUJIA = (3.0, 0.2)

fig, axes = plt.subplots(1, 2, figsize=(13, 6.5))

draw_panel(
    axes[0],
    "句子A：新鲜的 + 很甜 + 苹果自身 的V，加权求和 → 偏水果",
    [
        ("新鲜的", 0.45, V_XIANXIANDE, "#16a085"),
        ("很甜", 0.20, V_HENTIAN, "#27ae60"),
        ("苹果", 0.35, V_PINGGUO_SELF, "#7f8c8d"),
    ],
    PROTO_FRUIT, PROTO_TECH,
    sum_color="#1e8449",
    closer_to="水果",
)

draw_panel(
    axes[1],
    "句子B：发布了 + 股价 + 苹果自身 的V，加权求和 → 偏科技公司",
    [
        ("发布了", 0.35, V_FABU, "#2471a3"),
        ("股价", 0.30, V_GUJIA, "#2980b9"),
        ("苹果", 0.35, V_PINGGUO_SELF, "#7f8c8d"),
    ],
    PROTO_FRUIT, PROTO_TECH,
    sum_color="#1a5276",
    closer_to="科技公司",
)

fig.suptitle("V向量的加权求和：语义是怎么被“加”出来的", fontsize=15.5, fontweight="bold")
fig.text(
    0.5, 0.015,
    "注：坐标只是把384维的真实V向量简化成2维方便画图演示，不是真实模型数值；箭头首尾相接 = 向量加法，"
    "颜色相近(方向重合)的向量相加会互相增强，这就是“加权求和”能聚合出语义方向的原因。",
    ha="center", fontsize=9, color="#555555", wrap=True,
)
fig.tight_layout(rect=[0, 0.04, 1, 0.93])
out_path = "img_transformer_qkv_value_sum.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
