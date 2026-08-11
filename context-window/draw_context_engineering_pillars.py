"""
Context Window 2.3节配图：LangChain官方博客提出的Context Engineering四支柱
（Write / Select / Compress / Isolate），画出每种策略真实的数据流向/计算过程，
不是抽象方框摘要。

四支柱定义核实自LangChain官方博客：https://www.langchain.com/blog/context-engineering-for-agents
（The LangChain Team，2025-07-02发布，原文自称是"review of some popular agent products
and papers"后的归纳，非LangChain原创）。

四个真实例子全部下载源码逐一核实过（均为MIT协议开源仓库），不是道听途说：
- Write:    langmem `create_manage_memory_tool` -> store.put()
- Select:   langgraph-bigtool `retrieve_tools` -> store.search()，只有检索出的工具才会被bind_tools()
- Compress: langmem `summarize_messages` -> SummarizationResult.messages（配合RemoveMessage）
- Isolate:  langgraph-supervisor `create_supervisor`，子agent默认output_mode="last_message"

之前一版图把Write画成了"窗口里占位token被清空/替换"，这是错的——已按真实源码改正：
Write在真实实现里只是一次普通的tool_use/tool_result，正常追加在窗口末尾，从不清空任何东西。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

# 莫兰迪色系
C_WRITE = "#c9a86e"     # 沙棕色
C_SELECT = "#7fa896"    # 灰绿
C_COMPRESS = "#c9705a"  # 陶土红
C_ISOLATE = "#9b8ec4"   # 灰紫
C_WINDOW = "#8a94a6"    # 窗口边框灰
C_TOKEN = "#b9c4c0"     # 普通token块
C_KEEP = "#6b8f7a"      # 保留token
C_TEXT = "#000000"

fig = plt.figure(figsize=(17, 14))
gs = fig.add_gridspec(2, 2, hspace=0.38, wspace=0.28, left=0.045, right=0.985, top=0.90, bottom=0.06)


def token_block(ax, x, y, w, h, color, alpha=0.9, edge="white"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02",
                                  facecolor=color, alpha=alpha, edgecolor=edge, linewidth=1.0))


def panel_frame(ax, title, color, example):
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0.1, 9.0), 9.8, 0.85, boxstyle="round,pad=0.02,rounding_size=0.06",
                                  facecolor=color, alpha=0.95, edgecolor="none"))
    ax.text(5.0, 9.42, title, ha="center", va="center", fontsize=13.5, fontweight="bold", color="white")
    ax.text(5.0, 0.32, example, ha="center", va="center", fontsize=8.6, color=color,
             fontweight="bold", linespacing=1.5, wrap=True)


# ============ 1. Write：普通tool_use/tool_result，正常追加在窗口末尾 ============
ax1 = fig.add_subplot(gs[0, 0])
panel_frame(ax1, "Write：普通tool_use/tool_result，正常追加在末尾", C_WRITE,
            "真实例子（源码验证）：langmem的create_manage_memory_tool\n"
            "函数体只有一行 store.put(namespace, key, value)\n"
            "github.com/langchain-ai/langmem")

# context window：existing history + ①write调用 + ...省略若干轮... + ②search调用
ax1.text(0.3, 8.35, "Context Window（同一个窗口，从左到右就是时间顺序）", fontsize=9.0, fontweight="bold", color=C_TEXT)
ax1.add_patch(FancyBboxPatch((0.3, 7.05), 9.3, 1.05, boxstyle="round,pad=0.02,rounding_size=0.04",
                               facecolor="none", edgecolor=C_WINDOW, linewidth=1.6))
bw, gap = 0.56, 0.66
for i in range(7):
    token_block(ax1, 0.48 + i * gap, 7.25, bw, 0.62, C_TOKEN)
for i in (7, 8):
    token_block(ax1, 0.48 + i * gap, 7.25, bw, 0.62, C_WRITE)
# 分隔线：中间省略若干轮
sep_x = 0.48 + 8.75 * gap
ax1.plot([sep_x, sep_x], [7.05, 8.1], color=C_TEXT, lw=1.0, linestyle=(0, (1, 1.4)), alpha=0.6)
for i in (9, 10):
    token_block(ax1, 0.48 + (i + 0.5) * gap, 7.25, bw, 0.62, C_WRITE, alpha=0.6)

ax1.text(0.48 + 7.5 * gap, 8.18, "①调用\nmanage_memory", ha="center", va="bottom", fontsize=7.4, color=C_WRITE, fontweight="bold", linespacing=1.3)
ax1.text(0.48 + 10 * gap, 8.18, "很多轮后\n②调用\nsearch_memory", ha="center", va="bottom", fontsize=6.9, color=C_WRITE, fontweight="bold", linespacing=1.25)

# 外部Store
ax1.add_patch(mpatches.FancyBboxPatch((3.5, 3.5), 3.0, 1.55, boxstyle="round,pad=0.02,rounding_size=0.06",
                                        facecolor=C_WRITE, alpha=0.18, edgecolor=C_WRITE, linewidth=1.6))
ax1.text(5.0, 4.65, "外部Store", ha="center", va="center", fontsize=10.5, fontweight="bold", color=C_WRITE)
ax1.text(5.0, 3.95, "BaseStore（真实可以是\nPostgres/Redis/内存）", ha="center", va="center", fontsize=8.0, color=C_TEXT)

ax1.annotate("", xy=(4.5, 5.05), xytext=(2.4, 7.05),
             arrowprops=dict(arrowstyle="-|>", color=C_WRITE, lw=2.0, connectionstyle="arc3,rad=-0.15"))
ax1.text(2.55, 6.1, "store.put()\n（side effect）", fontsize=8.0, fontweight="bold", color=C_WRITE, ha="center")

ax1.annotate("", xy=(7.6, 7.05), xytext=(5.5, 5.05),
             arrowprops=dict(arrowstyle="-|>", color=C_WRITE, lw=2.0, linestyle=(0, (4, 2)), connectionstyle="arc3,rad=-0.15"))
ax1.text(7.5, 6.1, "store.search()\n读回", fontsize=8.0, fontweight="bold", color=C_WRITE, ha="center")

ax1.text(0.3, 2.6, "①②两次都只是在窗口末尾追加了一对tool_use/tool_result——\n窗口从没被清空过，只是变长了；外部Store和窗口是否被compress完全独立。",
          fontsize=8.6, color=C_TEXT, linespacing=1.6)


# ============ 2. Select：从全集里挑相关的拉进来 ============
ax2 = fig.add_subplot(gs[0, 1])
panel_frame(ax2, "Select：从全集里挑相关的拉进来", C_SELECT,
            "真实例子（源码验证）：langgraph-bigtool的retrieve_tools\n"
            "store.search()检索后，只有命中的工具才会被llm.bind_tools()绑定\n"
            "github.com/langchain-ai/langgraph-bigtool")

# 全集（散落的图标，颜色浅代表未入选）
import random
random.seed(7)
pool_items = [(random.uniform(0.4, 4.4), random.uniform(3.6, 8.1)) for _ in range(14)]
ax2.text(0.3, 8.35, "可用信息全集（文件/工具/历史规则……）", fontsize=8.6, fontweight="bold", color=C_TEXT)
for (px, py) in pool_items:
    token_block(ax2, px, py, 0.55, 0.4, C_TOKEN, alpha=0.55)
# 被选中的三个，颜色变绿并有箭头流向窗口
selected = [pool_items[2], pool_items[6], pool_items[10]]
for (px, py) in selected:
    token_block(ax2, px, py, 0.55, 0.4, C_SELECT, alpha=0.95)

# 漏斗
ax2.add_patch(plt.Polygon([[4.9, 8.2], [7.3, 8.2], [6.5, 6.3], [5.7, 6.3]],
                            closed=True, facecolor=C_SELECT, alpha=0.22, edgecolor=C_SELECT, linewidth=1.4))
ax2.text(6.1, 8.45, "筛选（语义检索/规则匹配）", ha="center", fontsize=7.6, color=C_SELECT, fontweight="bold")
for (px, py) in selected:
    ax2.annotate("", xy=(6.0, 8.15), xytext=(px + 0.27, py + 0.2),
                 arrowprops=dict(arrowstyle="-", color=C_SELECT, lw=1.1, alpha=0.7))

ax2.annotate("", xy=(6.1, 3.05), xytext=(6.1, 6.2),
             arrowprops=dict(arrowstyle="-|>", color=C_SELECT, lw=2.6))

# context window，只有被选中的3个进来
ax2.text(0.3, 2.9, "Context Window（只进入被选中的3项）", fontsize=9.2, fontweight="bold", color=C_TEXT)
ax2.add_patch(FancyBboxPatch((0.3, 1.55), 9.3, 1.15, boxstyle="round,pad=0.02,rounding_size=0.04",
                               facecolor="none", edgecolor=C_WINDOW, linewidth=1.7))
for i in range(3):
    token_block(ax2, 4.55 + i * 1.05, 1.8, 0.9, 0.65, C_SELECT)

ax2.text(0.3, 1.15, "全集里没被选中的信息，从头到尾都没进过窗口——\n省的不是\"读进来又删掉\"的token，是压根没读进来的token。", fontsize=8.8, color=C_TEXT, linespacing=1.6)


# ============ 3. Compress：窗口内的历史，压缩成摘要 ============
ax3 = fig.add_subplot(gs[1, 0])
panel_frame(ax3, "Compress：窗口内的历史，压缩成摘要", C_COMPRESS,
            "真实例子：langmem的summarize_messages产出\"list of updated messages\n"
            "that are ready to be input to the LLM\"（源码验证，github.com/langchain-ai/langmem）\n"
            "OpenAI compact_threshold=200000 / Google ADK token_threshold两种触发方式（官方文档）")

ax3.text(0.3, 8.35, "压缩前：15条历史事件，逐条占用token", fontsize=8.8, fontweight="bold", color=C_TEXT)
ax3.add_patch(FancyBboxPatch((0.3, 7.1), 9.3, 1.0, boxstyle="round,pad=0.02,rounding_size=0.04",
                               facecolor="none", edgecolor=C_WINDOW, linewidth=1.6))
for i in range(15):
    token_block(ax3, 0.42 + i * 0.62, 7.28, 0.5, 0.62, C_TOKEN)

ax3.annotate("", xy=(5.0, 5.35), xytext=(5.0, 6.95),
             arrowprops=dict(arrowstyle="-|>", color=C_COMPRESS, lw=2.6))
ax3.text(5.35, 6.15, "触发阈值\n（token数或轮次数达标）", fontsize=8.2, color=C_COMPRESS, fontweight="bold")

ax3.text(0.3, 5.05, "压缩后：前12条→1条摘要（占1个block的空间），最近3条原样保留，其余全部腾空", fontsize=8.5, fontweight="bold", color=C_TEXT)
ax3.add_patch(FancyBboxPatch((0.3, 3.8), 9.3, 1.0, boxstyle="round,pad=0.02,rounding_size=0.04",
                               facecolor="none", edgecolor=C_WINDOW, linewidth=1.6))
# 摘要块：叠影效果暗示"这一个block浓缩了原来12个"，但视觉宽度就是1个block，不是12个
token_block(ax3, 0.66, 3.90, 0.55, 0.62, C_COMPRESS, alpha=0.25, edge="none")
token_block(ax3, 0.58, 3.94, 0.55, 0.62, C_COMPRESS, alpha=0.45, edge="none")
token_block(ax3, 0.5, 3.98, 0.55, 0.62, C_COMPRESS)

for i in range(3):
    token_block(ax3, 1.55 + i * 0.62, 3.98, 0.5, 0.62, C_KEEP)

# 空出来的空间：真正被腾出来的部分，用虚线框+浅底色强调
freed_x0 = 3.55
ax3.add_patch(FancyBboxPatch((freed_x0, 3.9), 9.6 - freed_x0, 0.8, boxstyle="round,pad=0.01,rounding_size=0.03",
                               facecolor=C_KEEP, alpha=0.06, edgecolor=C_KEEP, linewidth=1.2, linestyle=(0, (4, 3))))
ax3.text(freed_x0 + (9.6 - freed_x0) / 2, 4.3, "空出来的空间\n留给后续对话继续追加", ha="center", va="center",
          fontsize=8.6, color=C_KEEP, fontweight="bold", linespacing=1.4)

ax3.text(0.3, 2.6, "15个block只剩4个还占着位置，窗口总token数明显下降，\n但\"发生过什么\"这条主线没有丢——这是牺牲细节换空间，不是砍掉历史。", fontsize=8.3, color=C_TEXT, linespacing=1.5)


# ============ 4. Isolate：拆到独立窗口里并行处理 ============
ax4 = fig.add_subplot(gs[1, 1])
panel_frame(ax4, "Isolate：拆到独立窗口里并行处理", C_ISOLATE,
            "真实例子（源码验证）：langgraph-supervisor的create_supervisor\n"
            "子agent在自己独立的agent.invoke()里运行，默认output_mode=\"last_message\"只回传最后一条\n"
            "github.com/langchain-ai/langgraph-supervisor-py")

ax4.add_patch(FancyBboxPatch((3.1, 8.05), 3.8, 0.85, boxstyle="round,pad=0.02,rounding_size=0.05",
                               facecolor=C_ISOLATE, alpha=0.9, edgecolor="none"))
ax4.text(5.0, 8.47, "主线程 Context Window", ha="center", va="center", fontsize=9.3, fontweight="bold", color="white")

sub_x = [0.6, 3.85, 7.1]
sub_labels = ["子agent A\n(读文件1)", "子agent B\n(查文档)", "子agent C\n(跑测试)"]
for sx, lab in zip(sub_x, sub_labels):
    ax4.annotate("", xy=(sx + 1.15, 6.3), xytext=(5.0, 8.05),
                 arrowprops=dict(arrowstyle="-|>", color=C_ISOLATE, lw=1.8,
                                  connectionstyle="arc3,rad=0.0" if sx == 3.85 else ("arc3,rad=-0.25" if sx < 3.85 else "arc3,rad=0.25")))
    ax4.add_patch(FancyBboxPatch((sx, 4.7), 2.3, 1.6, boxstyle="round,pad=0.02,rounding_size=0.05",
                                   facecolor="none", edgecolor=C_ISOLATE, linewidth=1.6))
    ax4.text(sx + 1.15, 6.95, lab, ha="center", va="bottom", fontsize=8.2, fontweight="bold", color=C_ISOLATE, linespacing=1.4)
    for i in range(4):
        token_block(ax4, sx + 0.15 + i * 0.5, 4.85, 0.4, 1.3, C_TOKEN, alpha=0.75)
    ax4.text(sx + 1.15, 4.35, "独立token预算\n（互不可见）", ha="center", fontsize=7.0, color=C_TEXT)

    ax4.annotate("", xy=(5.0 + (sx - 3.85) * 0.15, 3.2), xytext=(sx + 1.15, 4.65),
                 arrowprops=dict(arrowstyle="-|>", color=C_ISOLATE, lw=1.6, linestyle=(0, (4, 2)),
                                  connectionstyle="arc3,rad=0.0"))

ax4.add_patch(FancyBboxPatch((3.6, 2.15), 2.8, 0.85, boxstyle="round,pad=0.02,rounding_size=0.05",
                               facecolor=C_ISOLATE, alpha=0.25, edgecolor=C_ISOLATE, linewidth=1.4))
ax4.text(5.0, 2.57, "只有精简后的结果摘要\n汇总回主线程", ha="center", va="center", fontsize=8.0, fontweight="bold", color=C_ISOLATE)

ax4.text(0.3, 1.1, "每个子agent自己读的文件/试的方案，全部留在各自窗口内消耗掉——\n主线程窗口只承担\"结果\"的token成本，不承担\"过程\"的。", fontsize=8.1, color=C_TEXT, linespacing=1.5)


fig.suptitle("Context Engineering四支柱：Write / Select / Compress / Isolate",
              fontsize=18, fontweight="bold", color=C_TEXT, y=0.965)
fig.text(0.5, 0.015,
          "四支柱分类定义来自LangChain官方博客(langchain.com/blog/context-engineering-for-agents，2025-07-02)；四个真实例子均下载源码逐一核实，非道听途说：\n"
          "Write=langmem/knowledge/tools.py　Select=langgraph-bigtool/graph.py　Compress=langmem/short_term/summarization.py　Isolate=langgraph-supervisor/supervisor.py",
          ha="center", fontsize=8.5, color=C_TEXT, linespacing=1.6)

out_path = "img_context_engineering_four_pillars.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
