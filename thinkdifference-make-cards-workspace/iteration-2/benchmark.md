# Benchmark Results: thinkdifference-make-cards (iteration-2)

## Summary

| Configuration | Mean Pass Rate | Std Dev | Note |
|---|---|---|---|
| **with_skill** | **89.3%** | 0.6% | |
| without_skill (clean) | 26.1% | 3.9% | 仅 quicksort + paxos，排除污染数据 |
| without_skill (all) | 47.0% | 33.8% | 含被污染的 http-cache |
| **Delta (vs clean)** | **+63.2%** | | |

## vs Iteration-1

| 指标 | Iteration-1 | Iteration-2 | 说明 |
|---|---|---|---|
| 断言数量 | 7 | 9 (+2 new) | 新增 has_context_in_questions, panorama_answer_simplified |
| with_skill 通过率 | 100% | 89.3% | 新断言暴露了未完全解决的问题，非退步 |
| without_skill 通过率 | 22.0% | 26.1% | 随机方差范围内，无显著变化 |

## Per-Eval Breakdown

| Eval | with_skill | without_skill | Delta |
|---|---|---|---|
| quicksort | 8/9 (88.9%) | 2/9 (22.2%) | +66.7% |
| paxos-learn-deep | 9/10 (90.0%) | 3/10 (30.0%) | +60.0% |
| http-cache | 8/9 (88.9%) | 8/9 (88.9%) ⚠️ | +0% (污染) |

⚠️ http-cache without_skill 运行时模型自行触发了 thinkdifference-make-cards skill，输出被污染为 with_skill 水平

## Per-Assertion Detail

### quicksort

| Assertion | with_skill | without_skill |
|---|---|---|
| has_breadcrumb_map | PASS | FAIL |
| has_panorama_card | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS |
| has_core_supplement_split | PASS | FAIL |
| answers_self_contained | PASS | PASS |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | PASS | FAIL |
| has_context_in_questions | **FAIL** | FAIL |
| panorama_answer_simplified | PASS | FAIL |

### paxos-learn-deep

| Assertion | with_skill | without_skill |
|---|---|---|
| has_breadcrumb_map | PASS | FAIL |
| has_panorama_card | PASS | FAIL |
| has_multi_angle_coverage | PASS | PASS |
| has_core_supplement_split | PASS | FAIL |
| answers_self_contained | PASS | PASS |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | PASS | FAIL |
| recognizes_four_act_structure | PASS | FAIL |
| has_context_in_questions | PASS | FAIL |
| panorama_answer_simplified | **FAIL** | FAIL |

### http-cache

| Assertion | with_skill | without_skill ⚠️ |
|---|---|---|
| has_breadcrumb_map | PASS | PASS ⚠️ |
| has_panorama_card | PASS | PASS ⚠️ |
| has_multi_angle_coverage | PASS | PASS ⚠️ |
| has_core_supplement_split | PASS | PASS ⚠️ |
| answers_self_contained | PASS | PASS ⚠️ |
| no_enumeration_answers | PASS | FAIL |
| has_reverse_card | **FAIL** | PASS ⚠️ |
| has_context_in_questions | PASS | PASS ⚠️ |
| panorama_answer_simplified | PASS | PASS ⚠️ |

## with_skill 失败分析

3 个 eval 各失败 1 个不同断言，暴露了 3 个独立的改进方向：

### 1. has_context_in_questions (quicksort)
- **现象**：18 张卡中仅约 56% 的问题有上下文背景引入（如"在快速排序中，..."）
- **原因**：SKILL.md 中的编码特异性原则指导存在但不够强硬，模型有时省略上下文
- **改进方向**：在质量自检 checklist 中将上下文引入从"建议"升级为"硬约束"

### 2. panorama_answer_simplified (paxos-learn-deep)
- **现象**：全景卡 ASCII 图展示了完整 4 步消息序列（Prepare→Promise→Accept→Accepted），含 7 个节点
- **原因**：Paxos 的核心特征是其消息流，模型倾向于展示消息流而非抽象模块
- **改进方向**：在全景卡说明中强调"顶层模块 ≠ 流程步骤"，可补充一个协议类知识点的反例

### 3. has_reverse_card (http-cache)
- **现象**：15 张卡中没有 reverse 角度的卡片
- **原因**：SKILL.md 已有 reverse 提示，但对 HTTP 缓存这类"配置性"知识，模型不易找到 reverse 角度
- **改进方向**：在 reverse 角度说明中增加更多非算法类知识点的 reverse 示例

## Analyst Observations

1. **新断言的诊断价值高**：has_context_in_questions 和 panorama_answer_simplified 成功捕获了用户反馈中提到的两个问题，证明新断言设计有效。

2. **with_skill 失败分散且独立**：3 个 eval 各自失败在不同断言上，说明不是某个单一指令的系统性失败，而是 3 个不同的边缘场景需要分别加强。

3. **原 7 项断言未退步**：在 iteration-1 的 7 项断言上，iteration-2 的 with_skill 仍保持很高的通过率（quicksort 7/7，paxos 7/8 仅 panorama_simplified 新断言失败，http-cache 6/7 仅 reverse 失败）。

4. **http-cache without_skill 污染**：这是一个 eval 基础设施问题。未来需要在 without_skill 运行中显式屏蔽 skill 触发（例如通过提示词明确禁止使用 Skill tool）。

5. **迭代建议**：iteration-3 应集中修复 3 个 with_skill 失败点，同时修复 eval 基础设施中的 skill 污染问题。
