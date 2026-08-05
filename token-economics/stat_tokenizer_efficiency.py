"""
统计不同tokenizer下，平均每个英文单词/每个汉字消耗多少token。

对比对象：
- o200k_base   （GPT-4o现役）
- cl100k_base  （GPT-3.5 / GPT-4旧一代）
- DeepSeek-V4-Pro 官方tokenizer（从HuggingFace官方仓库下载）
- Kimi-K3 官方tokenizer（从HuggingFace官方仓库下载）

语料：
- 英文：Project Gutenberg公开的《爱丽丝梦游仙境》+《远大前程》全文
- 中文：中文维基百科10篇不同主题条目的正文摘录

结果对应 TokenEconomics.md 1.1.1节的数据来源，运行本脚本可复现。
"""

import json
import os
import re
import urllib.parse
import urllib.request

import tiktoken
from tiktoken.load import load_tiktoken_bpe
from tokenizers import Tokenizer

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 语料是可以公开重新分发的文本（Gutenberg公有领域 / 维基百科CC BY-SA），
# 保存在corpus/目录里并提交进仓库，方便直接打开查看，见corpus/README.md。
CORPUS_DIR = os.path.join(os.path.dirname(__file__), "corpus")
os.makedirs(CORPUS_DIR, exist_ok=True)

EN_SOURCES = [
    ("en_alice_in_wonderland.txt", "https://www.gutenberg.org/files/11/11-0.txt"),
    ("en_great_expectations.txt", "https://www.gutenberg.org/cache/epub/1400/pg1400.txt"),
]

ZH_WIKI_TITLES = [
    "人工智能", "中华人民共和国", "上海市", "足球", "经济学",
    "计算机科学", "第二次世界大战", "咖啡", "音乐", "旅游",
]

KIMI_PAT_STR = "|".join([
    r"""[\p{Han}]+""",
    r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
    r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
    r"""\p{N}{1,3}""",
    r""" ?[^\s\p{L}\p{N}]+[\r\n]*""",
    r"""\s*[\r\n]+""",
    r"""\s+(?!\S)""",
    r"""\s+""",
])


def _download(url: str, dest: str, timeout: int = 30) -> None:
    if os.path.exists(dest):
        return
    print(f"下载 {url} -> {dest}")
    urllib.request.urlretrieve(url, dest)


def _strip_gutenberg(text: str) -> str:
    start = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", text, re.IGNORECASE | re.DOTALL)
    end = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK", text, re.IGNORECASE)
    s = start.end() if start else 0
    e = end.start() if end else len(text)
    return text[s:e]


def load_en_corpus() -> str:
    text = ""
    for filename, url in EN_SOURCES:
        dest = os.path.join(CORPUS_DIR, filename)
        _download(url, dest)
        text += _strip_gutenberg(open(dest, encoding="utf-8").read()) + "\n"
    return text


def load_zh_corpus() -> str:
    dest = os.path.join(CORPUS_DIR, "zh_wikipedia_extracts.txt")
    if not os.path.exists(dest):
        print("拉取中文维基百科语料...")
        texts = []
        for title in ZH_WIKI_TITLES:
            quoted = urllib.parse.quote(title)
            api_url = (
                "https://zh.wikipedia.org/w/api.php?action=query&prop=extracts"
                f"&explaintext=1&format=json&titles={quoted}"
            )
            with urllib.request.urlopen(api_url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                texts.append(page.get("extract", ""))
        with open(dest, "w", encoding="utf-8") as f:
            f.write("\n".join(texts))
    return open(dest, encoding="utf-8").read()


def load_deepseek_v4_tokenizer() -> Tokenizer:
    dest = os.path.join(CACHE_DIR, "dsv4_tokenizer.json")
    _download(
        "https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/resolve/main/tokenizer.json",
        dest,
        timeout=60,
    )
    return Tokenizer.from_file(dest)


def load_kimi_k3_tokenizer() -> tiktoken.Encoding:
    dest = os.path.join(CACHE_DIR, "kimi_tiktoken.model")
    _download(
        "https://huggingface.co/moonshotai/Kimi-K3/resolve/main/tiktoken.model",
        dest,
        timeout=60,
    )
    mergeable_ranks = load_tiktoken_bpe(dest)
    return tiktoken.Encoding(
        name="kimi-k3",
        pat_str=KIMI_PAT_STR,
        mergeable_ranks=mergeable_ranks,
        special_tokens={},
    )


def main() -> None:
    en_text = load_en_corpus()
    zh_text = load_zh_corpus()

    en_words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", en_text)
    han_chars = re.findall(r"[一-鿿]", zh_text)
    print(f"英文语料: {len(en_text)}字符 / {len(en_words)}个单词")
    print(f"中文语料: {len(zh_text)}字符 / {len(han_chars)}个汉字")
    print()

    results = []

    for name, enc in [
        ("o200k_base (GPT-4o)", tiktoken.encoding_for_model("gpt-4o")),
        ("cl100k_base (GPT-3.5/GPT-4旧)", tiktoken.get_encoding("cl100k_base")),
        ("Kimi-K3", load_kimi_k3_tokenizer()),
    ]:
        en_ratio = len(enc.encode(en_text)) / len(en_words)
        zh_ratio = len(enc.encode(zh_text)) / len(han_chars)
        results.append((name, enc.n_vocab, en_ratio, zh_ratio))

    dsv4 = load_deepseek_v4_tokenizer()
    en_ratio = len(dsv4.encode(en_text).ids) / len(en_words)
    zh_ratio = len(dsv4.encode(zh_text).ids) / len(han_chars)
    results.append(("DeepSeek-V4-Pro", dsv4.get_vocab_size(), en_ratio, zh_ratio))

    print(f"{'Tokenizer':32s} {'词表大小':>10s} {'英文token/单词':>14s} {'中文token/汉字':>14s}")
    for name, vocab_size, en_ratio, zh_ratio in results:
        print(f"{name:32s} {vocab_size:>10d} {en_ratio:>14.3f} {zh_ratio:>14.3f}")


if __name__ == "__main__":
    main()
