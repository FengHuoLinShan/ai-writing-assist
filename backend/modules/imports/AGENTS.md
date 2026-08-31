# AGENTS.md — modules/imports

- 跨模块写正文只走 `modules.writing.facade`；不得直接依赖 Writing 的 model、repository 或 service。
- `ImportRecord` 只保存导入元数据，不保存正文原文；解析结果统一为 `list[dict{title, content}]`，
  新格式必须接入 `parsers.py` 的统一校验与分派。
- 上传仍受 50MB、扩展名、内容签名与安全文件名校验。锁定运行时只验证了 TXT、EPUB、HTML/HTM；
  MOBI/AZW3 虽保留入口和签名校验，但在补齐解析依赖与真实文件测试前不得宣称可用。
- 不让导入记录长期停在 `processing`；成功、失败和空内容都必须落到明确状态。错误可读但不得
  泄露凭据、内部 URL 或原始路径。
- 深度导入的业务 LLM 只能消费持久化的 project execution snapshot，并通过 Project runtime
  恢复当前账户 Key；不得回退环境 Key。Context 与来源审计只走 Evidence facade/snapshot seam。
- 修改解析或上传时至少覆盖真实 happy path、空内容、非法类型/签名、大小限制和分页；任何对外
  宣称支持的文件格式都必须有未 mock 的真实文件验收。
