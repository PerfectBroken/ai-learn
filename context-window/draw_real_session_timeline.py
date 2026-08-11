"""
Context Window 2.1节配图：一次真实Claude Code会话里，context window的真实装载时间线。

数据来自Claude Code官方文档(code.claude.com/docs/en/context-window)里一个交互式模拟器
自带的真实token数字，不是编的示意数字。原页面是一个可拖动播放的React组件，这里把
背后的真实数据做成静态图，方便离线查阅、对比复现。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

C_AUTO = "#8a94a6"     # auto-loaded（系统自动装载）
C_USER = "#7fa896"     # user（用户输入）
C_CLAUDE = "#c98b6e"   # claude（模型输出/操作）
C_HOOK = "#c9a86e"     # hook（自动触发）
C_SUB = "#9b8ec4"      # subagent（子agent隔离上下文）
C_TEXT = "#000000"

# (标签, token数, 类型, 是否在终端可见: hidden/brief/full)
STARTUP = [
    ("System prompt", 4200, C_AUTO, "hidden"),
    ("Auto memory\n(MEMORY.md)", 680, C_AUTO, "hidden"),
    ("环境信息", 280, C_AUTO, "hidden"),
    ("MCP工具(仅工具名)", 120, C_AUTO, "hidden"),
    ("Skill描述", 450, C_AUTO, "hidden"),
    ("~/.claude/\nCLAUDE.md", 320, C_AUTO, "hidden"),
    ("项目CLAUDE.md", 1800, C_AUTO, "hidden"),
]

WORKING = [
    ("用户prompt", 45, C_USER, "full"),
    ("读auth.ts", 2400, C_CLAUDE, "brief"),
    ("读tokens.ts", 1100, C_CLAUDE, "brief"),
    ("规则:api-\nconventions.md", 380, C_AUTO, "brief"),
    ("读middleware.ts", 1800, C_CLAUDE, "brief"),
    ("读auth.test.ts", 1600, C_CLAUDE, "brief"),
    ("规则:testing.md", 290, C_AUTO, "brief"),
    ("grep搜索", 600, C_CLAUDE, "brief"),
    ("Claude分析", 800, C_CLAUDE, "full"),
    ("改auth.ts", 400, C_CLAUDE, "full"),
    ("Hook:prettier", 120, C_HOOK, "hidden"),
    ("改auth.test.ts", 600, C_CLAUDE, "full"),
    ("Hook:prettier", 100, C_HOOK, "hidden"),
    ("npm test输出", 1200, C_CLAUDE, "brief"),
    ("总结", 400, C_CLAUDE, "full"),
]

SUB_PARENT = [
    ("追问prompt", 40, C_USER, "full"),
    ("派生子agent", 80, C_CLAUDE, "brief"),
]
SUB_ISOLATED = [
    ("system prompt", 900, C_SUB),
    ("CLAUDE.md副本", 1800, C_SUB),
    ("MCP+skills", 970, C_SUB),
    ("主线程任务描述", 120, C_SUB),
    ("读session.ts", 2200, C_SUB),
    ("读timeouts.ts", 800, C_SUB),
    ("读config/*.ts", 3100, C_SUB),
]
SUB_RETURN = [
    ("子agent返回摘要", 420, C_CLAUDE, "brief"),
    ("Claude响应", 1200, C_CLAUDE, "full"),
]

ENDING = [
    ("!git status", 180, C_USER, "full"),
    ("/commit-push skill", 620, C_USER, "brief"),
]


def draw_bar(ax, y, items, x0=0.0, height=0.62, fontsize=6.6):
    x = x0
    for item in items:
        label, tokens, color = item[0], item[1], item[2]
        w = tokens / 100.0
        ax.add_patch(mpatches.FancyBboxPatch(
            (x, y - height / 2), w, height, boxstyle="round,pad=0,rounding_size=0.03",
            facecolor=color, edgecolor="white", linewidth=0.8, alpha=0.95,
        ))
        if w > 3.5:
            ax.text(x + w / 2, y, f"{label}\n{tokens}", ha="center", va="center",
                     fontsize=fontsize, fontweight="bold", color=C_TEXT, linespacing=1.3)
        else:
            ax.text(x + w / 2, y + height / 2 + 0.18, f"{label}({tokens})", ha="center", va="bottom",
                     fontsize=fontsize - 0.6, fontweight="bold", color=C_TEXT, rotation=55)
        x += w
    return x


fig, ax = plt.subplots(figsize=(19, 10))
ax.axis("off")
ax.set_xlim(-2, 130)
ax.set_ylim(-2, 15)

y = 13
ax.text(-2, y + 0.75, "① 开场前（用户还没打字）", fontsize=12, fontweight="bold", color=C_TEXT, ha="left")
end1 = draw_bar(ax, y, STARTUP)
ax.text(end1 + 1, y, f"小计\n{sum(i[1] for i in STARTUP)}", fontsize=9, fontweight="bold", color=C_TEXT, va="center")

y = 10.6
ax.text(-2, y + 0.75, "② 工作过程中（一句45token的prompt，换来一万多token的真实context增长）", fontsize=12, fontweight="bold", color=C_TEXT, ha="left")
end2 = draw_bar(ax, y, WORKING)
ax.text(end2 + 1, y, f"小计\n{sum(i[1] for i in WORKING)}", fontsize=9, fontweight="bold", color=C_TEXT, va="center")

y = 8.0
ax.text(-2, y + 0.75, "③ 追问触发子agent——注意子agent的内容画在下面一行，不计入主线程", fontsize=12, fontweight="bold", color=C_TEXT, ha="left")
end3a = draw_bar(ax, y, SUB_PARENT)

y_sub = 6.3
ax.text(end3a + 2, y + 0.3, "↓ 子agent拥有自己独立的context窗口", fontsize=9, color=C_SUB, fontweight="bold")
end3b = draw_bar(ax, y_sub, SUB_ISOLATED, x0=end3a + 2, fontsize=6.2)
ax.text(end3b + 1, y_sub, f"子agent自己\n用了{sum(i[1] for i in SUB_ISOLATED)}", fontsize=8.5, fontweight="bold", color=C_SUB, va="center")

y = 4.6
ax.text(-2, y + 0.75, "④ 子agent只把摘要带回主线程——6100+token的文件读取，换回420token", fontsize=12, fontweight="bold", color=C_TEXT, ha="left")
end4 = draw_bar(ax, y, SUB_RETURN, x0=end3a)
ax.text(end4 + 1, y, f"小计\n{sum(i[1] for i in SUB_RETURN)}", fontsize=9, fontweight="bold", color=C_TEXT, va="center")

y = 2.2
ax.text(-2, y + 0.75, "⑤ 收尾", fontsize=12, fontweight="bold", color=C_TEXT, ha="left")
end5 = draw_bar(ax, y, ENDING, x0=end4)

main_total = (sum(i[1] for i in STARTUP) + sum(i[1] for i in WORKING) + sum(i[1] for i in SUB_PARENT)
              + sum(i[1] for i in SUB_RETURN) + sum(i[1] for i in ENDING))
ax.text(end5 + 3, y, f"主线程\ncontext\n累计\n≈{main_total}\ntoken", fontsize=10, fontweight="bold", color="#b5654a", va="center", ha="left")

legend_items = [
    mpatches.Patch(color=C_AUTO, label="系统自动装载（auto）"),
    mpatches.Patch(color=C_USER, label="用户输入（user）"),
    mpatches.Patch(color=C_CLAUDE, label="Claude操作/输出（claude）"),
    mpatches.Patch(color=C_HOOK, label="Hook自动触发"),
    mpatches.Patch(color=C_SUB, label="仅在子agent自己的context里（sub）"),
]
fig.legend(handles=legend_items, loc="lower center", ncol=5, fontsize=10, frameon=False, bbox_to_anchor=(0.5, 0.01))

fig.suptitle("一次真实Claude Code会话的Context Window装载时间线（真实token数据）",
              fontsize=16, fontweight="bold", color=C_TEXT)
fig.text(0.5, 0.055,
          "数据来源：code.claude.com/docs/en/context-window 官方交互式模拟器内置的真实数字。方块宽度∝token数（100token=1单位）。",
          ha="center", fontsize=9.5, color=C_TEXT)
fig.tight_layout(rect=[0, 0.08, 1, 0.93])
out_path = "img_real_session_timeline.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
