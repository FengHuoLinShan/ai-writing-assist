import { afterEach, describe, expect, it, vi } from "vitest"

import "../../../../apiContracts.js"
import "../../../../api.js"

// api.js 在导入时挂到 window.api；此处直接验证 wire 的 manifest v2 请求体。
afterEach(() => vi.unstubAllGlobals())

describe("previewWorldbookImport wire", () => {
  it("以 manifest v2 提交：显式格式、资料集与提交语义一并进入请求", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 201,
      json: () => Promise.resolve({ suggestion_id: "s1", preview_hash: "a".repeat(64) }),
    }))
    const result = await window.api.world.previewWorldbookImport("p1", {
      source_format: "obsidian",
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "append",
      files: [{ path: "ring/concepts/理法之环.md", content: "正文" }],
    })
    expect(result).toEqual({ suggestion_id: "s1", preview_hash: "a".repeat(64) })
    const [url, init] = globalThis.fetch.mock.calls[0]
    expect(String(url)).toContain("/world/bible/imports/preview")
    expect(String(url)).toContain("novel_id=p1")
    expect(init.method).toBe("POST")
    expect(JSON.parse(init.body)).toEqual({
      schema_version: "world_worldbook_import.v2",
      source_format: "obsidian",
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "append",
      files: [{ path: "ring/concepts/理法之环.md", content: "正文" }],
    })
  })

  it("缺省时回退 auto 格式、continue 语义与完整快照", async () => {
    globalThis.fetch = vi.fn(() => Promise.resolve({
      ok: true,
      status: 201,
      json: () => Promise.resolve({}),
    }))
    await window.api.world.previewWorldbookImport("p1", { files: [{ path: "a.md", content: "" }] })
    const [, init] = globalThis.fetch.mock.calls[0]
    expect(JSON.parse(init.body)).toMatchObject({
      schema_version: "world_worldbook_import.v2",
      source_format: "auto",
      dataset_name: null,
      dataset_intent: "continue",
      commit_mode: "full_snapshot",
    })
  })
})
