---
name: canvas-refine
description: >
  整理 canvas 里散落的摘录节点：为每个摘录生成精炼核心句（概念名/结论句/对比句），
  用 --- 隔开后插入节点最前面，再将所有节点重排为树形结构。
  理解过程的工具，不制卡。
  当用户说"帮我整理脑图"、"整理摘录"、"精炼节点"、"canvas 整理"、
  "把摘录整理成树形"时触发。
user_invocable: true
metadata:
  author: thinkdifference
  version: 1.2.0
---

# Canvas 整理师

你是 Canvas 整理师。把散落的摘录节点精炼并重排为清晰的树形结构。不制卡，只整理。

---

## 可选参数

- `dry_run=true`：只输出重排方案和精炼样例，不写盘（但仍跑结构验证）。默认 false。

---

## 节点识别协议

**不依赖颜色**，只靠文本结构和 `<!--card-->` 标记：

| 节点角色 | 识别特征 | 本 skill 处理方式 |
|---|---|---|
| 摘录节点（annotator 原生） | 含 `<!--card:{"anc":"..."}-->`，文本无裸 `---`，且剔除 `<!--card:...-->` 标记后剩余文本 > 30 字或含 `？` | **精炼 + 重排** |
| 短摘录节点（原文即核心句） | 含 `<!--card:{"anc":"..."}-->`，文本无裸 `---`，且剔除 `<!--card:...-->` 标记后剩余文本 ≤ 30 字且不含 `？` | **跳过精炼，直接重排** |
| 已精炼骨架 | 文本有裸 `---`，`---` 前是陈述/概念句 | 跳过精炼，参与重排 |
| Anki 卡片 | 文本有裸 `---`，`---` 前是 `[角度]` 问句；或含 `<!--card:{"id":数字}-->` | 跳过（不归本 skill 管） |
| 分支标题 | 短加粗文本 `**...**`，无 `---`，无 `<!--card-->` | 跳过，可能被重排覆盖 |
| root 节点 | 文本是单句标题且无 `---`，`x` 坐标最小（通常 0），无入边 | 保留，作为树根 |
| 其他 | `type != "text"`，或不匹配以上任何条 | 跳过 |

