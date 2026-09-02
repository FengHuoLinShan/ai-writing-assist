/**
 * 索引维护页展示纯逻辑 — 从 ragView 状态页渲染分支移植。
 */

export const EVIDENCE_HEALTH_LABELS = {
  healthy: "健康",
  degraded: "可以改进",
  insufficient_data: "数据不足",
}

export function percentText(value) {
  return value == null ? "-" : `${Math.round(value * 100)}%`
}

export function runtimeLabel(prewarmState, runtime) {
  if (prewarmState === "running") return "正在连接"
  if (prewarmState === "failed") return "连接失败"
  if (runtime?.healthy) return "已就绪"
  if (runtime?.started) return "准备中"
  return "未连接"
}

export function cacheText(cacheStats = {}) {
  return cacheStats.hits != null ? `${cacheStats.hits}/${cacheStats.misses || 0}` : "-"
}

export function traceDroppedCount(trace) {
  return Object.values(trace?.drop_counts || {})
    .reduce((sum, value) => sum + (Number(value) || 0), 0)
}

export function traceTimeText(trace) {
  return trace?.created_at ? new Date(trace.created_at).toLocaleString("zh-CN") : "-"
}

export function chunkPreview(text) {
  const plain = String(text || "")
  return plain.length > 120 ? `${plain.substring(0, 120)}...` : plain
}
