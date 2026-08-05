## 语料来源

`TokenEconomics.md` 1.1.1节统计数据 和 `stat_tokenizer_efficiency.py` 用的就是这份语料，原样保存在这里方便直接打开查看，不是摘要或改写过的版本。

| 文件 | 来源 | 说明 |
|---|---|---|
| `en_alice_in_wonderland.txt` | [Project Gutenberg #11](https://www.gutenberg.org/ebooks/11) | 《爱丽丝梦游仙境》全文，公有领域，文件内含Gutenberg官方许可声明 |
| `en_great_expectations.txt` | [Project Gutenberg #1400](https://www.gutenberg.org/ebooks/1400) | 《远大前程》全文，公有领域，文件内含Gutenberg官方许可声明 |
| `zh_wikipedia_extracts.txt` | 中文维基百科，通过[官方API](https://zh.wikipedia.org/w/api.php)拉取的纯文本正文 | 10篇条目摘录：人工智能、中华人民共和国、上海市、足球、经济学、计算机科学、第二次世界大战、咖啡、音乐、旅游。内容遵循[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)协议 |

统计时英文按`[A-Za-z]+(?:'[A-Za-z]+)?`正则切出"单词"，中文按`[一-鿿]`正则统计汉字数，具体逻辑见`../stat_tokenizer_efficiency.py`。
