"""
Context Window 2.3.3节配图：Compress压缩摘要请求，是完全独立于主对话的另一次LLM调用——
不是把主对话的system prompt换掉接着聊，而是单轮、不带tools、system prompt整个替换成
SUMMARIZATION_SYSTEM_PROMPT的一次隔离请求。画出真实的请求体/响应体字段和数据流向，
不是抽象方框。依据：OpenClaw源码 packages/agent-core/src/harness/compaction/compaction.ts

框高按行数自动计算，避免文字溢出框外。
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False

C_NORMAL = "#7fa896"    # 主对话的正常请求：灰绿
C_COMPACT = "#c9705a"   # 隔离的压缩请求：陶土红
C_FLATTEN = "#9b8ec4"   # 序列化/拍扁步骤：灰紫
C_GOLD = "#c9a86e"      # 触发判断：沙棕
C_TEXT = "#000000"

TOP_PAD = 1.15      # 标题栏(0.85) + 与首行间距(0.3)
LINE_STEP = 0.5
BOTTOM_PAD = 0.55    # 末行下方留白，避免贴框底


def required_height(n_lines):
    return TOP_PAD + max(0, n_lines - 1) * LINE_STEP + BOTTOM_PAD


x0, w = 0.4, 9.2

# ============ 逐块定义内容，行数决定框高 ============
stage1_lines = [
    ('tools: [read_file, edit_file, bash, ...]', False),
    ('system: "You are a coding assistant..."', False),
    ('messages: [', False),
    ('  {role:"user", content:"帮我重构utils.ts"},', False),
    ('  {role:"assistant", content:[{type:"tool_use",...}]},', False),
    ('  {role:"toolResult", content:"..."}, ... ← 逐轮追加、只增不减', False),
    (']', False),
]
stage3_lines = [
    ("<conversation>", False),
    ('[User]: 帮我重构utils.ts', False),
    ('[Assistant]: 好的，我先看看现有实现', False),
    ('[Assistant tool calls]: read_file(path="utils.ts")', False),
    ('[Tool result]: (截断到2000字符) export function foo...', False),
    ("</conversation>", False),
    ("<previous-summary>...</previous-summary>  ← 仅增量更新时才有", False),
    ("## Goal / ## Progress / ## Key Decisions / ## Next Steps", True),
    ("...（固定markdown模板，逼模型照这个格式输出） ← 这一整段就是promptText", True),
]
stage4_lines = [
    ("★ 没有tools字段——这次调用模型物理上调不了任何工具", True),
    ('systemPrompt: SUMMARIZATION_SYSTEM_PROMPT', True),
    ('  "You are a context summarization assistant...', False),
    ('   Do NOT continue the conversation. ONLY output', False),
    ('   the structured summary."', False),
    ('messages: [', False),
    ('  {role:"user", content:[{type:"text", text: promptText}]}', True),
    (']  ← promptText就是上一步拍扁出的那整段文本', True),
]
stage5_lines = [
    ("extractSummaryText()：只取response.content里的text block", False),
    ("（因为请求没给tools，模型也不可能返回tool_use）", True),
    ("## Goal", False),
    ("用户希望重构 utils.ts 里的...", False),
    ("## Progress", False),
    ("### Done", False),
    ("- [x] 已读取 utils.ts 现有实现", False),
]
stage6_lines = [
    ('tools: [read_file, edit_file, bash, ...]  ← 跟最上面的主对话请求一样，没变', False),
    ('system: "You are a coding assistant..."   ← 跟最上面的主对话请求一样，没变', False),
    ('messages: [', False),
    ('  {role:"compactionSummary", summary:"## Goal\\n..."},', True),
    ('  ...最近保留的几条原始消息, 新的user输入', False),
    (']', False),
]

h1 = required_height(len(stage1_lines))
h2 = required_height(1)
h3 = required_height(len(stage3_lines))
h4 = required_height(len(stage4_lines))
h5 = required_height(len(stage5_lines))
h6 = required_height(len(stage6_lines))

GAP = 1.85       # 普通stage之间的箭头间距
GAP_TRIGGER = 2.05  # 触发框到压缩请求体之间，箭头旁还要放一行说明文字

# ============ 自顶向下累积计算每块的位置 ============
top_margin = 0.85
y1_top = 44 - top_margin
y1 = y1_top - h1                      # 主对话正常请求：底edge

y2_top = y1 - GAP
y2 = y2_top - h2                      # shouldCompact判断：底edge

y3_top = y2 - GAP_TRIGGER
y3 = y3_top - h3                      # ①压缩请求体：底edge

y4_top = y3 - GAP
y4 = y4_top - h4                      # promptText拍扁内容：底edge

y5_top = y4 - GAP
y5 = y5_top - h5                      # ④返回摘要：底edge

y6_top = y5 - GAP
y6 = y6_top - h6                      # 塞回主对话：底edge

iso_top = y3_top + 0.4
iso_bottom = y6 - 0.35

ylim_bottom = iso_bottom - 0.7
fig_h = 18.6 * (44 - ylim_bottom) / 37.8

fig, ax = plt.subplots(figsize=(15.5, fig_h))
ax.set_xlim(-3.2, 10.6)
ax.set_ylim(ylim_bottom, 44)
ax.axis("off")


def stage(y, h, title, color, lines, fontsize=8.2, title_fs=11, dashed=False):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x0, y), w, h, boxstyle="round,pad=0.03,rounding_size=0.08",
        facecolor=color, alpha=0.14, edgecolor=color, linewidth=2.0 if dashed else 1.8,
        linestyle=(0, (6, 3)) if dashed else "solid",
    ))
    ax.add_patch(mpatches.FancyBboxPatch(
        (x0, y + h - 0.85), w, 0.85, boxstyle="round,pad=0,rounding_size=0.08",
        facecolor=color, alpha=0.95, edgecolor="none",
    ))
    ax.text(x0 + 0.35, y + h - 0.43, title, ha="left", va="center", fontsize=title_fs,
             fontweight="bold", color="white")
    ty = y + h - TOP_PAD
    for line, is_bold in lines:
        w_ = "bold" if is_bold else "normal"
        ax.text(x0 + 0.45, ty, line, ha="left", va="top", fontsize=fontsize, color=C_TEXT, fontweight=w_)
        ty -= LINE_STEP


def down_arrow(y_top, y_bottom, label, color="#555555", x=5, fontsize=9.2):
    ax.annotate("", xy=(x, y_bottom), xytext=(x, y_top),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=2.2))
    ax.text(x + 0.3, (y_top + y_bottom) / 2, label, ha="left", va="center", fontsize=fontsize,
             fontweight="bold", color="#333333")


# ============ ① 主对话：正在进行的正常请求 ============
stage(y1, h1, "主对话：每一轮都长这样的正常请求", C_NORMAL, stage1_lines, fontsize=8.1)
down_arrow(y1 - 0.15, y2_top + 0.15, "对话持续进行，messages数组不断变长")

# ============ ② 触发判断（shouldCompact） ============
stage(y2, h2, "每次发请求前先判断：shouldCompact(contextTokens, contextWindow, settings)",
      C_GOLD, [("contextTokens > contextWindow − reserveTokens(默认16384) ？", True)],
      fontsize=8.6, title_fs=9.6)
down_arrow(y2 - 0.15, y3_top + 0.15, "达到阈值 → 触发一次完全独立的压缩请求\n（下方隔离区）",
           color=C_GOLD, fontsize=9.0)

# 隔离区外框
ax.add_patch(mpatches.FancyBboxPatch(
    (0.1, iso_bottom), 10.0, iso_top - iso_bottom, boxstyle="round,pad=0.05,rounding_size=0.12",
    facecolor="none", edgecolor=C_COMPACT, linewidth=2.6, linestyle=(0, (8, 4)),
))
ax.text(10.05, (iso_top + iso_bottom) / 2, "隔离区：这一整块跟主对话的\ntools/system/messages\n完全不共用，是另开的一次LLM调用",
         ha="left", va="center", fontsize=8.6, fontweight="bold", color=C_COMPACT, linespacing=1.4, rotation=-90)

# ============ ① serializeConversation()，先产出promptText ============
stage(y3, h3, "① serializeConversation()：把要压缩的历史拍扁成promptText", C_FLATTEN, stage3_lines, fontsize=8.0)
down_arrow(y3 - 0.15, y4_top + 0.15, "promptText原样塞进messages字段\n（对象字面量赋值，没有转义/截断等额外处理）",
           color=C_FLATTEN, fontsize=8.4)

# ============ ② 压缩请求体：promptText已就位，组装完成 ============
stage(y4, h4, "② 压缩请求体（组装完成）：context = { systemPrompt, messages }", C_COMPACT, stage4_lines, fontsize=8.0)
down_arrow(y4 - 0.15, y5_top + 0.15,
           "③ 模型推理（同一个模型，但这是隔离的第2次调用，\n跟主对话轮次编号无关）", color=C_COMPACT)

# ============ ④ 压缩请求的响应 ============
stage(y5, h5, "④ 返回：纯文本摘要，没有tool_use/thinking block", C_COMPACT, stage5_lines, fontsize=8.0)
down_arrow(y5 - 0.15, y6_top + 0.15, "⑤ 摘要文本包成一条新的compactionSummary消息", color=C_COMPACT)

# ============ ⑥ 塞回主对话 ============
stage(y6, h6, "塞回主对话的messages数组，替换被裁掉的历史，压缩后照常继续", C_NORMAL, stage6_lines, fontsize=8.0)

# 闭环虚线：从⑥回到①，走左侧空白
loop_x = -2.3
ax.plot([0.4, loop_x], [y6 + h6 * 0.45, y6 + h6 * 0.45], color="#555555", lw=2.0, linestyle=(0, (5, 3)))
ax.plot([loop_x, loop_x], [y6 + h6 * 0.45, y1 + h1 * 0.55], color="#555555", lw=2.0, linestyle=(0, (5, 3)))
ax.annotate("", xy=(0.4, y1 + h1 * 0.55), xytext=(loop_x, y1 + h1 * 0.55),
            arrowprops=dict(arrowstyle="-|>", color="#555555", lw=2.0, linestyle=(0, (5, 3))))
ax.text(loop_x - 0.55, (y6 + y1) / 2 + 2, "压缩完成后\n回到①继续正常对话", ha="center", va="center",
        fontsize=9.2, fontweight="bold", color="#333333", rotation=90, linespacing=1.5)

fig.suptitle("Compress的LLM请求是完全独立的一次调用：单轮、不带tools、system prompt整个换掉",
              fontsize=16, fontweight="bold", color=C_TEXT, y=0.994)
fig.text(0.5, 0.006,
          "关键点：压缩请求不是\"把主对话的system prompt换成摘要指令、接着聊\"，而是重新构造一个全新的context对象——\n"
          "systemPrompt换成SUMMARIZATION_SYSTEM_PROMPT，messages只有1条（历史被拍扁成文本塞进去），tools字段直接不传。\n"
          "两次请求（主对话 vs 压缩）在参数上完全不共用，只是恰好调用同一个模型。依据：OpenClaw compaction.ts",
          ha="center", fontsize=9, color=C_TEXT, fontweight="bold")

fig.tight_layout(rect=[0.03, 0.02, 1, 0.982])
out_path = "img_compaction_isolated_request.png"
fig.savefig(out_path, dpi=150)
print(f"已保存: {out_path}")
