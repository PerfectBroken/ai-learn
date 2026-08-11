"""
Context Window 2.3.1节配图：Write触发架构的权衡——"agent决定"（即时但不可靠）
vs "独立模型调用决定"（可靠但有延迟），以及OpenViking式的双通道混合。

画的是真实的对话轮次时间线和写入动作发生的具体时刻，不是抽象方框。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

C_AGENT = "#7fa896"     # agent决定：灰绿
C_MODEL = "#c9705a"     # 独立模型调用决定：陶土红
C_HYBRID = "#9b8ec4"    # OpenViking混合：灰紫
C_MISS = "#c9a86e"      # 被错过/延迟的沙棕色
C_TURN = "#b9c4c0"      # 普通轮次
C_TEXT = "#000000"
C_STORE = "#6b8f7a"     # 长期记忆store

fig = plt.figure(figsize=(15, 16))
gs = fig.add_gridspec(3, 1, hspace=0.5, left=0.05, right=0.97, top=0.94, bottom=0.04)

N_TURNS = 6
TURN_X0 = 0.6
TURN_GAP = 1.05
TURN_W = 0.75
TURN_Y = 7.2
TURN_H = 0.75

FLOW_X_STORE = 1.5     # 长期记忆store方块中心x
FLOW_X_TRIGGER = 5.3   # 触发框中心x
GAUGE_X = 8.0          # 仪表条起始x（独立一栏，不与流程图重叠）


def turn_x(i):
    return TURN_X0 + i * TURN_GAP


def draw_timeline(ax, highlight, base_color=C_TURN):
    ax.add_patch(FancyBboxPatch((0.35, TURN_Y - 0.15), turn_x(N_TURNS - 1) + TURN_W - 0.15,
                                  TURN_H + 0.3, boxstyle="round,pad=0.02,rounding_size=0.03",
                                  facecolor="none", edgecolor="#8a94a6", linewidth=1.3))
    for i in range(N_TURNS):
        c = highlight.get(i, base_color)
        ax.add_patch(FancyBboxPatch((turn_x(i), TURN_Y), TURN_W, TURN_H,
                                      boxstyle="round,pad=0.008,rounding_size=0.02",
                                      facecolor=c, alpha=0.92, edgecolor="white", linewidth=1.0))


def panel_header(ax, title, color):
    ax.set_xlim(0, 10.4)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.1, 8.95), 10.2, 0.85, boxstyle="round,pad=0.02,rounding_size=0.05",
                                  facecolor=color, alpha=0.95, edgecolor="none"))
    ax.text(5.2, 9.37, title, ha="center", va="center", fontsize=12.5, fontweight="bold", color="white")


def gauge(ax, y, label, value, color, max_w=2.0):
    ax.text(GAUGE_X, y + 0.4, label, fontsize=8.3, color=C_TEXT, fontweight="bold")
    ax.add_patch(FancyBboxPatch((GAUGE_X, y), max_w, 0.28, boxstyle="round,pad=0.005,rounding_size=0.01",
                                  facecolor="#e4e4e0", edgecolor="none"))
    ax.add_patch(FancyBboxPatch((GAUGE_X, y), max_w * value, 0.28, boxstyle="round,pad=0.005,rounding_size=0.01",
                                  facecolor=color, edgecolor="none"))


def store_box(ax, cx, cy, text, color, w=2.3, h=0.85, fontsize=7.8):
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.04",
                                  facecolor=color, alpha=0.9, edgecolor="none"))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="white",
             fontweight="bold", linespacing=1.3)


# ============ Panel 1: agent决定 ============
ax1 = fig.add_subplot(gs[0, 0])
panel_header(ax1, "agent决定：即时响应，但可靠性没保障", C_AGENT)

draw_timeline(ax1, {1: C_AGENT, 4: C_MISS})
ax1.text(turn_x(1) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户：\"记住我喜欢\n用Python\"",
          ha="center", fontsize=7.3, color=C_AGENT, fontweight="bold", linespacing=1.25)
ax1.text(turn_x(4) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户随口提到一个\n隐含的重要偏好",
          ha="center", fontsize=7.0, color=C_MISS, fontweight="bold", linespacing=1.25)

ax1.annotate("", xy=(turn_x(1) + TURN_W / 2, TURN_Y - 1.55), xytext=(turn_x(1) + TURN_W / 2, TURN_Y - 0.1),
             arrowprops=dict(arrowstyle="-|>", color=C_AGENT, lw=2.4))
store_box(ax1, turn_x(1) + TURN_W / 2, TURN_Y - 2.15, "①立刻写入\n长期记忆", C_STORE, w=2.0, h=0.95)

ax1.annotate("", xy=(turn_x(4) + TURN_W / 2, TURN_Y - 1.1), xytext=(turn_x(4) + TURN_W / 2, TURN_Y - 0.1),
             arrowprops=dict(arrowstyle="-|>", color=C_MISS, lw=2.0, linestyle=(0, (3, 2))))
xm, ym = turn_x(4) + TURN_W / 2, TURN_Y - 1.55
ax1.plot([xm - 0.28, xm + 0.28], [ym - 0.28, ym + 0.28], color=C_MISS, lw=2.8)
ax1.plot([xm - 0.28, xm + 0.28], [ym + 0.28, ym - 0.28], color=C_MISS, lw=2.8)
ax1.text(xm, ym - 0.65, "②agent没调用工具\n这条永久错过", ha="center", va="top",
          fontsize=7.4, color=C_MISS, fontweight="bold", linespacing=1.3)

gauge(ax1, 4.8, "即时性", 0.95, C_AGENT)
gauge(ax1, 3.9, "可靠性", 0.35, C_AGENT)


# ============ Panel 2: 独立模型调用决定 ============
ax2 = fig.add_subplot(gs[1, 0])
panel_header(ax2, "独立模型调用决定：判断更可靠，但有延迟", C_MODEL)

draw_timeline(ax2, {1: C_MODEL, 4: C_MODEL})
ax2.text(turn_x(1) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户：\"记住我喜欢\n用Python\"",
          ha="center", fontsize=7.3, color=C_MODEL, fontweight="bold", linespacing=1.25)
ax2.text(turn_x(4) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户随口提到一个\n隐含的重要偏好",
          ha="center", fontsize=7.0, color=C_MODEL, fontweight="bold", linespacing=1.25)

collector_y = TURN_Y - 0.75
ax2.plot([turn_x(1) + TURN_W / 2, turn_x(1) + TURN_W / 2], [TURN_Y - 0.1, collector_y],
          color=C_MODEL, lw=1.6, linestyle=(0, (2, 2)))
ax2.plot([turn_x(4) + TURN_W / 2, turn_x(4) + TURN_W / 2], [TURN_Y - 0.1, collector_y],
          color=C_MODEL, lw=1.6, linestyle=(0, (2, 2)))
ax2.plot([turn_x(1) + TURN_W / 2, FLOW_X_TRIGGER], [collector_y, collector_y],
          color=C_MODEL, lw=1.6, linestyle=(0, (2, 2)))
ax2.text((turn_x(1) + turn_x(4)) / 2, collector_y + 0.28, "两条都先攒着，不立刻处理",
          ha="center", fontsize=7.6, color=C_MODEL, fontweight="bold")

ax2.annotate("", xy=(FLOW_X_TRIGGER, collector_y - 0.9), xytext=(FLOW_X_TRIGGER, collector_y),
             arrowprops=dict(arrowstyle="-|>", color=C_MODEL, lw=2.2))
store_box(ax2, FLOW_X_TRIGGER, collector_y - 1.55, "定时任务/session end\n触发独立模型调用", C_MODEL, w=3.1, h=0.95, fontsize=7.6)

ax2.annotate("", xy=(FLOW_X_STORE + 1.1, collector_y - 1.55), xytext=(FLOW_X_TRIGGER - 1.55, collector_y - 1.55),
             arrowprops=dict(arrowstyle="-|>", color=C_STORE, lw=2.2))
store_box(ax2, FLOW_X_STORE, collector_y - 1.55, "两条都没漏\n一起写入", C_STORE, w=2.1, h=0.95, fontsize=7.6)

gauge(ax2, 4.8, "即时性", 0.25, C_MODEL)
gauge(ax2, 3.9, "可靠性", 0.9, C_MODEL)


# ============ Panel 3: OpenViking混合 ============
ax3 = fig.add_subplot(gs[2, 0])
panel_header(ax3, "OpenViking式混合：两条路径都要，互为兜底", C_HYBRID)

draw_timeline(ax3, {1: C_HYBRID, 4: C_MISS})
ax3.text(turn_x(1) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户：\"记住我喜欢\n用Python\"",
          ha="center", fontsize=7.3, color=C_HYBRID, fontweight="bold", linespacing=1.25)
ax3.text(turn_x(4) + TURN_W / 2, TURN_Y + TURN_H + 0.35, "用户随口提到一个\n隐含的重要偏好",
          ha="center", fontsize=7.0, color=C_MISS, fontweight="bold", linespacing=1.25)

# 路径①：立刻写
ax3.annotate("", xy=(turn_x(1) + TURN_W / 2, TURN_Y - 1.55), xytext=(turn_x(1) + TURN_W / 2, TURN_Y - 0.1),
             arrowprops=dict(arrowstyle="-|>", color=C_HYBRID, lw=2.2))
ax3.text(turn_x(1) + TURN_W / 2 + 0.5, TURN_Y - 1.3, "①立刻写", ha="left", fontsize=7.2,
          color=C_HYBRID, fontweight="bold")

# 路径②：两条都汇入兜底通道
collector_y3 = TURN_Y - 0.75
ax3.plot([turn_x(1) + TURN_W / 2, turn_x(1) + TURN_W / 2], [TURN_Y - 0.1, collector_y3],
          color=C_MISS, lw=1.6, linestyle=(0, (2, 2)))
ax3.plot([turn_x(4) + TURN_W / 2, turn_x(4) + TURN_W / 2], [TURN_Y - 0.1, collector_y3],
          color=C_MISS, lw=1.6, linestyle=(0, (2, 2)))
ax3.plot([turn_x(1) + TURN_W / 2, FLOW_X_TRIGGER], [collector_y3, collector_y3],
          color=C_MISS, lw=1.6, linestyle=(0, (2, 2)))
ax3.text((turn_x(1) + turn_x(4)) / 2, collector_y3 + 0.28, "②两条都同时汇入兜底通道",
          ha="center", fontsize=7.6, color=C_MISS, fontweight="bold")

ax3.annotate("", xy=(FLOW_X_TRIGGER, collector_y3 - 0.9), xytext=(FLOW_X_TRIGGER, collector_y3),
             arrowprops=dict(arrowstyle="-|>", color=C_MISS, lw=2.2))
store_box(ax3, FLOW_X_TRIGGER, collector_y3 - 1.55, "session end\n独立模型调用兜底", C_MISS, w=2.6, h=0.95, fontsize=7.6)

# 两条路径最终都汇入同一个长期记忆
ax3.annotate("", xy=(FLOW_X_STORE + 1.1, collector_y3 - 1.3), xytext=(turn_x(1) + TURN_W / 2, TURN_Y - 1.6),
             arrowprops=dict(arrowstyle="-|>", color=C_HYBRID, lw=1.8, connectionstyle="arc3,rad=0.3"))
ax3.annotate("", xy=(FLOW_X_STORE + 1.1, collector_y3 - 1.8), xytext=(FLOW_X_TRIGGER - 1.3, collector_y3 - 1.55),
             arrowprops=dict(arrowstyle="-|>", color=C_MISS, lw=1.8))
store_box(ax3, FLOW_X_STORE, collector_y3 - 1.55, "长期记忆：\n即时的+兜底的都进来了", C_STORE, w=2.3, h=1.05, fontsize=7.4)

gauge(ax3, 4.8, "即时性", 0.95, C_HYBRID)
gauge(ax3, 3.9, "可靠性", 0.9, C_HYBRID)


fig.suptitle("Write触发架构的权衡：不是谁更先进，是即时性 vs 可靠性",
              fontsize=17, fontweight="bold", color=C_TEXT, y=0.98)

out_path = "img_write_trigger_tradeoff.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
