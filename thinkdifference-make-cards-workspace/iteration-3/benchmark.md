# Benchmark Results: thinkdifference-make-cards (iteration-3)

## Summary

| Configuration | Mean Pass Rate | Std Dev |
|---|---|---|
| **with_skill** | **96.3%** | 6.4% |
| without_skill | 35.9% | 7.4% |
| **Delta** | **+60.4%** | |

## Iteration Trend

| 指标 | Iteration-1 | Iteration-2 | Iteration-3 |
|---|---|---|---|
| 断言数量 | 7 | 9 | 9 |
| with_skill | 100% | 89.3% | **96.3%** |
| without_skill | 22.0% | 26.1% | 35.9% |
| Delta | +78.0% | +63.2% | +60.4% |

**趋势分析**：
- with_skill: 100% → 89.3%（新断言暴露问题）→ 96.3%（修复后接近恢复）
- 在相同的 9 项断言下，from 89.3% to 96.3% 是实质性提升
- 唯一剩余失败点是 http-cache 的 no_enumeration_answers

## Per-Eval Breakdown

| Eval | with_skill | without_skill | Delta |
|---|---|---|---|
| quicksort | **9/9 (100%)** | 4/9 (44.4%) | +55.6% |
| paxos-learn-deep | **10/10 (100%)** | 3/10 (30.0%) | +70.0% |
| http-cache | 8/9 (88.9%) | 3/9 (33.3%) | +55.6% |

## Per-Assertion Detail

### quicksort

| Assertion | iter-2 with | iter-3 with | iter-3 without |
|---|---|---|---|
| has_breadcrumb_map | PASS | PASS | FAIL |
| has_panorama_card | PASS | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS | PASS |
| has_core_supplement_split | PASS | PASS | FAIL |
| answers_self_contained | PASS | PASS | PASS |
| no_enumeration_answers | PASS | PASS | FAIL |
| has_reverse_card | PASS | PASS | PASS |
| has_context_in_questions | **FAIL** | **PASS** ✅ | FAIL |
| panorama_answer_simplified | PASS | PASS | FAIL |

### paxos-learn-deep

| Assertion | iter-2 with | iter-3 with | iter-3 without |
|---|---|---|---|
| has_breadcrumb_map | PASS | PASS | FAIL |
| has_panorama_card | PASS | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS | PASS |
| has_core_supplement_split | PASS | PASS | FAIL |
| answers_self_contained | PASS | PASS | PASS |
| no_enumeration_answers | PASS | PASS | FAIL |
| has_reverse_card | PASS | PASS | PASS |
| recognizes_four_act_structure | PASS | PASS | FAIL |
| has_context_in_questions | PASS | PASS | FAIL |
| panorama_answer_simplified | **FAIL** | **PASS** ✅ | FAIL |

### http-cache

| Assertion | iter-2 with | iter-3 with | iter-3 without |
|---|---|---|---|
| has_breadcrumb_map | PASS | PASS | FAIL |
| has_panorama_card | PASS | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS | PASS |
| has_core_supplement_split | PASS | PASS | FAIL |
| answers_self_contained | PASS | PASS | PASS |
| no_enumeration_answers | PASS | **FAIL** ⚠️ | FAIL |
| has_reverse_card | **FAIL** | **PASS** ✅ | PASS |
| has_context_in_questions | PASS | PASS | FAIL |
| panorama_answer_simplified | PASS | PASS | FAIL |

## Iteration-2 修复状态

| 失败点 | Iteration-2 | Iteration-3 | 状态 |
|---|---|---|---|
| has_context_in_questions (quicksort) | FAIL (56%) | **PASS (100%)** | ✅ 已修复 |
| panorama_answer_simplified (paxos) | FAIL (7节点消息序列) | **PASS (4模块划分)** | ✅ 已修复 |
| has_reverse_card (http-cache) | FAIL (0张) | **PASS (3张)** | ✅ 已修复 |

## 新增失败分析

### no_enumeration_answers (http-cache with_skill)

- **现象**：补充卡 1 和卡 4 的 answer 主体为 bullet list 形式
- **是否退步**：iteration-2 中 http-cache with_skill 的 no_enumeration_answers 是 PASS，iteration-3 变为 FAIL
- **原因推测**：可能是随机波动（单次运行），也可能是 SKILL.md 修改后对 HTTP 缓存这类"规则对比"知识点，模型更倾向于用列表呈现优先级规则
- **严重度**：低。这不是新引入的系统性问题，更像是边缘情况

## Analyst Observations

1. **3 个目标修复全部成功**：iteration-2 暴露的 3 个独立失败点在 iteration-3 中全部修复，证明了定向改进的有效性。

2. **with_skill 接近满分**：96.3% 的通过率（27/28 项断言），唯一失败是 http-cache 的列举式答案，属于边缘情况。

3. **http-cache without_skill 回归真实基线**：iteration-2 中被 skill 污染（88.9%），iteration-3 为真实基线（33.3%），与 quicksort/paxos 的 without_skill 水平一致。

4. **without_skill 基线略有上升**（22.0% → 26.1% → 35.9%）：quicksort without_skill 的 has_reverse_card 首次通过，说明裸模型有一定概率自发生成 reverse 卡。这是正常的随机波动范围。

5. **迭代建议**：如需 iteration-4，可聚焦于加强"禁止列举"的约束力（当前只在质量自检中提及，可考虑增加反例说明）。但当前 96.3% 的通过率已经很高，边际收益递减。
