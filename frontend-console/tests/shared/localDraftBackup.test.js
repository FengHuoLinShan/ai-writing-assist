import { describe, expect, it, vi } from "vitest"
import { clearLocalDraftBackup, readLocalDraftBackup, writeLocalDraftBackup } from "../../vue/shared/localDraftBackup.js"

function createStorage() {
  const data = new Map()
  return {
    getItem: vi.fn(key => data.get(key) ?? null),
    setItem: vi.fn((key, value) => data.set(key, String(value))),
    removeItem: vi.fn(key => data.delete(key)),
  }
}

const scope = { accountId: "account-a", projectId: "project-a", objectId: "object-a", section: "basic" }

describe("localDraftBackup", () => {
  it("按账户、作品、对象和编辑区隔离，并保存服务器基线", () => {
    const storage = createStorage()
    const saved = writeLocalDraftBackup(storage, scope, "version-1", { name: "新名字" })
    expect(saved.ok).toBe(true)

    const loaded = readLocalDraftBackup(storage, scope)
    expect(loaded).toMatchObject({ ok: true, draft: { base_version: "version-1", payload: { name: "新名字" } } })
    expect(readLocalDraftBackup(storage, { ...scope, accountId: "account-b" }).draft).toBeNull()
    expect(readLocalDraftBackup(storage, { ...scope, projectId: "project-b" }).draft).toBeNull()
    expect(readLocalDraftBackup(storage, { ...scope, objectId: "object-b" }).draft).toBeNull()
  })

  it("清理只删除仍与当前副本完全相同的快照", () => {
    const storage = createStorage()
    const oldDraft = writeLocalDraftBackup(storage, scope, "version-1", { name: "旧草稿" }).draft
    const newDraft = writeLocalDraftBackup(storage, scope, "version-1", { name: "较新草稿" }).draft

    expect(clearLocalDraftBackup(storage, oldDraft)).toMatchObject({ ok: true, changed: true })
    expect(readLocalDraftBackup(storage, scope).draft.payload.name).toBe("较新草稿")
    expect(clearLocalDraftBackup(storage, newDraft)).toMatchObject({ ok: true, removed: true })
    expect(readLocalDraftBackup(storage, scope).draft).toBeNull()
  })

  it("存储不可用时返回失败，不伪报成功", () => {
    expect(writeLocalDraftBackup(null, scope, null, { name: "草稿" })).toMatchObject({ ok: false, reason: "storage_unavailable" })
    expect(readLocalDraftBackup(null, scope)).toMatchObject({ ok: false, reason: "storage_unavailable" })
  })

  it("损坏的本地 JSON 不会自动覆盖或清除", () => {
    const storage = createStorage()
    const key = "author-workspace-draft:v1:account-a:project-a:object-a:basic"
    storage.setItem(key, "not-json")

    expect(readLocalDraftBackup(storage, scope)).toMatchObject({ ok: false, reason: "read_failed" })
    expect(storage.getItem(key)).toBe("not-json")
  })
})
