# Round 16/20 — Python Compat / Docker / CI-CD / Dependency Licensing

**Status**: PASS  
**Started**: 2026-07-13 | **Completed**: 2026-07-13  

## Results

| Module | Issues | CRITICAL | HIGH | MEDIUM | LOW |
|--------|--------|----------|------|--------|-----|
| Python compat | ~3 | 0 | 2 | 0 | 1 |
| Docker | ~12 | 0 | 4 | 5 | 3 |
| CI/CD | ~6 | 3 | 0 | 2 | 1 |
| Dep licensing | ~7 | 0 | 2 | 2 | 3 |
| **Total** | **~28** | **3** | **8** | **9** | **8** |

### Python Compat (≥3.12)
🔴 HIGH: `context_compiler.py:206` — 仅剩的 `datetime.utcnow()` 弃用（65+ 文件已改）
🔴 HIGH: `pyproject.toml:107` — filterwarnings 全局压制 DeprecationWarning
🟡 LOW: 1494 处冗余 `@pytest.mark.asyncio`（asyncio_mode="auto" 下纯死代码）
✅ 旧式 typing 零处、SQLAlchemy 1.x 零处、match/case 正确

### Docker
🔴 HIGH: 后端 + 前端均无 Dockerfile（零容器化部署路径）
🔴 HIGH: `POSTGRES_PASSWORD` 明文硬编码
🔴 HIGH: 无 `.dockerignore`
🟡 MEDIUM: 镜像源硬编码（`docker.m.daocloud.io` 不通用）
🟡 MEDIUM: 健康检查 5s 间隔过激进、无日志驱动、无资源限制
✅ docker-compose.yml 管理 pgvector（卷持久化 OK）

### CI/CD — CRITICAL × 3
🔴 CRITICAL: 零 CI/CD 流水线 — 无 `.github/workflows/`、无自动化质量门禁
🔴 CRITICAL: main 分支未受保护 — 无 PR review 要求、无状态检查
🔴 CRITICAL: 无 Secret 扫描（OpenAI API Keys 高风险）
🟡 MEDIUM: pre-commit 未配置、无 npm lock 审计
✅ 测试架构已合理分层（单元/集成/E2E 标记完善），只差 CI 执行

### Dependency Licensing
🔴 HIGH: EbookLib AGPLv3+ — 强网络 copyleft，需评估替代或咨询法务
🔴 HIGH: `requirements.txt` vs `pyproject.toml` 严重不同步（6 个依赖缺失）
🟡 MEDIUM: 生产依赖全 `>=` 无上限、`python-dateutil` 未使用
🟢 LOW: npm 侧全部 MIT/BSD/Apache（无 GPL）、0 个生产依赖
