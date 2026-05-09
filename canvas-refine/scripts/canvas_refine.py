#!/usr/bin/env python3
"""
canvas_refine.py — Canvas 整理师的脚本后端。

两种模式：
  1) --classify-only        分类模式：读 canvas，输出 JSON 分类结果（供 AI 规划树形）
  2) --tree-json <path>     执行模式：按 tree_input.json 精炼+重排+写回 canvas

共同保证：
  - 所有原节点的非坐标顶层字段（canvasMargin / canvas2anki / color / file / ...）原样保留
  - 任一端点在 anki_ids 的 edge 原 id/fromNode/toNode 保留，不重建
  - Anki 卡片 y 跟随其源骨架节点同步
  - 失败时非零退出，不写盘
"""

import argparse
import copy
import json
import re
import sys
import uuid
from typing import Any


# ══════════════════════════════════════════════════════════════════════════
# ── textutil ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

_BARE_DASH_RE = re.compile(r"^---\s*$", re.MULTILINE)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def strip_markdown(s: str) -> str:
    """去 **加粗**、去行末 ;English 别名行、trim。用于比较语义等价。"""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\n;[^\n]*$", "", s)
    return s.strip()


def has_bare_dash(text: str) -> bool:
    """判断文本中是否含"裸 ---"（不在代码块内的 --- 行）。"""
    masked = _FENCE_RE.sub("", text)
    return bool(_BARE_DASH_RE.search(masked))


def has_question(text: str) -> bool:
    return "？" in text


def find_children(node_id: str, edges: list[dict]) -> list[str]:
    return [e["toNode"] for e in edges if e.get("fromNode") == node_id]


def find_parent(node_id: str, edges: list[dict]) -> str | None:
    for e in edges:
        if e.get("toNode") == node_id:
            return e.get("fromNode")
    return None


# ══════════════════════════════════════════════════════════════════════════
# ── classify ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════
#
# 识别优先级（高 → 低）：
#   1. canvas2anki 字段存在         → anki_card
#   2. 裸 --- + `[角度]` 前缀       → anki_card（未回写 id 的卡片）
#   3. 裸 ---                       → refined_skeleton（已精炼）
#   4. canvasMargin + 含 ？         → question_node
#   5. canvasMargin + 文本 ≤30 字   → short_excerpt
#   6. canvasMargin + 文本 >30 字   → long_excerpt（待精炼）
#   7. **加粗** 无 canvasMargin     → branch_title
#   8. 其他（file / group / 未知）  → preserve（坐标/edge 不动）

_BRACKET_TAG_RE = re.compile(r"^\s*\[[^\]]+\]")


def classify_node(node: dict) -> str:
    """返回节点角色字符串。"""
    ntype = node.get("type", "")
    if ntype != "text":
        return "preserve"

    text = node.get("text", "")
    has_margin = node.get("canvasMargin") is not None
    has_anki = node.get("canvas2anki") is not None

    # 1. canvas2anki 字段
    if has_anki:
        return "anki_card"

    # 2. 裸 --- + [角度] 前缀
    if has_bare_dash(text):
        first_line = text.split("\n", 1)[0]
        if _BRACKET_TAG_RE.match(first_line):
            return "anki_card"
        return "refined_skeleton"

    # 4-6. canvasMargin 摘录类
    if has_margin:
        if has_question(text):
            return "question_node"
        stripped = strip_markdown(text)
        if len(stripped) <= 30:
            return "short_excerpt"
        return "long_excerpt"

    # 7. 纯加粗短标题
    if re.match(r"^\s*\*\*[^*]+\*\*\s*$", text) and len(strip_markdown(text)) <= 30:
        return "branch_title"

    return "preserve"


def classify_all(canvas: dict) -> dict[str, list[dict]]:
    """分类所有节点，返回 {role: [节点简介]}。"""
    buckets: dict[str, list[dict]] = {
        "long_excerpt": [],
        "short_excerpt": [],
        "question_node": [],
        "refined_skeleton": [],
        "anki_card": [],
        "branch_title": [],
        "preserve": [],
    }
    for n in canvas.get("nodes", []):
        role = classify_node(n)
        buckets.setdefault(role, []).append(
            {
                "id": n["id"],
                "text": n.get("text", "")[:80],
                "type": n.get("type"),
                "has_canvasMargin": n.get("canvasMargin") is not None,
                "has_canvas2anki": n.get("canvas2anki") is not None,
            }
        )

    # 推测 root：x 最小、type=text、无入边、无 canvasMargin、且不在任何 role 里是内容类
    edges = canvas.get("edges", [])
    incoming_ids = {e.get("toNode") for e in edges}
    root_candidates = [
        n
        for n in canvas.get("nodes", [])
        if n.get("type") == "text"
        and n["id"] not in incoming_ids
        and n.get("canvasMargin") is None
        and n.get("canvas2anki") is None
        and not has_bare_dash(n.get("text", ""))
    ]
    if root_candidates:
        root = min(root_candidates, key=lambda n: n.get("x", 0))
        buckets["root"] = [{"id": root["id"], "text": root.get("text", "")[:80]}]
    else:
        buckets["root"] = []
    return buckets


