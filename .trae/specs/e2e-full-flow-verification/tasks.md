# Tasks

## 第一轮：P1 核心 CRUD 缺失流程（无外部依赖）

- [x] Task 1: 补齐 World 模块缺失流程 (2.7, 2.9, 2.10, 2.14)
  - [x] 1.1: test_02_world.py — 新增 `test_accept_candidate_creates_entity` (2.7 确认候选为实体)
  - [x] 1.2: test_02_world.py — 新增 `test_ignore_candidate` (2.9 忽略候选)
  - [x] 1.3: test_02_world.py — 新增 `test_entity_extraction_task_submits_and_polls` (2.10 实体抽取任务，mock LLM)
  - [x] 1.4: test_02_world.py — 新增 `test_related_entity_graph` (2.14 相关实体图)

- [x] Task 2: 补齐 Geo 模块缺失流程 (3.3, 3.10, 3.11, 3.13, 3.14)
  - [x] 2.1: test_04_geo.py — 新增 `test_get_location_detail` (3.3 地点详情)
  - [x] 2.2: test_04_geo.py — 新增 `test_travel_constraints` (3.10 通行约束查询)
  - [x] 2.3: test_04_geo.py — 新增 `test_calculate_routing` (3.11 路径计算)
  - [x] 2.4: test_04_geo.py — 新增 `test_location_factions` (3.13 地点势力)
  - [x] 2.5: test_04_geo.py — 新增 `test_location_characters` (3.14 地点人物)

- [x] Task 3: 补齐 Character 模块缺失流程 (4.6, 4.7, 4.8, 4.9, 4.10, 4.12)
  - [x] 3.1: test_03_character.py — 新增 `test_list_knowledge` (4.6 知识列表)
  - [x] 3.2: test_03_character.py — 新增 `test_add_knowledge` (4.7 添加知识)
  - [x] 3.3: test_03_character.py — 新增 `test_update_knowledge` (4.8 编辑知识)
  - [x] 3.4: test_03_character.py — 新增 `test_delete_knowledge` (4.9 删除知识)
  - [x] 3.5: test_03_character.py — 新增 `test_single_character_extract_task` (4.10 单人物抽取，mock LLM)
  - [x] 3.6: test_03_character.py — 新增 `test_apply_ai_suggestions` (4.12 应用 AI 建议)

- [x] Task 4: 补齐 Memory 模块缺失流程 (5.2, 5.3, 5.4)
  - [x] 4.1: test_06_memory.py — 新增 `test_list_pending_proposals` (5.2 待处理提案列表)
  - [x] 4.2: test_06_memory.py — 新增 `test_confirm_proposal` (5.3 确认提案)
  - [x] 4.3: test_06_memory.py — 新增 `test_reject_proposal` (5.4 拒绝提案)

- [x] Task 5: 补齐 Review + Writing 缺失流程 (10.1, 10.3, 11.2, 11.4)
  - [x] 5.1: test_10_review.py — 新增 `test_run_review` (10.1 运行复查)
  - [x] 5.2: test_10_review.py — 新增 `test_get_review_detail` (10.3 复查报告详情)
  - [x] 5.3: test_11_writing.py — 新增 `test_get_chapter_draft_with_outline` (11.2 获取草稿+章节卡)
  - [x] 5.4: test_11_writing.py — 新增 `test_save_and_analyze` (11.4 保存并分析，mock LLM)

## 第二轮：P2 补充流程（低优先级，部分依赖 LLM mock）

- [x] Task 6: 补齐 Project + Outline + Timeline 补充流程
  - [x] 6.1: test_01_import_flow.py — 新增 `test_update_project` (1.3 编辑项目)
  - [x] 6.2: test_05_timeline.py — 新增 `test_deprecate_event` (6.4 废弃事件)
  - [x] 6.3: test_07_outline.py — 新增 `test_get_chapter_card_detail` (7.7 章节卡详情)
  - [x] 6.4: test_07_outline.py — 新增 `test_get_chapter_by_index` (7.8 按索引查章节卡)
  - [x] 6.5: test_07_outline.py — 新增 `test_confirm_chapter_card` (7.10 确认章节卡)
  - [x] 6.6: test_07_outline.py — 新增 `test_foreshadowing_crud` (7.12/7.13 伏笔)
  - [x] 6.7: test_07_outline.py — 新增 `test_reveal_plan_crud` (7.14/7.15 揭示计划)

- [x] Task 7: 补齐 Geo 补充流程 + 深度导入
  - [x] 7.1: test_04_geo.py — 新增 `test_update_location` (3.5 更新地点)
  - [x] 7.2: test_04_geo.py — 新增 `test_history_context` (3.12 历史上下文)
  - [x] 7.3: test_11_writing.py — 新增 `test_update_draft_status` (11.5 更新草稿状态)
  - [ ] 7.4: test_01_import_flow.py — 新增 `test_deep_import_pipeline` (12.3 深度导入，mock LLM) — 跳过：需要真实 LLM

## 第三轮：异步任务 + 生成中心（依赖 LLM mock）

- [x] Task 8: 异步任务 + 生成中心
  - [x] 8.1: test_07_outline.py — 新增 `test_chapter_card_extraction_task` (7.11 从正文提取章节卡)
  - [x] 8.2: test_07_outline.py — 新增 `test_plot_structure_generate_task` (7.16 剧情结构生成)
  - [ ] 8.3: test_08_rag.py — 新增 `test_rebuild_index` (8.4 重建索引) — 跳过：需要大量数据准备
  - [x] 8.4: test_03_character.py — 新增 `test_extract_all_characters` (4.11 全部人物抽取)

## 修复任务（测试中发现的 bug）

- [x] Task 9: 修复测试中发现的 API bug
  - [x] 9.1: MemoryUpdateProposal.decided_at 缺少 timezone — 已修复
  - [x] 9.2: ChapterCardResponse.arc_id UUID→str 转换缺失 — 已修复
  - [x] 9.3: RevealPlan.target_id ORM 类型不匹配 (String→UUID) — 已修复
  - [x] 9.4: 全部 E2E 测试通过（136 passed, 0 failures）

# Task Dependencies

- Task 2 depends on seed_data 中已有 location 数据（已满足）
- Task 3 depends on Task 1（character extract 需要 world entity 数据）
- Task 4 depends on seed_data 中已有 memory 数据（需扩展 seed_data）
- Task 5 depends on Task 4（review 可能需要 memory 数据）
- Task 6~8 可并行执行
- Task 9 依赖 Task 1~8 的测试结果
