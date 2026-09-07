# Evidence Coverage Report — python_click_migration
_生成: 2026-09-06 22:30 JST · OFFLINE ONLY（本轮零游戏接触）· 全部结论可溯源到 durable artifact_
## 1. 我们现在已经知道什么（按矩阵 40 行汇总）
**已饱和/强 evidence（score ≥17）**
- `HOME:SCHEDULE` (18分) — 7 successes, cross-session (0906 run W1-W6 + WINGVAL)- `SCHEDULE:VOCAL` (19分) — 6+ successes across 2 runs; fresh trouble reads ×5 (1%,5%,0%×4)- `SCHEDULE:DECIDE` (17分) — 6 successes across runs (REPLICATED)- `DIALOGUE:SAFE_TEXTBOX` (18分) — 35+ successes across 3 sessions- `DIALOGUE:SKIP_CONTROL` (17分) — 5+ season/story successes; S3-end season dialogue skipped- `RESULT:ADVANCE_CYCLE` (18分) — 6 successes across runs
**中等（13–16）**
- `HOME:FURIKAERI_ENTRY` (15分) — 缺口: single-session/single-context evidence only- `CHOICE:MIDDLE_OPTION` (15分) — 缺口: single-session/single-context evidence only- `SKILL_BOARD:ENTRY_OVERVIEW` (15分) — 缺口: single-session/single-context evidence only- `SKILL_BOARD:WHITE_NODE_BUY` (16分) — 缺口: single-session/single-context evidence only- `SKILL_REPLACEMENT:SLOT_SELECT` (14分) — 缺口: single-session/single-context evidence only- `SKILL_REPLACEMENT:CONFIRM_OK` (14分) — 缺口: single-session/single-context evidence only- `SEASON_TRANSITION:NEXT` (16分) — 缺口: second independent fresh frame with visual_box_norm- `SEASON_TRANSITION:OK_SKIP` (15分) — 缺口: second independent fresh frame with visual_box_norm- `SEASON_TRANSITION:START_PREP` (16分) — 缺口: second independent fresh frame with visual_box_norm- `CROSS:TRANSIENT_TIMING` (13分) — 缺口: no frame-based detector; semantics operator-asserted only
**薄弱/未知（≤12）**
- `HOME:REST` (11分) — 缺口: no visual_box_norm; click point only or ungrounded- `SCHEDULE:AUDITION_ENTRY` (12分) — 缺口: single-session/single-context evidence only- `SCHEDULE:BACK` (11分) — 缺口: single-session/single-context evidence only- `SCHEDULE:SUPPORT_SKILL` (6分) — 缺口: business rule not formalized; fail-closed- `DIALOGUE:AFSOUSHI_X4` (7分) — 缺口: no visual_box_norm; click point only or ungrounded- `CHOICE:GOMEN_OPTION` (11分) — 缺口: business rule not formalized; fail-closed- `CHOICE:ANY` (0分) — 缺口: business rule not formalized; fail-closed- `AUDITION_SELECTION:CANDIDATE_SELECT` (12分) — 缺口: single-session/single-context evidence only- `AUDITION_SELECTION:DECIDE` (12分) — 缺口: single-session/single-context evidence only- `AUDITION_BATTLE:AUTO_TOGGLE` (10分) — 缺口: single-session/single-context evidence only- `AUDITION_BATTLE:SPEED_DISPLAY` (7分) — 缺口: no visual_box_norm; click point only or ungrounded- `AUDITION_BATTLE:PAUSE_RESUME` (8分) — 缺口: single-session/single-context evidence only- `AUDITION_BATTLE:ADVICE_OR_CARD` (2分) — 缺口: business rule not formalized; fail-closed- `RESULT:PASS_FAIL_DETECTOR` (5分) — 缺口: business rule not formalized; fail-closed- `SKILL_BOARD:NO_CLICK` (12分) — 缺口: no frame-based detector; semantics operator-asserted only- `SKILL_BOARD:ZOOM_CONTROLS` (12分) — 缺口: single-session/single-context evidence only- `SKILL_BOARD:STOP_RULE` (11分) — 缺口: single-session/single-context evidence only- `SKILL_REPLACEMENT:LIMIT_4_DETECTOR` (8分) — 缺口: no frame-based detector; semantics operator-asserted only- `ENDING:ADVANCE_CYCLE` (9分) — 缺口: second independent fresh frame with visual_box_norm- `ENDING:BIRTH_OK` (10分) — 缺口: second independent fresh frame with visual_box_norm- `ENDING:IDENTITY_RECORD` (9分) — 缺口: second independent fresh frame with visual_box_norm- `ENDING:GIVE_UP` (11分) — 缺口: business rule not formalized; fail-closed- `CROSS:VIEWPORT_DPR` (8分) — 缺口: no visual_box_norm; click point only or ungrounded- `CROSS:FRAME_STATE_DETECTOR` (4分) — 缺口: no frame-based detector; semantics operator-asserted only
## 2. READY_CONTROLS（shadow-test 级，非 production 授权）