# ══════════════════════════════════════════════════════════════════════════
# ── layout ────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

COL_X = {0: 0, 1: 380, 2: 760, 3: 1100}
COL_W = {0: 220, 1: 200, 2: 280, 3: 300}
ANKI_COL_X = 1460  # 预留给 canvas-make-cards

NODE_H_NONLEAF = 55
NODE_H_LEAF_MIN = 55
GAP_NODE = 20
GAP_BRANCH = 60


def _estimate_leaf_height(text: str) -> int:
    """按文本长度估叶子高度。"""
    n = len(text)
    if n > 200:
        return 180
    if n > 120:
        return 140
    if n > 60:
        return 100
    if n > 30:
        return 80
    return NODE_H_LEAF_MIN


def assign_coords(
    tree: list[dict],
    root_id: str | None,
    node_map: dict,
) -> tuple[dict, list[dict]]:
    """
    递归布局骨架。
    返回 (coords_map, new_edges_list)。
    coords_map: {node_id: {"x","y","width","height"}}
    new_edges_list: 新生成的骨架 edges（不含 anki 相关 edge）
    """
    coords: dict[str, dict] = {}
    edges: list[dict] = []
    y_cursor = [0]

    def layout(item: dict, depth: int) -> tuple[str, float]:
        """返回 (node_id, y_center)。"""
        children = item.get("children", [])
        nid = item.get("id") or _new_id()
        new_text = item.get("new_text")

        if not children:
            # 叶子
            if nid in node_map:
                text = node_map[nid].get("text", "")
            else:
                text = new_text or ""
            h = _estimate_leaf_height(text)
            x = COL_X.get(depth, COL_X[3])
            w = COL_W.get(depth, COL_W[3])
            y = y_cursor[0]
            coords[nid] = {"x": x, "y": y, "width": w, "height": h}
            y_cursor[0] += h + GAP_NODE
            return nid, y + h / 2
        else:
            # 非叶：先摆子节点
            child_centers = []
            child_ids = []
            for child in children:
                cid, c_center = layout(child, depth + 1)
                child_ids.append(cid)
                child_centers.append(c_center)

            my_center = (child_centers[0] + child_centers[-1]) / 2
            h = NODE_H_NONLEAF
            x = COL_X.get(depth, COL_X[3])
            w = COL_W.get(depth, COL_W[3])
            coords[nid] = {"x": x, "y": my_center - h / 2, "width": w, "height": h}

            # 生成 edge 到子节点
            for cid in child_ids:
                edges.append(
                    {
                        "id": _new_id(),
                        "fromNode": nid,
                        "fromSide": "right",
                        "toNode": cid,
                        "toSide": "left",
                    }
                )

            # 分支间额外间距
            y_cursor[0] += GAP_BRANCH - GAP_NODE
            return nid, my_center

    # 顶层 branch_centers
    branch_centers = []
    for branch in tree:
        bid, b_center = layout(branch, 1)
        branch_centers.append((bid, b_center))

    # root 定位 + 连向各 branch
    if root_id and branch_centers:
        root_center = (branch_centers[0][1] + branch_centers[-1][1]) / 2
        root_h = 56
        coords[root_id] = {
            "x": COL_X[0],
            "y": root_center - root_h / 2,
            "width": COL_W[0],
            "height": root_h,
        }
        for bid, _ in branch_centers:
            edges.append(
                {
                    "id": _new_id(),
                    "fromNode": root_id,
                    "fromSide": "right",
                    "toNode": bid,
                    "toSide": "left",
                }
            )

    return coords, edges


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def place_orphans(orphan_ids: list[str], node_map: dict) -> tuple[dict, dict]:
    """
    把孤儿节点放到左侧 group 内。
    返回 (coords_map, group_node)。
    """
    if not orphan_ids:
        return {}, {}

    x_base = -900
    y_base = 0
    gap = 20
    inner_w = 280
    inner_h = 80

    coords: dict[str, dict] = {}
    cur_y = y_base + 40
    for oid in orphan_ids:
        coords[oid] = {
            "x": x_base + 20,
            "y": cur_y,
            "width": inner_w,
            "height": inner_h,
        }
        cur_y += inner_h + gap

    group = {
        "id": _new_id(),
        "type": "group",
        "label": "孤儿节点（不参与骨架）",
        "x": x_base,
        "y": y_base,
        "width": inner_w + 40,
        "height": (cur_y - y_base) + 20,
    }
    return coords, group


