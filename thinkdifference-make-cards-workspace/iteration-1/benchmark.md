# Benchmark Results: thinkdifference-make-cards (iteration-1)

## Summary

| Configuration | Mean Pass Rate | Std Dev |
|---|---|---|
| **with_skill** | **100%** | 0.0 |
| without_skill | 22.0% | 10.9% |
| **Delta** | **+78.0%** | |

## Per-Eval Breakdown

| Eval | with_skill | without_skill | Delta |
|---|---|---|---|
| quicksort | 7/7 (100%) | 1/7 (14.3%) | +85.7% |
| paxos-learn-deep | 8/8 (100%) | 3/8 (37.5%) | +62.5% |
| http-cache | 7/7 (100%) | 1/7 (14.3%) | +85.7% |

## Per-Assertion Detail

### quicksort

| Assertion | with_skill | without_skill |
|---|---|---|
| has_breadcrumb_map | PASS | FAIL |
| has_panorama_card | PASS | FAIL |
| has_multi_angle_coverage | PASS | FAIL |
| has_core_supplement_split | PASS | FAIL |
| answers_self_contained | PASS | PASS |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | PASS | FAIL |

### paxos-learn-deep

| Assertion | with_skill | without_skill |
|---|---|---|
| has_breadcrumb_map | PASS | FAIL |
| has_panorama_card | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS |
| has_core_supplement_split | PASS | FAIL |
| answers_self_contained | PASS | PASS |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | PASS | PASS |
| recognizes_four_act_structure | PASS | FAIL |

### http-cache

| Assertion | with_skill | without_skill |
|---|---|---|
| has_breadcrumb_map | PASS | FAIL |
| has_panorama_card | PASS | FAIL |
| has_multi_angle_coverage | PASS | FAIL |
| has_core_supplement_split | PASS | FAIL |
| answers_self_contained | PASS | PASS |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | PASS | FAIL |

## Analyst Observations

1. **answers_self_contained 是非区分性断言**：with_skill 和 without_skill 均 3/3 通过。裸模型也能生成自足的回答。

2. **最强区分性断言**（with_skill 3/3, without_skill 0/3）：
   - has_breadcrumb_map：裸模型从不生成集中的面包屑地图
   - has_core_supplement_split：裸模型不做核心/补充优先级分层
   - no_enumeration_answers：裸模型倾向于列举式回答

3. **paxos without_skill 表现相对最好**（37.5%）：Paxos 本身知名度高，裸模型有足够知识生成多角度和反向推理卡片。但仍缺少结构化输出。

4. **skill 的核心价值**：结构纪律（面包屑地图、核心/补充分层、六角度扫描）+ 制卡质量约束（禁止列举、reverse 角度显式检查）。
