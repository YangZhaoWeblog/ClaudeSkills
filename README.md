# Claude Code Skills

一套为 [Claude Code](https://claude.ai/code) 打造的认知增强 Skills，专注于**深度学习、知识管理与思维工具**。

<a href="https://star-history.com/#YangZhaoWeblog/ClaudeSkills&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=YangZhaoWeblog/ClaudeSkills&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=YangZhaoWeblog/ClaudeSkills&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=YangZhaoWeblog/ClaudeSkills&type=Date" />
 </picture>
</a>

---

## 目录

- [ThinkDifference 系列](#thinkdifference-系列)
- [TD 系列](#td-系列)
- [LJG 系列](#ljg-系列)
- [其他工具](#其他工具)
- [快速上手](#快速上手)
- [Star History](#star-history)

---

## ThinkDifference 系列

> 为"真正学透知识"而生的一套工具链，从深挖、轻记到制卡形成完整闭环。

| Skill | 描述 | 触发方式 |
|---|---|---|
| [thinkdifference-learn-deep](./thinkdifference-learn-deep/) | 知识点深挖引导器，通过四幕式引导（问题感知→引导式构建→完整组装→压力测试）重走发明之路 | "帮我学透XX"、"深入理解XX"、"XX原理详解" |
| [thinkdifference-light-learn](./thinkdifference-light-learn/) | 轻量知识焊接器，用最少墨水将碎片知识点焊接到已有知识网络 | "补一下X"、"记一下X"、"light-learn X" |
| [thinkdifference-make-cards](./thinkdifference-make-cards/) | 将文章/笔记/知识点转化为高质量间隔重复卡片，从多个认知角度切面覆盖 | "帮我制卡"、"生成Anki卡片"、"做成闪卡" |
| [thinkdifference-card-coach](./thinkdifference-card-coach/) | 制卡教练，优化已有卡片的提问与答案，不代写而是引导用户自己打磨 | "帮我优化这张卡"、"这张卡问得不好" |
| [thinkdifference-extract-atoms](./thinkdifference-extract-atoms/) | 从任意笔记/文章中提取原子知识点，生成 Zettelkasten 风格笔记（含关联图谱） | "提取原子笔记"、"原子化"、"extract atoms" |

---

## TD 系列

> 学习路径规划与知识网络构建工具。

| Skill | 描述 | 触发方式 |
|---|---|---|
| [td-decompose](./td-decompose/) | 学习粒度诊断器，判断主题是"一个发明故事"还是"多个并行故事"，生成知识 DAG | "知识分解"、"帮我规划学习路径"、"我想学XXX该从哪里开始" |
| [td-synthesize](./td-synthesize/) | 知识缝合器 / MOC 生成器，读取多个已学概念并发现深层连接，生成或增量更新 MOC | "帮我综合"、"生成MOC"、"知识缝合"、"把这些概念串起来" |

---

## LJG 系列

> 对公式、学科进行结构性解构的分析工具。

| Skill | 描述 | 触发方式 |
|---|---|---|
| [ljg-formula-decoder](./ljg-formula-decoder/) | 公式解码器，将数学/物理公式还原为有血有肉的"现实机器"，经历5阶段解码流程 | 贴出任意公式（如 E=mc²）、"公式解码"、"这个公式什么意思" |
| [ljg-xray-discipline](./ljg-xray-discipline/) | 学科架构 X-ray，站在上帝视角提取学科的根本问题（目标函数）和核心骨架 | "帮我分析XX学科"、"XX领域的本质是什么"、"学科架构" |

---

## 其他工具

| Skill | 描述 | 触发方式 |
|---|---|---|
| [tech-doc-writer](./tech-doc-writer/) | 技术文档写作，通过四阶段流水线（定型→骨架→填充→交付+审查）产出高质量文档 | "写文档"、"写报告"、"技术调研"、"设计文档" |

---

## 快速上手

1. 将需要的 Skill 目录复制到你的 Claude Code 工作区
2. 在对话中使用触发语直接激活对应 Skill
3. Skills 之间可以组合使用，例如：`td-decompose` → `learn-deep` → `make-cards` 构成完整学习闭环

