# 发布证据账本（B6）

对外可机器查验的能力证据目录。每个 JSON 文件对应一项能力的一次证据快照，
由 `scripts/check_release_evidence.py` 在 CI（repo-gates workflow）校验：
schema 合法、关联 commit 在 main 可达、数据集 sha256 一致、超期标 stale。

## 索引

| 证据 | 能力 | 状态 |
| --- | --- | --- |
| [rp-long-memory-v3-holdout-readiness.json](rp-long-memory-v3-holdout-readiness.json) | RP 长期记忆 | 评测资产就绪（数据集锁定；质量指标待授权的真实评测运行） |

## 边界

- 证据必须写明 `claims_boundary`（证明什么、不证明什么），防止证据本身变成过度宣称。
- 付费真实模型运行的原始请求/输出留在仓库外私有目录（见 `backend/docs/testing-guide.md`）；
  本目录只提交去原文的账本快照与结论。
- 单文件受二进制/体积门约束（`make binary-growth-gate`）。