def sync_anki_y(
    anki_ids: set[str],
    skeleton_coords: dict,
    node_map: dict,
    edges_original: list[dict],
) -> dict:
    """
    对每张 Anki 卡片 C：查找源骨架节点 A（fromNode=A, toNode=C），
    若 A 已重排（在 skeleton_coords 里），则设 C.y = A.y_center - C.height/2。
    返回 {anki_id: {"y": ...}} 局部更新字典。
    """
    updates: dict[str, dict] = {}
    for e in edges_original:
        src = e.get("fromNode")
        dst = e.get("toNode")
        if dst in anki_ids and src in skeleton_coords:
            A_coords = skeleton_coords[src]
            C_node = node_map.get(dst)
            if not C_node:
                continue
            C_h = C_node.get("height", 60)
            A_center = A_coords["y"] + A_coords["height"] / 2
            updates[dst] = {"y": A_center - C_h / 2}
    return updates


# ══════════════════════════════════════════════════════════════════════════
# ── validate ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

MUTABLE_FIELDS = {"x", "y", "width", "height", "text"}


def validate_all(
    canvas_before: dict,
    canvas_after: dict,
    root_id: str | None,
    orphan_ids: set[str],
    anki_ids: set[str],
    merged_en_ids: set[str],
) -> list[str]:
    """执行全部 assert，返回 error 消息列表。空列表 = 通过。"""
    errors: list[str] = []

    before_nodes = {n["id"]: n for n in canvas_before.get("nodes", [])}
    after_nodes = {n["id"]: n for n in canvas_after.get("nodes", [])}
    edges_after = canvas_after.get("edges", [])

    # ── Assert 1: 问句必须是陈述的子节点、不做非叶 ─────────────────
    for nid, n in after_nodes.items():
        if n.get("type") != "text":
            continue
        if not has_question(n.get("text", "")):
            continue
        if n.get("canvasMargin") is None:
            continue
        children = find_children(nid, edges_after)
        if children:
            errors.append(f"[Assert 1] 问句节点做了非叶: {nid}")
        parent_id = find_parent(nid, edges_after)
        if parent_id is None:
            if nid not in orphan_ids:
                errors.append(f"[Assert 1] 问句节点无父节点: {nid}")
        else:
            parent = after_nodes.get(parent_id)
            if parent and has_question(parent.get("text", "")):
                errors.append(f"[Assert 1] 问句节点的父节点也是问句: {nid}")

    # ── Assert 2: 非叶节点的"可见标题"≤ 30 字 ──────────────────
    # 节点角色分两类：
    #   A) 新建结构标签节点：无 ---，整段 text 作为标题
    #   B) 精炼节点（text = 核心句\n---\n原文）：只校验 --- 前的核心句部分
    for nid, n in after_nodes.items():
        if n.get("type") != "text":
            continue
        if nid == root_id:
            continue
        children = find_children(nid, edges_after)
        if not children:
            continue
        text = n.get("text", "")
        if has_bare_dash(text):
            # 取 --- 前的部分
            title_part = _BARE_DASH_RE.split(text, maxsplit=1)[0]
        else:
            title_part = text
        stripped = strip_markdown(title_part)
        if len(stripped) > 30:
            errors.append(
                f"[Assert 2] 非叶节点标题超 30 字: {nid} ({len(stripped)}字)"
            )

    # ── Assert 3: 孤儿节点在 group 框内 ─────────────────────────
    groups = [n for n in after_nodes.values() if n.get("type") == "group"]
    for oid in orphan_ids:
        o = after_nodes.get(oid)
        if not o:
            errors.append(f"[Assert 3] 孤儿节点不存在: {oid}")
            continue
        in_group = any(
            g["x"] <= o["x"]
            and o["x"] + o["width"] <= g["x"] + g["width"]
            and g["y"] <= o["y"]
            and o["y"] + o["height"] <= g["y"] + g["height"]
            for g in groups
        )
        if not in_group:
            errors.append(f"[Assert 3] 孤儿节点未在 group 框内: {oid}")

    # ── Assert 4: merged_en_ids ⊆ orphan_ids ───────────────────
    extra = merged_en_ids - orphan_ids
    if extra:
        errors.append(f"[Assert 4] merged_en_ids 中未在 orphan_ids 的 id: {extra}")

    # ── Assert 5a: 非坐标顶层字段原样保留 ───────────────────────
    for nid, before in before_nodes.items():
        after = after_nodes.get(nid)
        if after is None:
            # 允许节点被删？—— 本 skill 不删节点，全部保留或进 group
            errors.append(f"[Assert 5a] 节点丢失: {nid}")
            continue
        all_keys = set(before.keys()) | set(after.keys())
        for k in all_keys:
            if k in MUTABLE_FIELDS:
                continue
            if before.get(k) != after.get(k):
                errors.append(
                    f"[Assert 5a] 字段 '{k}' 被修改: {nid} "
                    f"(before={before.get(k)!r}, after={after.get(k)!r})"
                )

    # ── Assert 5b: Anki 卡片 y 与源骨架对齐 ─────────────────────
    for e in edges_after:
        src = e.get("fromNode")
        dst = e.get("toNode")
        if dst in anki_ids:
            A = after_nodes.get(src)
            C = after_nodes.get(dst)
            if A and C and A.get("type") == "text" and C.get("type") == "text":
                A_center = A["y"] + A.get("height", 0) / 2
                C_center = C["y"] + C.get("height", 0) / 2
                if abs(A_center - C_center) > 10:
                    errors.append(
                        f"[Assert 5b] Anki 卡片 y 与源骨架偏差 >10px: "
                        f"card={dst} (center={C_center}), skeleton={src} (center={A_center})"
                    )

    # ── Assert 5c: 任一端点在 anki_ids 的 edge 原样保留 ─────────
    before_edges = canvas_before.get("edges", [])
    anki_edges_before = [
        e
        for e in before_edges
        if e.get("fromNode") in anki_ids or e.get("toNode") in anki_ids
    ]
    after_edge_set = {
        (e.get("id"), e.get("fromNode"), e.get("toNode")) for e in edges_after
    }
    for e in anki_edges_before:
        key = (e.get("id"), e.get("fromNode"), e.get("toNode"))
        if key not in after_edge_set:
            errors.append(f"[Assert 5c] Anki edge 未原样保留: {key}")

    # ── 额外: 骨架节点不进卡片预留列 ─────────────────────────
    for nid, n in after_nodes.items():
        if nid in anki_ids or nid in orphan_ids:
            continue
        if n.get("type") != "text":
            continue
        if n.get("x") == ANKI_COL_X:
            errors.append(f"[Extra] 骨架节点侵入 Anki 预留列 (x={ANKI_COL_X}): {nid}")

    return errors