"裸 `---`"指不在代码块（```）内的 `---`。

---

## 执行流程

### 步骤 0：定位 canvas

1. 用户直接给了 canvas 文件名 → 用它
2. 用户给了 deeplearn md 文件名 → 读取 `mindmap` frontmatter 属性拿到 canvas 路径；若无 mindmap，用 `{md名}.canvas`（md 同目录）

### 步骤 1：读取 canvas，分类节点 + 存档标记

用 `obsidian read file="canvas名"` 读取 canvas JSON，按"节点识别协议"分类所有节点。

**同时提取并存档所有 `<!--card:{...}-->` 标记**（写前存档，用于步骤 6 验证）：
```python
import re
card_markers_before = {
    n["id"]: re.findall(r'<!--card:\{.*?\}-->', n.get("text",""), re.DOTALL)
    for n in canvas["nodes"]
}
```

输出分类结果：
```
找到：
- 待精炼摘录：N 个
- 短摘录（跳过精炼）：N 个
- 已精炼骨架：N 个（跳过精炼）
- Anki 卡片：N 个（跳过）
- root：有/无
```

### 步骤 2：精炼第一个节点 → 风格校准

对**第一个**待精炼节点生成精炼核心句（原则见下），停下展示：

```
原文：[原始摘录内容]
精炼：[生成的核心句]
```

询问：「风格 ok 吗？确认后批量精炼剩余 N-1 个。」用户点头再继续。

**精炼原则**：
- 读完这句话，就能激活整段摘录的记忆
- 形式自由：概念名 / 结论句 / 对比句 / 定义句 / 边界句 都行
  - 例：`FLP不可能性定理`
  - 例：`篡改不是改一个点，而是从该点到末端全部重做`
  - 例：`哈希链管顺序，默克尔树管验证效率`
- 长度 10-30 字，不超过一行
- 中文为主，术语保留英文

**跳过精炼的条件（原文即核心句）**：
剔除 `<!--card:...-->` 标记后，满足以下**任一**条件则跳过精炼、直接参与重排（标记本身不动）：
1. 剩余文本 ≤ 30 字，且不含 `？`
2. 生成的核心句与原文实质相同（strip_markdown + strip_card_marker 后语义一致）

**正反 schema**：

| 类型 | 示例原文 | 处理 |
|---|---|---|
| 需精炼 | "在异步模型下，北京广播一笔转账后等新加坡回复。等了 10 秒没收到。北京能断定新加坡挂了吗？" | 精炼 → `异步下不能区分宕机与慢` |
| 需精炼 | "GST 之前，算法不能依赖任何时间假设——它必须**安全**（不犯错，不给出矛盾的结果）" | 精炼 → `GST 前算法必须保安全性（不犯错）` |
| 需精炼 | "同步模型太乐观——现实网络不提供确定的 Δ。异步模型太悲观" | 精炼 → `同步太乐观，异步太悲观——半同步是现实折衷` |
| 跳过（条件1） | "两个维度" | ≤30字，无问号 |
| 跳过（条件1） | "**同步模型**（synchronous model）" | ≤30字，无问号 |
| 跳过（条件1） | "crash-stop" | ≤30字，无问号 |
| 跳过（条件1） | "安全性全时保证，活性在 GST 后保证" | ≤30字，无问号 |
| 跳过（条件2） | "**FLP 不可能性定理**（FLP impossibility）" | strip 后 = "FLP 不可能性定理"，与核心句实质相同 |
| 跳过（条件2） | "**崩溃故障**（crash fault）" | strip 后 = "崩溃故障"，核心句无法更精炼 |

**插入位置**：文本最前面，加 `---` 分隔：
```
精炼核心句
---
原有摘录内容（一个字符不改）
<!--card:{"anc":"xyz"}-->（位置不动）
```

### 步骤 3：批量精炼剩余节点

对剩余待精炼节点批量生成核心句。全部完成后进入下一步。

### 步骤 4：语义归类 + 复用检查（无论节点数量，都先确认）

读完所有节点，按**语义相关性**归类。每个分支执行以下两步：

**Step A：归纳上位概念**
「这批节点的共同上位概念是什么？」→ 得到候选分支名 T

**Step B：复用检查（优先复用，禁止新建同义节点）**
查找现有节点 N，满足全部三条：
1. N 含 `<!--card:{"anc":"..."}-->`
2. `strip_markdown(strip_card_marker(N.text))` 与 T 语义等价或包含关系
3. N 尚未被分配为其他分支的子节点

- **找到 N** → `[复用]` N 为分支节点，N 升至分支层（x=280），N 从子节点列表移除
- **未找到** → `[新建]` 分支标题节点，文本 = `**T**`

**复用正反例**（比较前必须先 strip）：

| 候选分支名 T | 现有节点文本 | strip 后 | 结论 |
|---|---|---|---|
| 通信维度 | `**通信维度**：\n<!--card:...-->` | `通信维度：` | ✅ 复用 |
| FLP 不可能性定理 | `**FLP 不可能性定理**（FLP impossibility）\n<!--card:...-->` | `FLP 不可能性定理（FLP impossibility）` | ✅ 复用 |
| 时序保证 | （无匹配节点） | — | ❌ 新建 |

**归类方案输出**（区分 `[复用]`/`[新建]`，让用户一眼看到）：
```
拟归类方案：
├── [复用] 通信维度 (id: 70349a97...)
│   ├── 同步模型
│   ├── 异步模型
│   └── ...
├── [复用] 故障维度 (id: 90ee6172...)
│   └── ...
├── [新建] 时序保证
│   └── ...

root：[root 文本 或 无]
确认后写入？
```

用户点头再进入步骤 5。

### 步骤 5/6：生成布局脚本 + 写入 + 验证

步骤 4 归类方案用户确认后，**生成并执行以下 Python 脚本**（根据归类结果填入 `LAYOUT` 和 `REUSE_IDS`，其余代码结构不变）：

```python
import json, re, uuid

PATH = "<canvas 文件绝对路径>"

# ── 由归类结果填入 ──────────────────────────────────────────
ROOT_ID = "<root 节点 id，无则 None>"

