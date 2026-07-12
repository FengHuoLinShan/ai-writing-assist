# Round 18/20 — Performance Profiling / Memory Leaks / Bundle Size / Images

**Status**: PASS  
**Started**: 2026-07-13 | **Completed**: 2026-07-13  

## Results

| Module | Issues | HIGH | MEDIUM | LOW |
|--------|--------|------|--------|-----|
| Performance | ~8 | 2 | 4 | 2 |
| Memory leaks | ~12 | 2 | 4 | 6 |
| Bundle size | ~8 | 2 | 4 | 2 |
| Images | ~9 | 1 | 5 | 3 |
| **Total** | **~37** | **7** | **17** | **13** |

### Performance Profiling
🔴 HIGH: 零 APM（无 Sentry/Datadog/OpenTelemetry）
🔴 HIGH: 零负载测试（无 locust/k6）
🟡 MEDIUM: 零前端性能审计（无 Lighthouse/web-vitals/bundle-analyzer）
🟡 MEDIUM: 零 Profiler 配置（无 py-spy/scalene）
🟡 MEDIUM: 零 Prometheus/metrics 端点（RAG/LLM 延迟指标仅内存累积）
✅ `_TimingMiddleware` + RAG/LLM/Embedding 各阶段 latency_ms 埋点良好
✅ 专用 LLM probe 基准测试工具 (tools/deepseek_scene_probe/)

### Memory Leaks
🔴 HIGH: `rag/retrieval.py:40` — `_default_embedder` 每次创建 `LLMClient()` 不 close（热路径）
🔴 HIGH: `rag/tuning.py:195` — 同上模式
🟡 MEDIUM: `viewHelper.js:108-110` — `bindActionMenus` 累积 `document.click` 监听器
🟡 MEDIUM: `rag/circuit_breaker.py` `_novel_circuit_breakers` 无界增长
🟡 MEDIUM: `rag/query_expansion.py` `_PROJECT_TERMS_CACHE` 无界
✅ 4 处正确 try/finally close、7 处 JS 正确清理（Observer/revokeObjectURL/clearInterval）

### Bundle Size
🔴 HIGH: CSS 未被 Vite 处理（`<link>` 方式而非 import → 146KB 原样传输，零压缩）
🔴 HIGH: 11 个视图入口点全量加载（无路由级别懒加载）
🟡 MEDIUM: 无 `sideEffects:false`、无 `manualChunks`、无 bundle 分析插件
🟡 MEDIUM: 1494 个冗余 `@pytest.mark.asyncio`（纯死代码）
✅ 0 个生产依赖（全 devDeps）、0 图标库、系统字体零下载

### Image/Assets
🔴 HIGH: favicon 为空 SVG + 缺 apple-touch-icon/manifest/Windows tile
🟡 MEDIUM: 3 个原型 PNG（共 ~1.16MB）未压缩且可能未引用
🟡 MEDIUM: 无构建时图片优化（无 imagemin/sharp/SVGO）
🟡 MEDIUM: CSS 无 `font-display` 策略
✅ 文档 SVG 由 Mermaid 生成（4 文件 ~102KB，无需优化）
