# 生产部署

Layer 5的话题，现在还没正式开始学（当前在Layer 3 Multi-Agent编排），这里先占坑记一条从Multi-Agent编排那章顺带查到的发现——**彩虹部署（Rainbow Deployment）**，等后面正式学到这一章时再补充完整参考资料和其他内容。

## 彩虹部署（Rainbow Deployment）——Anthropic用来解决"给一个高度有状态的agent系统发版"的问题

**来源**：Anthropic工程博客[《How we built our multi-agent research system》](https://www.anthropic.com/engineering/multi-agent-research-system)，"Production reliability and engineering challenges"一节，原文：

> "Deployment needs careful coordination. Agent systems are highly stateful webs of prompts, tools, and execution logic that run almost continuously. This means that whenever we deploy updates, agents might be anywhere in their process. We therefore need to prevent our well-meaning code changes from breaking existing agents. We can't update every agent to the new version at the same time. Instead, we use rainbow deployments to avoid disrupting running agents, by gradually shifting traffic from old to new versions while keeping both running simultaneously."

https://brandon.dimcheff.com/2018/02/rainbow-deploys-with-kubernetes/