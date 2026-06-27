# 大纲与结构管理用户路径 — 真实 LLM 验收记录

**验收日期:** 2026-06-13  
**验收目标:** 验证 AI 生成结构路径使用《诡秘之主 第一部》第 1-3 章真实正文内容，生成剧情线与篇章纲并刷新到 UI。  
**模型/环境:** DeepSeek (`deepseek-v4-flash`)，base_url=https://api.deepseek.com

---

## 1. 数据来源

- 原始文本: `/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt`
- 样本文件: `backend/tests/e2e/samples/lotm_chapters_1_2_3.txt`
- 第 1 章字符数: 2,638
- 第 2 章字符数: 3,397
- 第 3 章字符数: 3,322
- 合计字符数: 9,357

样本通过章节标题正则 `第[一二三四五六七八九十1234567890]+章` 切分，保留前三章完整正文。

---

## 2. 后端 API 真实 LLM 验收

**测试命令:**

```bash
cd backend && pytest tests/e2e/test_outline_generation.py::TestRealOutlineGeneration::test_outline_generate_real_llm_creates_threads_and_arcs -v -s --tb=short --log-cli-level=INFO
```

**输入:**

- 项目: 《诡秘之主 第一部》
- 章节范围: 1-3
- 上下文: 项目信息 + 世界对象（克莱恩·莫雷蒂、罗塞尔·古斯塔夫、廷根市、值夜者等）+ 人物角色 + 第 1-3 章真实正文

**输出结果:**

- `total_threads`: 3
- `total_arcs`: 1
- `existing_threads_count`（首次）: 0
- `existing_arcs_count`（首次）: 0

**生成的剧情线:**

1. 穿越之谜与生存适应 (type=main)
2. 克莱恩之死疑云 (type=hidden)
3. 家庭关系与日常生活 (type=secondary)

**生成的篇章纲:**

1. 绯红之始 (arc_index=1)

**二次生成重复范围警告:**

- 第二次生成相同范围返回 `existing_threads_count=3`、`existing_arcs_count=1`，并在 `warnings` 中提示 "章节 1-3 已有 3 条剧情线、1 个篇章纲"。

---

## 3. 前端 UI 真实 LLM 验收

**测试命令:**

```bash
cd frontend-console && ENABLE_REAL_LLM=1 npx playwright test outline-real-llm.spec.js --reporter=list --timeout=300000
```

**测试路径:**

1. 创建项目《诡秘之主 第一部》。
2. 通过 API 创建第 1-3 章 writing_drafts（使用真实样本内容）。
3. 打开 outlineView → Scene 卡子标签。
4. 点击「AI 生成结构」，设置范围 1-3，确认。
5. 等待 toast「结构生成完成」。
6. 切换到剧情线子标签，断言列表非空。
7. 切换到篇章纲子标签，断言列表非空。
8. 刷新页面，断言数据持久化。

**输出结果:**

- `threads=1`
- `arcs=3`
- UI 成功刷新并持久化。

> 注：前端测试仅通过 writing_drafts 注入正文，未注入世界对象/人物角色上下文，因此生成数量与后端 API 测试存在差异。该差异符合预期，重点验证 UI 端到端路径可用。

---

## 4. 关键代码变更

- `backend/modules/outline/services.py`: `PlotStructureGenerator.generate` 现在会加载指定章节范围的 `writing_drafts` 最新版本，并将章节原文注入 LLM prompt。
- `backend/tests/e2e/seed_data.py`: 新增 `create_writing_drafts`，为测试项目注入第 1-3 章真实正文。
- `backend/tests/e2e/test_outline_generation.py`: 使用真实章节 1-3 范围，记录并断言生成数量与重复范围警告。
- `frontend-console/api.js`: `request` 支持 `options.timeout`；`outline.generate` 使用 180s 超时以容纳 LLM 调用。
- `frontend-console/e2e/outline-real-llm.spec.js`: 新增真实 LLM 前端验收测试。

---

## 5. 结论

- [x] AI 生成结构路径使用数据库中《诡秘之主 第一部》第 1-3 章真实正文内容。
- [x] 未使用 mock LLM 完成最终验收。
- [x] 后端 API 与前端 UI 均成功生成并持久化 plot_threads 与 outline_arcs。
- [x] 重复范围生成返回正确计数并触发警告。
