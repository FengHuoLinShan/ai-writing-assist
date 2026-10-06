/**
 * api/core.js — api 对象上的顶层函数（健康检查、缓存清除）
 * （AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import { request, withQuery, _clearRequestCache } from "./_shared.js"

// ============================================================
// 健康检查
// ============================================================
export async function healthCheck() {
    try {
      // 健康检查必须绕过 GET 缓存，否则短时间内多次检查会命中同一份缓存。
      await request(withQuery("/health", { _ts: Date.now() }))
      return true
    } catch {
      return false
    }
}

// ============================================================
// 缓存清除（跨模块写操作后需要刷新 GET 缓存）
// ============================================================
export function clearCache() {
    _clearRequestCache()
}
