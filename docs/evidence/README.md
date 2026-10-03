# 发布证据账本（B6）

对外可机器查验的能力证据目录。每个 JSON 文件对应一项能力的一次证据快照，
由 `scripts/check_release_evidence.py` 在 CI（repo-gates workflow）校验：
schema 合法、关联 commit 在 main 可达、数据集 sha256 一致、超期标 stale
（默认 WARN，不阻断无关 PR；`--stale-fails` 供定时刷新检查或发布前显式把关）。

## 索引

| 证据 | 能力 | 状态 |
| --- | --- | --- |
| [rp-long-memory-v3-holdout-readiness.json](rp-long-memory-v3-holdout-readiness.json) | RP 长期记忆 | 评测资产就绪（数据集锁定；质量指标待授权的真实评测运行） |

## 边界

- 证据必须写明 `claims_boundary`（证明什么、不证明什么），防止证据本身变成过度宣称。
- 付费真实模型运行的原始请求/输出留在仓库外私有目录（见根目录 `testing-guide.md`）；
  本目录只提交去原文的账本快照与结论。
- 单文件受二进制/体积门约束（`make binary-growth-gate`）。

校验器要求完整40位 commit SHA、带时区时间、非空字符串能力/生成器版本、
非空 proves/does_not_prove 声明和合法指标条目。数据集文件引用只能是仓库内
相对路径，逐文件 SHA-256 冻结内容。B7 CLI/nightly 直接输出此契约，三档产物
保存在 backend/.test-artifacts/ 并由 nightly 上传；主题分支产物仅是工程证据，
不因此取得 main 发布资格，亦不证明模型语义、盲评质量或付费成本。
