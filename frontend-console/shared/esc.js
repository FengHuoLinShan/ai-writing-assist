/**
 * HTML 转义函数 — 防止 XSS
 * 将用户/LLM/API 数据安全地插入 innerHTML
 */
function esc(str) {
  if (str === null || str === undefined) return ""
  var s = String(str)
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;")
}