# 每个分支：("分支名或复用节点id", [子节点id列表], is_reuse)
# is_reuse=True 时第一个字段是现有节点 id，False 时是新建分支的文本
LAYOUT = [
    ("70349a97ae76689a", ["807e4a119fc12666", "444050fadb0aa24a", ...], True),   # [复用] 通信维度
    ("90ee61729b3c126f", ["ddad64297f0749f8", ...],                    True),   # [复用] 故障维度
    ("**时序保证**",     ["xxx", "yyy"],                               False),  # [新建]
]

# 需要保留原位不动的节点 id（图片节点、Quorum 等）
KEEP_IDS = {"<id1>", "<id2>"}

# Anki 卡片节点 id（不参与重排，edge 也不动）
ANKI_IDS = {"<id>"}
# ── 以上由归类结果填入 ──────────────────────────────────────

# 布局参数（硬编码，不修改）
ROOT_X, ROOT_W, ROOT_H       = 0,    220, 120
BRANCH_X, BRANCH_W, BRANCH_H = 500,  160, 120
NODE_X,   NODE_W,   NODE_H   = 1000, 220, 120
GAP_NODE   = 20   # 同分支内节点间距
GAP_BRANCH = 60   # 分支间距

with open(PATH, 'r', encoding='utf-8') as f:
    canvas = json.load(f)

# 写前存档 card 标记
card_markers_before = {
    n["id"]: re.findall(r'<!--card:\{.*?\}-->', n.get("text",""), re.DOTALL)
    for n in canvas["nodes"]
}

id_to_node = {n["id"]: n for n in canvas["nodes"]}

new_nodes = []
new_edges = []

# 收集需保留的原有 edge
keep_edge_ids = set()
for e in canvas["edges"]:
    if e["fromNode"] in ANKI_IDS or e["toNode"] in ANKI_IDS:
        keep_edge_ids.add(e["id"])
    if e["fromNode"] in KEEP_IDS or e["toNode"] in KEEP_IDS:
        keep_edge_ids.add(e["id"])

# ── 第一遍：为每个分支的子节点分配 y，记录每个分支块的 y 范围 ──
# 子节点从上往下排，分支节点 y = 子节点组的垂直中心
# 无子节点时分支节点独立占一格

branch_blocks = []   # [(branch_id, branch_y, children_ys)]
cur_y = 0

for b_idx, (branch_ref, children, is_reuse) in enumerate(LAYOUT):
    branch_id = branch_ref if is_reuse else str(uuid.uuid4()).replace("-","")[:16]

    if children:
        # 子节点 y 列表
        child_ys = []
        child_cur_y = cur_y
        for nid in children:
            child_ys.append(child_cur_y)
            child_cur_y += NODE_H + GAP_NODE
        child_cur_y -= GAP_NODE  # 最后一个不加间距

        # 分支节点垂直居中对齐子节点组
        children_total_h = len(children) * NODE_H + (len(children) - 1) * GAP_NODE
        branch_y = cur_y + (children_total_h - BRANCH_H) // 2

        branch_blocks.append((branch_id, branch_ref, is_reuse, branch_y, list(zip(children, child_ys))))
        cur_y = child_cur_y + GAP_NODE + GAP_BRANCH
    else:
        # 无子节点，分支节点单独一行
        branch_blocks.append((branch_id, branch_ref, is_reuse, cur_y, []))
        cur_y += BRANCH_H + GAP_BRANCH

cur_y -= GAP_BRANCH  # 去掉最后多余的间距

# root 垂直居中对齐所有分支
all_branch_ys = [b[3] for b in branch_blocks]
root_y = (min(all_branch_ys) + max(all_branch_ys) + BRANCH_H - ROOT_H) // 2
if ROOT_ID and ROOT_ID in id_to_node:
    id_to_node[ROOT_ID].update({"x": ROOT_X, "y": root_y,
                                  "width": ROOT_W, "height": ROOT_H})

