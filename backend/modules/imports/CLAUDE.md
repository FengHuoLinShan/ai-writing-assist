# CLAUDE.md — modules/imports

## 模块级禁止事项

- 不在 imports 模块直接访问 `writing/models.py` / `writing/repositories.py` / `writing/services.py`，跨模块写正文草稿只能走 `writing/facade.py`
- 不把导入正文原文存入 `import_records`，导入记录只保存文件名、类型、大小、章节数、状态和错误信息
- 不绕过 `parsers.py` 新增格式解析；所有解析器必须统一返回 `list[dict{title, content}]`
- 不允许白名单外文件类型；当前仅允许 `.txt` / `.epub` / `.html` / `.htm` / `.mobi` / `.azw3`
- 不允许超过 50MB 的上传文件
- 不信任上传文件名；不使用原始路径，必须先做 `os.path.basename`
- 不让 `ImportRecord` 长时间卡在 `processing`；成功、失败、空内容都必须落到明确状态
- 不吞掉解析或写入失败；失败记录要保存可读错误信息，但不泄露敏感配置
- 不在缺少解析器 happy path、空内容、非法类型、分页测试时合并导入逻辑改动
