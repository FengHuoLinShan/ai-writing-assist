# Module: writing / 正文草稿承载模块

## 定位

writing 模块当前不是核心 AI 正文生成模块，而是人工正文草稿和结构化创作成果的承载模块。

## 数据表

- writing_drafts — chapter_index / chapter_card_id / title / content / version_number

## Facade

```python
async def get_draft(db, draft_id) -> WritingDraftContract | None
async def get_latest_draft_for_chapter(db, novel_id, chapter_index) -> WritingDraftContract | None
async def list_chapter_indices(db, novel_id) -> list[int]  # 有草稿的章节索引
```

## API

```
POST /api/writing/drafts                            # 保存/创建草稿（自动递增版本号）
GET  /api/writing/drafts/{id}                       # 获取草稿
PUT  /api/writing/drafts/{id}                       # 更新草稿内容/状态
DELETE /api/writing/drafts/{id}                     # 删除草稿
GET  /api/writing/chapters/{index}/draft            # 按章节索引获取最新草稿
GET  /api/writing/chapters/{index}/versions         # 获取章节版本历史
GET  /api/writing/chapters                          # 列出有草稿的章节索引
```

## 手动工作台

writing 视图扩展为手动工作台（frontend-console/views/writingView.js）：
- 左侧章节树：合并章节卡+草稿索引，状态徽章（草稿/章节卡）
- 中间编辑器：textarea + 保存/上一章/下一章/导出本章
- 右侧细纲面板：当前章节卡详情（核心展开，其余折叠）
- 状态流转：草稿→候选→正史
- 版本历史：弹窗查看所有版本，可恢复到历史版本
- 深度导入流水线：世界对象抽取→人物同步→剧情结构生成
- 章节卡提取：批量调用 LLM 从正文提取章节卡字段