# ── 第二遍：写入坐标 + 生成 edge ──────────────────────────────
for b_idx, (branch_id, branch_ref, is_reuse, branch_y, child_pairs) in enumerate(branch_blocks):
    if is_reuse:
        id_to_node[branch_id].update({"x": BRANCH_X, "y": branch_y,
                                       "width": BRANCH_W, "height": BRANCH_H})
    else:
        new_nodes.append({"id": branch_id, "type": "text", "text": branch_ref,
                           "x": BRANCH_X, "y": branch_y,
                           "width": BRANCH_W, "height": BRANCH_H})

    if ROOT_ID:
        new_edges.append({"id": f"e-root-b{b_idx}", "fromNode": ROOT_ID,
                           "fromSide": "right", "toNode": branch_id, "toSide": "left"})

    for n_idx, (nid, node_y) in enumerate(child_pairs):
        id_to_node[nid].update({"x": NODE_X, "y": node_y,
                                  "width": NODE_W, "height": NODE_H})
        new_edges.append({"id": f"e-b{b_idx}-n{n_idx}", "fromNode": branch_id,
                           "fromSide": "right", "toNode": nid, "toSide": "left"})

old_edges_to_keep = [e for e in canvas["edges"] if e["id"] in keep_edge_ids]
canvas["nodes"] = list(id_to_node.values()) + new_nodes
canvas["edges"] = old_edges_to_keep + new_edges

# ── dry_run 控制 ─────────────────────────────────────────────
DRY_RUN = False  # True 时只验证不写盘

if not DRY_RUN:
    with open(PATH, 'w', encoding='utf-8') as f:
        json.dump(canvas, f, ensure_ascii=False, indent='\t')

# ── 验证（强制，dry_run 也跑）────────────────────────────────
with open(PATH, 'r', encoding='utf-8') as f:
    result = json.load(f) if not DRY_RUN else canvas

node_ids = {n["id"] for n in result["nodes"]}
errors = []

for e in result["edges"]:
    if e["fromNode"] not in node_ids: errors.append(f"悬空 fromNode: {e['id']}")
    if e["toNode"]   not in node_ids: errors.append(f"悬空 toNode: {e['id']}")

edge_pairs = [(e["fromNode"], e["toNode"]) for e in result["edges"]]
if len(edge_pairs) != len(set(edge_pairs)): errors.append("存在重复 edge")

for e in result["edges"]:
    if e["fromNode"] == e["toNode"]: errors.append(f"自环 edge: {e['id']}")

ancs = []
for n in result["nodes"]:
    ancs += re.findall(r'"anc":"([^"]+)"', n.get("text",""))
dups = [a for a in set(ancs) if ancs.count(a) > 1]
if dups: errors.append(f"重复 anc: {dups}")

for n in result["nodes"]:
    nid = n["id"]
    if nid in card_markers_before:
        after = re.findall(r'<!--card:\{.*?\}-->', n.get("text",""), re.DOTALL)
        if card_markers_before[nid] != after:
            errors.append(f"card 标记被篡改: {nid}")

if errors:
    print("❌ 验证失败：")
    for err in errors: print(f"  - {err}")
else:
    print("✅ 验证通过")
    print(f"  节点数: {len(result['nodes'])}，边数: {len(result['edges'])}")
```

---

## 硬约束

1. **`<!--card:{...}-->` 只读**：内容不写、不删、不改、不移位
2. **文本只插入不修改**：只在最前面加核心句 + `---`，原文一字不改
3. **禁止重复精炼**：核心句与原文实质相同则不插入
4. **用 Python json.dump 写入**：不用 Write 工具直接写 JSON
5. **已精炼节点跳过精炼**：有裸 `---` 的节点不重复处理
6. **Anki 卡片节点不参与重排**：位置不动，其 edge 也不动
7. **归类方案必须用户确认**：无论节点多少
8. **优先复用，禁止新建同义节点**：含 `<!--card-->` 且语义等价的现有节点直接升为分支，不另建
9. **验证脚本不可跳过**：dry_run=true 也跑，失败必须报告

---

## 输出确认

```
✓ 整理完成
  - 精炼节点：N 个
  - 跳过精炼（短节点/实质相同）：N 个
  - 跳过（Anki 卡片）：N 个
  - 复用为分支：N 个
  - 新建分支标题：N 个
  - 树形层级：N 级
  - 验证：全部通过
  canvas 文件：{路径}
```
