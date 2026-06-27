/**
 * API 缓存失效逻辑测试 — 回归
 *
 * 背景: 回收站(recycle-bin)列表是 GET 缓存。恢复(/projects/{id}/restore)、
 * 永久删除(/projects/{id}/permanent)是写操作,必须失效同一集合(/projects)的所有列表缓存,
 * 否则 30s TTL 内重开回收站显示已删除的旧项目,重复删除报"资源不存在"。
 *
 * 旧实现按 "base 或 base 父路径的字符串 include" 匹配,/{id}/restore 的父路径是
 * /projects/{id},不含 recycle-bin key,导致遗漏。新实现按集合根(第一路径段)失效。
 *
 * api.js 用 window.api 导出,内部 _invalidateRelatedCache/_apiCache 不可 import,
 * 故此处镜像其失效语义并断言行为(与 state-preservation 测试同一模式)。
 */

import { describe, it, expect, beforeEach } from "vitest"

// ---- 镜像 api.js 的失效实现 ----
const _apiCache = new Map()

function _invalidateRelatedCache(path) {
  const base = path.split("?")[0]
  const collectionRoot = "/" + base.split("/").filter(Boolean)[0]
  for (const key of _apiCache.keys()) {
    const keyPath = key.slice(key.indexOf(":") + 1)
    if (keyPath === collectionRoot || keyPath.startsWith(collectionRoot + "/") || keyPath.startsWith(collectionRoot + "?")) {
      _apiCache.delete(key)
    }
  }
}

function seedCache() {
  _apiCache.set("GET:/projects?skip=0&limit=20", { data: [], time: Date.now() })
  _apiCache.set("GET:/projects/recycle-bin?skip=0&limit=20", { data: [], time: Date.now() })
  _apiCache.set("GET:/projects/p1", { data: {}, time: Date.now() })
  _apiCache.set("GET:/world/entities?novel_id=p1", { data: [], time: Date.now() })
}

beforeEach(() => {
  _apiCache.clear()
  seedCache()
})

describe("_invalidateRelatedCache — 集合根失效", () => {
  it("软删除 DELETE /projects/{id} 失效 recycle-bin 与列表缓存", () => {
    _invalidateRelatedCache("/projects/p1")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
    expect(_apiCache.has("GET:/projects?skip=0&limit=20")).toBe(false)
  })

  it("恢复 POST /projects/{id}/restore 失效 recycle-bin 缓存(回归)", () => {
    _invalidateRelatedCache("/projects/p1/restore")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
    expect(_apiCache.has("GET:/projects?skip=0&limit=20")).toBe(false)
  })

  it("永久删除 DELETE /projects/{id}/permanent 失效 recycle-bin 缓存(回归)", () => {
    _invalidateRelatedCache("/projects/p1/permanent")
    expect(_apiCache.has("GET:/projects/recycle-bin?skip=0&limit=20")).toBe(false)
  })

  it("不跨集合误失效: 改 /projects 不影响 /world 缓存", () => {
    _invalidateRelatedCache("/projects/p1/permanent")
    expect(_apiCache.has("GET:/world/entities?novel_id=p1")).toBe(true)
  })
})