# ══════════════════════════════════════════════════════════════════════════
# ── main ──────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════


def apply_refinements(canvas: dict, refinements: dict[str, str]) -> None:
    """就地把精炼核心句插入到节点文本前。对已有裸 --- 的节点跳过。"""
    for n in canvas.get("nodes", []):
        nid = n["id"]
        core = refinements.get(nid)
        if not core:
            continue
        text = n.get("text", "")
        if has_bare_dash(text):
            continue
        stripped_text = strip_markdown(text)
        if strip_markdown(core) == stripped_text:
            continue
        n["text"] = f"{core}\n---\n{text}"


def apply_new_texts(canvas: dict, tree: list[dict]) -> list[str]:
    """
    为 tree 中 id=null 的新节点生成 id 并创建节点，写入 canvas["nodes"]。
    递归修改 tree（就地）：把 id=null 改为新生成的 id。
    返回新生成的 id 列表。
    """
    created: list[str] = []

    def recurse(items: list[dict]) -> None:
        for item in items:
            if item.get("id") is None:
                nid = _new_id()
                item["id"] = nid
                canvas["nodes"].append(
                    {
                        "id": nid,
                        "type": "text",
                        "text": item.get("new_text", ""),
                        "x": 0,
                        "y": 0,
                        "width": 200,
                        "height": 55,
                    }
                )
                created.append(nid)
            recurse(item.get("children", []))

    recurse(tree)
    return created


def collect_skeleton_ids(tree: list[dict], root_id: str | None) -> set[str]:
    """收集骨架树中所有节点 id。"""
    ids: set[str] = set()
    if root_id:
        ids.add(root_id)

    def recurse(items: list[dict]) -> None:
        for item in items:
            if item.get("id"):
                ids.add(item["id"])
            recurse(item.get("children", []))

    recurse(tree)
    return ids


def run_classify_only(canvas_path: str) -> int:
    with open(canvas_path, "r", encoding="utf-8") as f:
        canvas = json.load(f)
    buckets = classify_all(canvas)
    print(json.dumps(buckets, ensure_ascii=False, indent=2))
    return 0


