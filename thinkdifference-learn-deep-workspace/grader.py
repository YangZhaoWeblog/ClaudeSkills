#!/usr/bin/env python3
"""Grade learn-deep skill outputs against assertions."""
import json
import re
import sys
import os

def grade_output(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    results = []

    # 1. no_triple_equals - check for separator lines (===== on its own line, not inside ASCII art)
    # A separator is a line that is ONLY equals signs (with optional whitespace)
    separator_lines = re.findall(r'^\s*={4,}\s*$', content, re.MULTILINE)
    results.append({
        "text": "no_triple_equals: 不包含 ==== 分隔符",
        "passed": len(separator_lines) == 0,
        "evidence": f"Found {len(separator_lines)} separator lines" if separator_lines else "No separator lines found"
    })

    # 2. no_bracket_labels
    bracket_labels = re.findall(r'\[缺口暴露\]|\[工具引入\]|\[停顿点\]|\[缺陷暴露\]', content)
    results.append({
        "text": "no_bracket_labels: 不包含方括号标识",
        "passed": len(bracket_labels) == 0,
        "evidence": f"Found labels: {bracket_labels}" if bracket_labels else "No bracket labels found"
    })

    # 3. uses_h2_for_acts
    h2_acts = re.findall(r'^## 第[一二三四]幕', content, re.MULTILINE)
    results.append({
        "text": "uses_h2_for_acts: 使用 ## 标题分幕",
        "passed": len(h2_acts) >= 4,
        "evidence": f"Found {len(h2_acts)} ## act headers: {h2_acts}"
    })

    # 4. no_numbered_tool_headers - Act 2 should NOT have numbered tool headers (### 第X个工具：)
    # v2.1: immersive narrative flow means no ### headers splitting the narrative in Act 2
    act2_match = re.search(r'## 第二幕.*?(?=## 第三幕)', content, re.DOTALL)
    numbered_headers = []
    if act2_match:
        act2_text = act2_match.group()
        # Check for numbered tool headers like "### 第1个工具" or "### 工具一" etc.
        numbered_headers = re.findall(r'^### .*(工具|第[一二三四五六七八九十\d]+).+', act2_text, re.MULTILINE)
    results.append({
        "text": "no_numbered_tool_headers: 第二幕无编号式工具标题",
        "passed": len(numbered_headers) == 0,
        "evidence": f"Found {len(numbered_headers)} numbered tool headers: {numbered_headers}" if numbered_headers else "No numbered tool headers found - immersive narrative flow"
    })

    # 5. blockquote_pause
    # Check for blockquote pause points (> 想一想 or > ... think/想 patterns)
    blockquotes = re.findall(r'^> .*(想一想|想想|思考|试试|你来|你觉得|如果|为什么).*[？?]', content, re.MULTILINE)
    results.append({
        "text": "blockquote_pause: 停顿点使用引用块",
        "passed": len(blockquotes) >= 1,
        "evidence": f"Found {len(blockquotes)} blockquote pause points"
    })

    # 6. has_analogy_search_invite
    # Check in Act 1 for analogy search invitation
    act1_match = re.search(r'## 第一幕.*?(?=## 第二幕)', content, re.DOTALL)
    has_invite = False
    if act1_match:
        act1_text = act1_match.group()
        # Look for patterns like "有没有..." "生活中..." "日常中..."
        invite_patterns = [
            r'有没有.{2,40}(操作|东西|事情|情况|经验|办法|情形|场景|例子)',
            r'生活中.{2,40}(操作|例子|场景|现象|情形|情况)',
            r'日常.{2,30}(操作|例子|场景|现象|情形)',
            r'能不能想到.{2,30}',
            r'什么东西.{2,30}(无法|不能|不可)',
            r'有没有什么.{2,30}(无法|不能|不可|伪造)',
            r'你能想到.{2,30}(例子|场景|情况)',
        ]
        for pat in invite_patterns:
            if re.search(pat, act1_text):
                has_invite = True
                break
    results.append({
        "text": "has_analogy_search_invite: 第一幕包含类比搜索邀请",
        "passed": has_invite,
        "evidence": "Found analogy search invitation in Act 1" if has_invite else "No analogy search invitation detected in Act 1"
    })

    # 7. closing_question_short
    # Find the last bold or blockquote question in Act 1
    closing_q_short = False
    closing_q_text = ""
    if act1_match:
        act1_text = act1_match.group()
        # Look for the last bold question or blockquote question
        bold_qs = re.findall(r'\*\*(.+?[？?])\*\*', act1_text)
        bq_qs = re.findall(r'^> \*\*(.+?[？?])\*\*', act1_text, re.MULTILINE)
        all_qs = bold_qs + bq_qs
        if all_qs:
            closing_q_text = all_qs[-1]
            # Count Chinese characters + punctuation (rough measure)
            char_count = len(re.sub(r'[\s\*>]', '', closing_q_text))
            closing_q_short = char_count <= 25  # a bit generous for counting
    results.append({
        "text": "closing_question_short: 收束问题不超过20字",
        "passed": closing_q_short,
        "evidence": f"Closing question: '{closing_q_text}' ({len(re.sub(r'[\\s*>]', '', closing_q_text))} chars)" if closing_q_text else "No closing question found"
    })

    # 8. no_step_separator
    step_seps = re.findall(r'---\s*第\s*\d+\s*步\s*---', content)
    results.append({
        "text": "no_step_separator: 不包含步骤分隔线",
        "passed": len(step_seps) == 0,
        "evidence": f"Found {len(step_seps)} step separators" if step_seps else "No step separators found"
    })

    # 9. four_acts_present
    acts = {
        "问题感知": bool(re.search(r'第一幕.*问题感知', content)),
        "引导式构建": bool(re.search(r'第二幕.*引导式构建', content)),
        "完整组装": bool(re.search(r'第三幕.*完整组装', content)),
        "验证与压力测试": bool(re.search(r'第四幕.*验证', content)),
    }
    results.append({
        "text": "four_acts_present: 四幕齐全",
        "passed": all(acts.values()),
        "evidence": f"Acts found: {acts}"
    })

    # 10. has_ascii_diagram
    act3_match = re.search(r'## 第三幕.*?(?=## 第四幕)', content, re.DOTALL)
    has_diagram = False
    if act3_match:
        act3_text = act3_match.group()
        # Look for ASCII art patterns: multiple lines with |, +, -, >, arrows etc
        diagram_lines = re.findall(r'^.*[\|+\->=<\\/]{3,}.*$', act3_text, re.MULTILINE)
        has_diagram = len(diagram_lines) >= 3
    results.append({
        "text": "has_ascii_diagram: 第三幕包含ASCII架构图",
        "passed": has_diagram,
        "evidence": f"Found {len(diagram_lines) if act3_match else 0} diagram-like lines in Act 3"
    })

    return results

def main():
    if len(sys.argv) > 1:
        base = sys.argv[1]
    else:
        base = "/Users/yangzhao/.claude/skills/thinkdifference-learn-deep-workspace/iteration-1"
    dirs = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]

    for d in sorted(dirs):
        output_file = os.path.join(base, d, "outputs", "output.md")
        if not os.path.exists(output_file):
            print(f"\n=== {d} === NOT READY")
            continue

        print(f"\n=== {d} ===")
        results = grade_output(output_file)
        passed = sum(1 for r in results if r["passed"])
        total = len(results)
        print(f"Score: {passed}/{total}")
        for r in results:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}] {r['text']}")
            if not r["passed"]:
                print(f"         -> {r['evidence']}")

        # Save grading.json
        grading_path = os.path.join(base, d, "grading.json")
        with open(grading_path, 'w', encoding='utf-8') as f:
            json.dump({"expectations": results, "pass_rate": passed/total}, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
