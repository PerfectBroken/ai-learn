"""
Embedding 对比实验：我爱你 / 我喜欢你 / 我恨你 / i love you / i hate you

对应 Transformer.md「二、单次前向流程」第1步 Embedding。

这个脚本刻意做两组对照，用来回答一个很关键的问题：
"Embedding 这一步本身，到底有没有语义？"

- 第一组「未训练 Embedding」：完全模拟 Transformer 里最原始的 Embedding 层——
  就是一张随机初始化的查找表（token id -> 向量），没有经过任何训练。
  这组结果会证明：Embedding 层本身只是个容器，语义是"训练"出来的，不是"查表"查出来的。

- 第二组「预训练句子向量」：用一个已经训练好的多语言模型，把整句话过完
  Embedding + 多层注意力 + FFN 之后的最终隐藏状态做 mean pooling，
  得到真正带语义的句子向量。这才是"模型已经学会意思"之后的效果。

对比这两组，就能直观看到 Embedding 和"整个 Transformer 网络"分别贡献了什么。
"""

import numpy as np

SENTENCES = ["我爱你", "我喜欢你", "我恨你", "i love you", "i hate you"]
PRETRAINED_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # 与预训练模型的输出维度对齐，排除"维度更高所以更准"这个干扰变量


def cosine_sim_matrix(vectors: np.ndarray) -> np.ndarray:
    norm = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return norm @ norm.T


def print_matrix(title: str, sentences: list[str], matrix: np.ndarray) -> None:
    print(f"\n=== {title} ===")
    header = " " * 14 + "".join(f"{s:>14}" for s in sentences)
    print(header)
    for s, row in zip(sentences, matrix):
        print(f"{s:<14}" + "".join(f"{v:>14.3f}" for v in row))


def print_anchor_ranking(title: str, anchor: str, sentences: list[str], matrix: np.ndarray) -> None:
    idx = sentences.index(anchor)
    pairs = [(s, matrix[idx][i]) for i, s in enumerate(sentences) if s != anchor]
    pairs.sort(key=lambda x: -x[1])
    print(f"\n[{title}] 以「{anchor}」为基准，与其余句子的相似度排序：")
    for s, v in pairs:
        print(f"  {anchor} vs {s:<12} 余弦相似度 = {v:.3f}")


# ---------- 第一组：未训练的随机 Embedding（模拟 Transformer 最原始的 Embedding 层） ----------

def random_embedding_demo(d_model: int = EMBEDDING_DIM, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # 用字符级切分模拟分词，中英文都按最小单元切开
    vocab: dict[str, np.ndarray] = {}

    def get_vec(token: str) -> np.ndarray:
        if token not in vocab:
            vocab[token] = rng.normal(size=d_model)  # 随机初始化，未训练
        return vocab[token]

    sentence_vecs = []
    for s in SENTENCES:
        tokens = list(s.replace(" ", "")) if any("一" <= c <= "鿿" for c in s) else s.lower().split()
        token_vecs = np.stack([get_vec(t) for t in tokens])
        sentence_vecs.append(token_vecs.mean(axis=0))  # 简单mean pooling得到句向量
    return np.stack(sentence_vecs)


# ---------- 第二组：预训练多语言模型的句子向量 ----------

def pretrained_embedding_demo() -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(PRETRAINED_MODEL_NAME)
    return model.encode(SENTENCES, normalize_embeddings=False)


def main() -> None:
    random_vecs = random_embedding_demo()
    random_sim = cosine_sim_matrix(random_vecs)
    print_matrix("未训练随机Embedding 余弦相似度", SENTENCES, random_sim)
    print_anchor_ranking("未训练随机Embedding", "我爱你", SENTENCES, random_sim)

    print(f"\n正在加载预训练多语言模型 {PRETRAINED_MODEL_NAME}（首次运行会下载模型权重，约几百MB，请耐心等待）...")
    pretrained_vecs = pretrained_embedding_demo()
    pretrained_sim = cosine_sim_matrix(pretrained_vecs)
    print_matrix(f"预训练句子向量（模型: {PRETRAINED_MODEL_NAME}） 余弦相似度", SENTENCES, pretrained_sim)
    print_anchor_ranking(f"预训练句子向量-{PRETRAINED_MODEL_NAME}", "我爱你", SENTENCES, pretrained_sim)

    # 保存热力图，直观对比两组结果
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = ["STHeiti", "Arial Unicode MS", "Songti SC"]
        plt.rcParams["axes.unicode_minus"] = False

        fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
        for ax, (title, matrix) in zip(
            axes,
            [
                ("未训练随机Embedding", random_sim),
                (f"预训练句子向量（模型: {PRETRAINED_MODEL_NAME}）", pretrained_sim),
            ],
        ):
            im = ax.imshow(matrix, vmin=-1, vmax=1, cmap="RdYlGn")
            ax.set_xticks(range(len(SENTENCES)))
            ax.set_yticks(range(len(SENTENCES)))
            ax.set_xticklabels(SENTENCES, rotation=45, ha="right")
            ax.set_yticklabels(SENTENCES)
            ax.set_title(title, fontsize=10)
            for i in range(len(SENTENCES)):
                for j in range(len(SENTENCES)):
                    ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", fontsize=8)
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        fig.suptitle("余弦相似度对比：未训练Embedding vs 预训练句子向量")
        fig.tight_layout()
        out_path = "embedding_similarity_heatmap.png"
        fig.savefig(out_path, dpi=150)
        print(f"\n热力图已保存到: {out_path}")
    except Exception as e:  # 绘图失败不影响主流程的数值结论
        print(f"\n(绘图跳过，原因: {e})")


if __name__ == "__main__":
    main()
