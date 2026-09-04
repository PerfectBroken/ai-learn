# Terminal-Bench

来源：https://www.tbench.ai/ 。这个官网首页本身内容很薄，主要是一张实时排行榜，没有太多方法论说明，summary里方法论部分补充了另外两篇笔记（《Demystifying》《Quantifying infrastructure noise》）里已经核实过的信息。

## Summary

**是什么**：测试端到端的技术任务，让agent在真实终端环境里完成类似"从源码编译Linux内核""训练一个ML模型"这类完整工程任务，跟SWE-bench"改一个具体bug"这种局部任务不同，覆盖面更宽、更贴近真实运维/工程场景。

**当前排行榜快照**（抓取于2026-08-31，Terminal-Bench官网实时数据，会持续变化）：第一名是Opus 5 + Claude Code组合，得分**51.8% ± 3.4%**（2026-07-24）；第二名Fable 5 + Claude Code 44.5%；第三名GLM-5.3 + Claude Code 41.8%；OpenAI的GPT-5.6系列配Codex在37.3%~17.3%之间；xAI的Grok 4.6/4.5配Grok Build在12%~20%之间。

**这个分数水平本身值得注意**：对照《Demystifying》里"SWE-bench一年内从40%涨到超过80%、正在逼近饱和"，Terminal-Bench的最高分才刚过50%——说明它比SWE-bench难得多，离饱和还很远，是目前更能拉开模型差距的benchmark，这也解释了为什么Anthropic在《Quantifying infrastructure noise》那篇里专门拿它做基础设施噪音的主实验对象（分数还没饱和，才有空间观察到6个百分点的infra噪音）。

**2.0版本的资源规范**：《Quantifying infrastructure noise》提到Terminal-Bench 2.0在每个task级别都标注了推荐的CPU和RAM配置，但"标注"不等于"强制执行一致"——这正是那篇笔记探讨的核心问题（不同的容器资源强制方式，会实际改变这个benchmark测的是什么）。

## 参考资料

- Terminal-Bench, https://www.tbench.ai/
