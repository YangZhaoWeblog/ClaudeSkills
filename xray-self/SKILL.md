---
name: xray-self
description: Use when the user says xray-self, 自我透视, vault 自画像, 隐藏模式, 给我做画像, 自我诊断, 体检, or asks to inspect long-term knowledge/work patterns across an Obsidian vault.
---

# xray-self

## Mission

扫描 Obsidian vault，产出一份结构化自画像：看见事实，挖出模式，提出可证伪的深层假说。目标不是心理分析，而是提高外部可验证产出的质量和频率。

## Operating rules

- 默认扫描当前 vault：`/Users/yangzhao/Documents/MyDigitalGarden`。
- 优先使用 Obsidian CLI；CLI 不足时用 Glob/Grep/Read/Bash 读只读信息。
- 输出写入：`2.工作稿/个人规划/xray-self/自画像-{YYYY-MM-DD}.md`。
- 必须创建/更新一份画像文件；不要只在终端口头总结。
- 不做心理/医学诊断，不把人格标签当结论。
- 不把单一信号写成刺痛；刺痛至少需要两个独立信号。
- 不把推测写成事实；所有深层判断都标 `[推测]`。
- 每个核心结论必须写：证据、置信度、可推翻条件。

## Scan method

按五层扫描，不可跳层：

1. **统计分布**：目录、标签、文件数量、近期活跃、主题频率。
2. **加工深度**：raw/source → inbox → 工作稿 → deep/light-learn → 原子笔记 → canvas/card → MOC → 外部输出。
3. **链接拓扑**：backlinks、outlinks、hub、bridge、orphan、deadend、unresolved。
4. **无意识痕迹**：重复词、空文件、搁置、过度系统化、反复 should、强烈措辞。
5. **时间轨迹**：最近增强、衰减、反复返回的问题、输出变化。

## Evidence protocol

| 层级 | 含义 | 可写什么 |
|---|---|---|
| `[确定]` | 可直接观察 | 数量、路径、标签、链接、文件存在、修改记录 |
| `[较确定]` | 多信号模式 | 执行力分布、加工深度差异、主题聚集/搁置 |
| `[推测]` | 深层解释 | 欲望层级、核心焦虑、操作系统、被忽视资产 |

结论格式：

```md
### 结论：...
- 置信度：确定 / 较确定 / 推测
- 证据：...
- 可推翻条件：...
- 如果成立，它意味着：...
```

## Output structure

使用 `references/portrait-template.md` 的结构。画像必须包含：

- 摘要表：结论 / 置信度 / 关键证据 / 可推翻条件
- 五层扫描结果
- 核心结论
- 刺痛：最不想听但最需要听的一句话
- 资产：已形成但可能被低估的能力/结构
- 行动：1-3 个可验收动作

## Completion checklist

- [ ] 完成五层扫描。
- [ ] 明确区分 `[确定]` / `[较确定]` / `[推测]`。
- [ ] 每个核心结论有可推翻条件。
- [ ] 刺痛至少有两个独立信号。
- [ ] 同时写出资产和行动。
- [ ] 画像已写入 vault 指定路径。
