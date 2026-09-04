# SWE-bench

来源：https://www.swebench.com/SWE-bench/ ，Princeton NLP出品，论文2024年被ICLR接收为oral（Jimenez et al.）。以下为summary，不做逐节翻译。

## Summary

**是什么**：给模型一个真实代码库和一个真实GitHub issue，让模型生成一个patch去解决这个issue，用Docker容器化的评估基础设施跑测试套件来判定patch是否修复了问题（且没有破坏原有测试）——是《Demystifying evals for AI agents》里coding agent确定性grader的代表案例。

**几个版本**：SWE-bench（全量）、SWE-bench Lite（精简子集）、**SWE-bench Verified**（2024-08-13发布，500个由人类工程师确认"确实可解"的问题，用来解决原始数据集里task本身有歧义/不可解的噪音问题——这一点跟《Demystifying》Step 2里"0%通过率往往是task本身有问题"的教训是同一类经验）、SWE-bench Multimodal（视觉相关的软件领域）。

**评估基础设施的演进**：2024-06-27上线了完全容器化（Docker）的评估harness保证结果可复现；2025-01-11加了基于Modal的云端评估方案，降低本地跑评估的门槛。

**生态**：围绕SWE-bench衍生了一系列配套项目——SWE-agent（参考agent实现）、SWE-smith（生成训练数据）、SWE-rex（执行环境）、CodeClash、SWE-bench CLI、mini-swe-agent，说明它已经从单一benchmark发展成了一整套编程agent评估/训练基础设施生态，不只是一份数据集。

**跟主线笔记的关联**：正是《Demystifying》里提到的那个"一年内通过率从40%涨到超过80%，正在逼近饱和"的benchmark（对应Step 7"关注capability eval的饱和"）；也是《Quantifying infrastructure noise》里用来做交叉验证的第二个benchmark（RAM从1x加到5x，通过率单调上升但增幅比Terminal-Bench小，符合"SWE-bench任务资源消耗本来就不大"的预期）。

## 具体用法：怎么真正跑起来一次评估

这部分翻自官方文档的Installation/Quickstart/Evaluation/Docker Setup/Datasets/Harness Reference/FAQ这几篇，是"如果你要拿SWE-bench去评估自己的coding agent"这个实际操作流程。

### 1 环境准备

**前置条件**：Python 3.9+、Docker（评估环境完全靠它跑），官方建议至少**120GB硬盘空间**、**16GB+内存**、**8核以上CPU**（x86_64架构，arm64目前是实验性支持）。

**安装**：

```bash
git clone https://github.com/princeton-nlp/SWE-bench.git
cd SWE-bench
pip install -e .

# 如果要自己生成数据集或做RAG推理，按需加装
pip install -e ".[make_datasets]"   # 数据集生成
pip install -e ".[inference]"       # 推理+数据集生成
pip install -e ".[modal]"           # 云端评估（Modal）
```

Docker装好之后先跑`docker run hello-world`确认能用。macOS/Windows上用Docker Desktop的话，记得去Resources设置里把分配的CPU/内存调到至少8核16GB，磁盘镜像大小调到至少120GB——默认值通常不够用。

### 2 数据集怎么选、怎么拿

官方给了五个变体，对应不同用途：

| 数据集 | 规模 | 适合场景 |
| --- | --- | --- |
| SWE-bench（全量） | 2,294条 | 全面评估 |
| SWE-bench Lite | 300~534条（文档口径不完全一致） | 快速迭代、开发阶段先用这个 |
| **SWE-bench Verified** | 500条，工程师人工确认过确实可解 | 你实际工作里最该用这个——排除了原始数据集里"题目本身有歧义/不可解"的噪音 |
| SWE-bench Multimodal | 100条dev + 500条test | 涉及截图/UI元素的多模态场景 |
| SWE-bench Multilingual | 300条，9种语言、42个仓库 | 不止测Python，跨语言场景 |

都托管在Hugging Face上，直接用`datasets`库拉：

```python
from datasets import load_dataset

swebench_verified = load_dataset('princeton-nlp/SWE-bench_Verified', split='test')
```

每条数据的结构大致是：`instance_id`（仓库+issue编号拼出来的唯一ID）、`repo`、`problem_statement`（issue描述，即喂给你的agent的输入）、`base_commit`（起始代码状态）、`patch`（官方金标准解法，**调试自己agent的时候不要偷看**）、`test_patch`、`FAIL_TO_PASS`/`PASS_TO_PASS`（分别是"修复后应该从失败变通过"和"修复前后都应该保持通过"的测试用例列表——这两个字段就是《Demystifying evals》里说的"fail-to-pass/pass-to-pass二元测试"这类code-based grader的具体实现）。

### 3 你的agent要产出什么格式

评估喂给harness的是一个JSONL文件，每行一个预测结果：

```json
{"instance_id": "sympy__sympy-20590", "model_name_or_path": "your-agent-name", "model_patch": "<git diff格式的补丁内容>"}
```

也就是说，你自己的coding agent要做的事情就是：读`problem_statement`，在给定的代码库里想办法解决这个issue，最后产出一个`git diff`格式的patch字符串——这跟真实场景里"扔给agent一个bug、让它提交一个PR"的形状是一致的，这也是这次你觉得它对实际工作更有意义的地方。

### 4 跑评估

**先验证环境本身没问题**——用官方金标准patch（"gold"）跑一遍，如果这都过不了，说明环境有问题，不是agent的问题（这正好对应《Demystifying evals》Step 2里"用参考解验证grader配置是否正确"那条经验）：