满足 ready_rule（total≥15 且 visual/geometry/detector/authority/replication 全≥2）的 control：

| Control | Total | 仍缺 |
|---|---|---|
| HOME:SCHEDULE | 18 | second independent fresh frame with visual_box_norm |
| SCHEDULE:VOCAL | 19 | second independent fresh frame with visual_box_norm |
| SCHEDULE:DECIDE | 17 | second independent fresh frame with visual_box_norm |
| CHOICE:MIDDLE_OPTION | 15 | single-session/single-context evidence only |
| RESULT:ADVANCE_CYCLE | 18 | no frame-based detector; semantics operator-asserted only |
| SEASON_TRANSITION:NEXT | 16 | second independent fresh frame with visual_box_norm |
| SEASON_TRANSITION:START_PREP | 16 | second independent fresh frame with visual_box_norm |

严格 PYTHON_READY 仍为 **0**：migration_status 的稳定多帧独立 visual_box 复制规则没有任何 control 达成。
最接近的是 weekly 循环组（SCHEDULE/VOCAL/DECIDE/RESULT）——只差第二帧独立 box。

## 3. MOST_EXPENSIVE_GAPS（最贵的缺口）

1. **AUDITION_BATTLE 状态检测**：INPUT_READY vs ANIMATION 无帧锚定；AUTO 4 次成功全部单 run；battle 帧 0 张 durable。TE 路线的硬阻塞。
2. **RESULT PASS/FAIL 显式判定器**：两把 run 都没拿到 explicit semifinal/final WIN 读数（0905 UNKNOWN + 0906 根本没进 WING 决赛）；没有它 TE 判定无法 commit。
3. **帧级 room/state detector**：现在靠 page-label；Python 执行器没有独立状态通道（STATE_DETECTOR_BLOCKERS 首条）。
4. **ENDING + SEASON_TRANSITION durable 帧缺失**：sess_a87 里有完整 结算/フェスアイドル誕生 帧（call_554–637）但未恢复，transcript 随时可能像旧 session 一样被轮转。
5. **viewport/DPR 泛化**：只有 MAC_CURRENT_V1@1280x720；一切换平台/窗口全部重教。
6. **SKILL_BOARD 坐标尺度漂移**：0.9/1.1 display scale 使 full-screenshot 估计系统性偏移（session 内反复 empty-space miss）。

## 4. TOP_NEXT_LIVE_TARGETS（ROI 前 10，公式 gain×occurrence÷risk）

| # | Target | ROI | 为什么 |
|---|---|---|---|
| T01 | RESULT:ADVANCE_CYCLE second-frame visual box | 20.0 | every week; completes REPLICATED→box rule; zero risk (already authorized cycle) |
| T02 | SCHEDULE:VOCAL fresh visual box + trouble-rate read | 20.0 | every week; 5th-6th fresh gate read strengthens VOCAL gate evidence |
| T03 | SCHEDULE:DECIDE second-frame visual box | 20.0 | every week |
| T06 | 3-choice third-context replication (geometry re-read) | 16.0 | S1/S2 events natural; validates live_csm_029 vbox across context |
| T09 | SEASON_TRANSITION rank screen + end dialogue frame recovery→re-shoot (S1 end) | 16.0 | S1 end arrives fast; frames durable this time |
| T17 | S2 start prep detection (season-start prep must-fire check) | 16.0 | S2 start was the missed one for skills? S3 was missed; start-prep explicit check each season |
| T04 | HOME:SCHEDULE entry visual box | 15.0 | every week entry |
| T07 | SKILL_BOARD acquisition chain replication #2 (next produce S1 start prep) | 12.5 | certain at every new produce; converts single-session skill evidence to cross-session |
| T05 | DIALOGUE:SAFE_TEXTBOX tap-count + end detection frames | 10.0 | post-lesson dialogue end detector kills 振り返り over-tap hazard |
| T08 | SKILL_REPLACEMENT full transaction replication #2 | 10.0 | likely at S1 start prep (4-slot refill); T2 chain re-validated |

## 5. LOW_VALUE_ALREADY_SATURATED（不值得再专门采集）

- SAFE_TEXTBOX 盲点计数（35+ 成功，仅差一张 box 帧，顺手拍即可，不配独立目标）
- SCHEDULE 入场（7 成功跨 session）
- VOCAL failure-rate gate fresh 读数（5 次独立读数已支持 ≤2% 规则；继续堆读数边际价值低）
- title TOUCH TO START / OPENING SKIP timing（已 timed，cold-start 链 T16 顺手覆盖）
- locked-node 负样本（live_csm_020-023 + 3 张 panel 已是全项目最强负集合）
- 0905 abandon flow（business-blocked，除非 operator 明确授权）

## 6. 使用方式

- `evidence_coverage_matrix.json` — 40 行 × 7 分项 + 11 维描述
- `python_readiness_matrix.json` — shadow-test 队列排序
- `next_live_evidence_priority.json` — TOP_20 ROI；执行仍需显式 live 授权 + budget profile
- 本文件 — 汇总叙事