def run_full(canvas_path: str, tree_json_path: str, dry_run: bool) -> int:
    with open(canvas_path, "r", encoding="utf-8") as f:
        canvas_before = json.load(f)
    canvas = copy.deepcopy(canvas_before)

    with open(tree_json_path, "r", encoding="utf-8") as f:
        tree_input = json.load(f)

    # schema 基本校验
    for required in ("tree", "orphan_ids", "anki_ids", "merged_en_ids"):
        if required not in tree_input:
            sys.stderr.write(f"[schema] 缺字段: {required}\n")
            return 1
    root_id = tree_input.get("root_id")
    tree = tree_input["tree"]
    refinements = tree_input.get("refinements", {})
    orphan_ids = set(tree_input["orphan_ids"])
    anki_ids = set(tree_input["anki_ids"])
    merged_en_ids = set(tree_input["merged_en_ids"])

    # Step 1: 应用精炼（插入核心句）
    apply_refinements(canvas, refinements)

    # Step 2: 为新建节点生成 id 并添加到 canvas
    apply_new_texts(canvas, tree)

    # 刷新 node_map
    node_map = {n["id"]: n for n in canvas["nodes"]}

    # Step 3: 布局骨架
    skeleton_coords, skeleton_edges = assign_coords(tree, root_id, node_map)

    # Step 4: 孤儿 group
    orphan_coords, orphan_group = place_orphans(list(orphan_ids), node_map)

    # Step 5: 应用坐标到节点
    for nid, c in skeleton_coords.items():
        if nid in node_map:
            for k in ("x", "y", "width", "height"):
                node_map[nid][k] = c[k]
    for nid, c in orphan_coords.items():
        if nid in node_map:
            for k in ("x", "y", "width", "height"):
                node_map[nid][k] = c[k]

    # Step 6: Anki 卡片 y 跟随骨架
    anki_y_updates = sync_anki_y(
        anki_ids,
        skeleton_coords,
        node_map,
        canvas_before.get("edges", []),
    )
    for nid, u in anki_y_updates.items():
        if nid in node_map:
            node_map[nid]["y"] = u["y"]

    # Step 7: 添加孤儿 group 节点
    if orphan_group:
        canvas["nodes"].append(orphan_group)

    # Step 8: 重建 edges
    skeleton_ids = collect_skeleton_ids(tree, root_id)
    before_edges = canvas_before.get("edges", [])

    # 8a. 保留的 edge：任一端点在 anki_ids
    preserved_edges = [
        copy.deepcopy(e)
        for e in before_edges
        if e.get("fromNode") in anki_ids or e.get("toNode") in anki_ids
    ]
    # 8b. 新骨架 edges
    canvas["edges"] = preserved_edges + skeleton_edges

    # Step 9: 验证
    errors = validate_all(
        canvas_before, canvas, root_id, orphan_ids, anki_ids, merged_en_ids
    )
    if errors:
        sys.stderr.write("❌ 验证失败：\n")
        for e in errors:
            sys.stderr.write(f"  {e}\n")
        return 2

    # Step 10: 写盘 or 预览
    if dry_run:
        preview = {
            "nodes_count": len(canvas["nodes"]),
            "edges_count": len(canvas["edges"]),
            "skeleton_nodes": len(skeleton_ids),
            "orphan_nodes": len(orphan_ids),
            "anki_edges_preserved": len(preserved_edges),
            "new_skeleton_edges": len(skeleton_edges),
            "refinements_applied": sum(
                1 for nid, core in refinements.items()
                if nid in node_map and node_map[nid]["text"].startswith(core)
            ),
        }
        print("✓ Dry-run 预览（全部 assert 通过）：")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    with open(canvas_path, "w", encoding="utf-8") as f:
        json.dump(canvas, f, ensure_ascii=False, indent="\t")
    print(f"✓ 已写入 {canvas_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Canvas refine backend")
    ap.add_argument("--canvas", required=True, help="canvas 文件绝对路径")
    ap.add_argument("--classify-only", action="store_true", help="仅输出节点分类 JSON")
    ap.add_argument("--tree-json", help="tree_input.json 路径（非 classify-only 模式必填）")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不写盘")
    args = ap.parse_args()

    if args.classify_only:
        return run_classify_only(args.canvas)

    if not args.tree_json:
        sys.stderr.write("错误：非 --classify-only 模式必须提供 --tree-json\n")
        return 1
    return run_full(args.canvas, args.tree_json, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"❌ 未预期错误: {exc}\n")
        import traceback
        traceback.print_exc()
        sys.exit(3)