```bash
python -m swebench.harness.run_evaluation \
    --predictions_path gold \
    --max_workers 1 \
    --instance_ids sympy__sympy-20590 \
    --run_id validate-gold
```

**正式跑自己的预测结果**（建议先在Lite上跑通流程，再上Verified/全量）：

```bash
python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --predictions_path <你的predictions.jsonl路径> \
    --max_workers 8 \
    --run_id my_evaluation_run
```

也有更新的CLI写法（`swebench eval`），效果等价：

```bash
swebench eval verified -p <path_to_predictions> --run-id <run_id> -j 8
```

**只想跑某几条**：加`--instance_ids`，空格分隔多个ID。

**worker数怎么定**：官方建议`min(0.75 × CPU核数, 24)`——8核机器建议6个worker，16核建议12个，堆得太高反而会因为资源争抢变慢（这跟《Quantifying infrastructure noise》里"资源配置本身影响结果"是同一个坑，只是这里影响的是评估速度不是分数）。

**关于结果缓存要特别注意一个坑**：harness按`run_id`+`instance_id`缓存结果，**不看你这次提交的patch内容有没有变**——也就是说，如果你换了新的agent版本、生成了新的patch，但复用了同一个`run_id`，harness会直接返回上次缓存的旧结果，根本不会重新评估。**每次要评估新的预测结果，必须换一个新的`run_id`**，这个坑很容易踩，官方FAQ和文档里都单独强调了。

### 5 Docker资源怎么管

harness按三层构建镜像：base image（通用依赖）→ environment images（约60个，各Python环境配置）→ instance images（每个task专属依赖），层层复用来省空间，但依然很吃盘：

| `--cache_level` | 说明 | 磁盘占用 | 速度 |
| --- | --- | --- | --- |
| `none` | 不缓存 | 最小（跑的时候临时占~120GB） | 最慢 |
| `base` | 只缓存base镜像 | 最小 | 慢 |
| `env`（默认） | 缓存base+environment镜像 | 中等（~100GB） | 中等 |
| `instance` | 全部缓存 | 很大（~2000GB） | 最快 |

大多数场景默认的`env`就够用。磁盘紧张就用`none`/`base`，同时加`--clean True`让每个instance跑完自动清理。定期用`docker system prune -a`回收空间。

### 6 怎么读结果

跑完会在你执行命令的目录下生成一份汇总文件`<model>.<run_id>.json`，另外每个instance在`logs/run_evaluation/<run_id>/<model>/<instance_id>/`下有独立的文件夹，包含`report.json`（这条的结果）、`test_output.txt`（测试的完整输出）、`run_instance.log`（harness做了什么、失败了为什么失败）、`eval.sh`（跑测试用的脚本）、`patch.diff`（实际应用的补丁）——**这一整套就是《Demystifying evals》里说的transcript，Step 6"检查transcript"这个习惯在SWE-bench上就是去读这几个文件**。

几个容易混淆的统计字段：`Instances resolved`（patch真的让测试通过了）+`Instances unresolved`（测试跑了但没过）加起来才是"实际被打分"的数量；`Instances with errors`是"完全没能产出`report.json`"的那些（patch没能apply、容器没启动、跑超时），这些不是"agent做错了"，是"评估本身没能跑完"，需要单独看`run_instance.log`排查，不能跟"agent能力不够"混为一谈——这正好呼应《Demystifying evals》里"0%通过率往往是环境/task问题，不是agent问题"那条提醒。

### 7 云端跑（不想占用本地资源）

本地资源不够或者想跑大批量，可以用Modal：

```bash
pip install modal swebench[modal]
modal setup   # 首次要认证
python -m swebench.harness.run_evaluation \
    --predictions_path <path_to_predictions> \
    --parallelism 10 \
    --modal true
```

或者用更简单的`sb-cli`（提交到SWE-bench官方在AWS上的评估服务，不用自己管Docker环境）：

```bash
pip install sb-cli
sb login
sb submit --predictions <path_to_predictions>
```

### 8 跟你实际工作最相关的落地方式

对照《Demystifying evals》整篇的框架，如果要把SWE-bench用在自己的实际工作里（比如评估内部编程agent的能力），大致对应关系是：

- `problem_statement`就是你的**task**，`FAIL_TO_PASS`/`PASS_TO_PASS`就是**code-based grader**，多次跑同一个instance就是在积累**trial**；
- 先在**SWE-bench Verified**（已排除歧义task）上小规模跑通，符合"Step 0尽早开始，不用一上来就上全量"；
- 每次要重新评估记得换`run_id`，别被结果缓存坑了；
- 拿到`Instances with errors`的那些，先去读`run_instance.log`，分清楚是agent能力问题还是环境问题，再决定要不要归为真实的失败——这是"读transcript"这个习惯在SWE-bench上的具体落地。

## 参考资料

- SWE-bench Verified, https://www.swebench.com/SWE-bench/
- Installation, https://www.swebench.com/SWE-bench/installation/
- Quickstart, https://www.swebench.com/SWE-bench/guides/quickstart/
- Evaluation Guide, https://www.swebench.com/SWE-bench/guides/evaluation/
- Docker Setup Guide, https://www.swebench.com/SWE-bench/guides/docker_setup/
- Datasets, https://www.swebench.com/SWE-bench/guides/datasets/
- Evaluation Harness Reference, https://www.swebench.com/SWE-bench/reference/harness/
- FAQ, https://www.swebench.com/SWE-bench/faq/
