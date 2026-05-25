# Module: writing / 正文草稿承载模块

## 定位

writing 模块当前不是核心 AI 正文生成模块，而是人工正文草稿和结构化创作成果的承载模块。

## 数据表

- writing_drafts — chapter_index / chapter_card_id / title / content / version_number

## API

```
POST /api/writing/drafts                       # 保存/创建草稿
GET  /api/writing/drafts/{id}                  # 获取草稿
PUT  /api/writing/drafts/{id}                  # 更新草稿
GET  /api/writing/chapters/{index}/draft       # 按章节索引获取草稿
GET  /api/writing/drafts                       # 草稿列表（含导出参数）
```

## 后续扩展

- 根据章节卡生成正文
- 正文局部重写 / 文风润色
- 正文审稿
- 章节正文 RAG 分块
