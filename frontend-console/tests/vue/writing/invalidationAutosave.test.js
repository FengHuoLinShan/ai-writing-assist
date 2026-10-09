import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { createEditorController } from "../../../vue/views/writing/controllers/editorController.js"
import { clearWritingSession } from "../../../vue/views/writing/writingSession.js"

function deferred() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

function invalidationView(overrides = {}) {
  return {
    chapter_index: 1,
    changed: true,
    nothing_to_do: false,
    affected: [
      { consumer: "story_scene_checkpoint", scene_id: "s1", scene_index: 1, reason: "anchored_chapter_edited", basis: "known" },
      { consumer: "story_scene_checkpoint", scene_id: null, scene_index: 2, reason: "conservative_expansion_unregistered", basis: "unknown" },
    ],
    unknown_scope: true,
    receipt_id: "receipt-1",
    invalidated: [{ consumer: "evidence_chapter_index", label: "章节证据索引", detail: "requested_hash=x" }],
    unsupported: [],
    coverage_note: "细粒度依赖登记后可收窄",
    recompute_options: [{ kind: "reload_evidence" }, { kind: "rebuild_derived_state" }, { kind: "regenerate_prose" }],
    diagnostics: { earliest_affected_scene_index: 1 },
    ...overrides,
  }
}

function makeController({ autosaveResult, evolution } = {}) {
  let projectId = "p1"
  const toast = vi.fn()
  const api = {
    writing: {
      getVersionHistory: vi.fn(async () => ({ versions: [{ id: "d1", version_number: 1 }] })),
      get: vi.fn(async () => ({ id: "d1", novel_id: projectId, title: "第一章", content: "原文", version_number: 1, status: "draft" })),
      autosave: vi.fn(async (_id, payload) => (
        autosaveResult ? { id: "d1", version_number: 2, status: "draft", ...autosaveResult } : { id: "d1", ...payload, version_number: 2, status: "draft" }
      )),
      autosaveDraftOnly: vi.fn(async (payload) => ({ id: "d-new", ...payload, version_number: 1, status: "draft" })),
    },
    ...(evolution ? { evolution } : {}),
  }
  const controller = createEditorController({
    api,
    toast,
    confirm: vi.fn(() => true),
    confirmDialog: vi.fn(async () => true),
    getProjectId: () => projectId,
    onChange: vi.fn(),
    onVersionChanged: vi.fn(async () => {}),
  })
  return { controller, api, toast }
}

async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

async function editAndSave(controller, text) {
  document.body.innerHTML = '<textarea id="body"></textarea>'
  const editor = document.getElementById("body")
  controller.attach({ title: null, editor })
  editor.value = text
  editor.dispatchEvent(new Event("input"))
  await controller.autosave()
}

describe("autosave 失效提示接入（P2-C C4）", () => {
  beforeEach(() => {
    localStorage.clear()
    clearWritingSession()
  })
  afterEach(() => vi.restoreAllMocks())

  it("保存成功且响应带 invalidation 时生成作者语言提示", async () => {
    const { controller } = makeController({ autosaveResult: { invalidation: invalidationView() } })
    await controller.loadChapter(1)
    await editAndSave(controller, "新内容")

    const notice = controller.snapshot().invalidationNotice
    expect(notice).not.toBeNull()
    expect(notice.headline).toBe("这次修改让第 1 章起的场景状态需要更新（涉及场景 1、2）。")
    expect(notice.hasUnknownScope).toBe(true)
    expect(notice.receiptId).toBe("receipt-1")
    expect(notice.recomputeOptions).toEqual(["reload_evidence", "rebuild_derived_state", "regenerate_prose"])
    controller.dispose()
  })

  it("响应无 invalidation / nothing_to_do 时零打扰", async () => {
    const plain = makeController()
    await plain.controller.loadChapter(1)
    await editAndSave(plain.controller, "普通保存")
    expect(plain.controller.snapshot().invalidationNotice).toBeNull()
    plain.controller.dispose()

    const quiet = makeController({ autosaveResult: { invalidation: invalidationView({ nothing_to_do: true }) } })
    await quiet.controller.loadChapter(1)
    await editAndSave(quiet.controller, "没有失效的保存")
    expect(quiet.controller.snapshot().invalidationNotice).toBeNull()
    quiet.controller.dispose()
  })

  it("保存失败时不产生提示，也不影响既有错误通道", async () => {
    const { controller, api } = makeController()
    await controller.loadChapter(1)
    document.body.innerHTML = '<textarea id="body"></textarea>'
    const editor = document.getElementById("body")
    controller.attach({ title: null, editor })
    editor.value = "会失败的修改"
    editor.dispatchEvent(new Event("input"))
    api.writing.autosave.mockRejectedValueOnce(new Error("网络暂时不可用"))

    await controller.autosave()

    expect(controller.snapshot().invalidationNotice).toBeNull()
    expect(controller.snapshot().saveError).toBe("网络暂时不可用")
    controller.dispose()
  })

  it("切换章节后旧提示不残留，会话快照也不复活旧提示", async () => {
    let call = 0
    let projectId = "p1"
    const api = {
      writing: {
        getVersionHistory: vi.fn(async () => ({ versions: [{ id: "d1", version_number: 1 }] })),
        get: vi.fn(async () => {
          call += 1
          return { id: `d${call}`, novel_id: projectId, title: `第${call}章`, content: `原文${call}`, version_number: 1, status: "draft" }
        }),
        autosave: vi.fn(async (_id, payload) => ({ id: "d1", ...payload, version_number: 2, status: "draft", invalidation: invalidationView() })),
        autosaveDraftOnly: vi.fn(),
      },
    }
    const controller = createEditorController({
      api,
      toast: vi.fn(),
      confirm: vi.fn(() => true),
      confirmDialog: vi.fn(async () => true),
      getProjectId: () => projectId,
      onChange: vi.fn(),
      onVersionChanged: vi.fn(async () => {}),
    })
    await controller.loadChapter(1)
    await editAndSave(controller, "带失效的保存")
    expect(controller.snapshot().invalidationNotice).not.toBeNull()

    await controller.loadChapter(2)

    expect(controller.snapshot().invalidationNotice).toBeNull()
    controller.dispose()
  })
})

describe("载入章节回读未消解的失效提示（F7）", () => {
  beforeEach(() => {
    localStorage.clear()
    clearWritingSession()
  })
  afterEach(() => vi.restoreAllMocks())

  it("重新载入/切章回来都恢复原影响列表与重算入口", async () => {
    const { controller, api } = makeController({
      evolution: {
        pendingInvalidations: vi.fn(async (_novelId, { chapterIndex }) => (
          chapterIndex === 1
            ? { novel_id: "p1", items: [invalidationView({ receipt_id: "receipt-open" })] }
            : { novel_id: "p1", items: [] }
        )),
      },
    })

    await controller.loadChapter(1)
    await settle()

    const restored = controller.snapshot().invalidationNotice
    expect(restored).not.toBeNull()
    expect(restored.receiptId).toBe("receipt-open")
    expect(restored.headline).toBe("这次修改让第 1 章起的场景状态需要更新（涉及场景 1、2）。")
    expect(restored.recomputeOptions).toEqual(["reload_evidence", "rebuild_derived_state", "regenerate_prose"])
    expect(api.evolution.pendingInvalidations).toHaveBeenCalledWith("p1", { chapterIndex: 1 })

    // 切到没有待重算的一章：不把上一章的提示带过来
    await controller.loadChapter(2)
    await settle()
    expect(controller.snapshot().invalidationNotice).toBeNull()

    // 再回来：仍查得到同一份待重算状态
    await controller.loadChapter(1)
    await settle()
    expect(controller.snapshot().invalidationNotice.receiptId).toBe("receipt-open")
    controller.dispose()
  })

  it("回读失败提示重试：正文照常载入且保持可编辑", async () => {
    const { controller, toast } = makeController({
      evolution: { pendingInvalidations: vi.fn(async () => { throw new Error("网络中断") }) },
    })

    const loaded = await controller.loadChapter(1)
    await settle()

    expect(loaded).toBe(true)
    expect(controller.snapshot().content).toBe("原文")
    expect(controller.snapshot().invalidationNotice).toBeNull()
    expect(controller.snapshot().loadError).toBeNull()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("待重算提示暂未恢复"), "warning")
    expect(toast.mock.calls.flat().join(" ")).not.toContain("网络中断")
    controller.dispose()
  })

  it("服务端返回脏数据时告知尚未恢复，编辑不受影响", async () => {
    const { controller, toast } = makeController({
      evolution: { pendingInvalidations: vi.fn(async () => ({ novel_id: "p1", items: null })) },
    })

    await controller.loadChapter(1)
    await settle()

    expect(controller.snapshot().invalidationNotice).toBeNull()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("待重算提示暂未恢复"), "warning")
    controller.dispose()
  })

  it("在途回读晚于本次保存落地时不覆盖新提示", async () => {
    const gate = deferred()
    const { controller } = makeController({
      autosaveResult: { invalidation: invalidationView({ receipt_id: "receipt-fresh" }) },
      evolution: { pendingInvalidations: vi.fn(() => gate.promise) },
    })

    await controller.loadChapter(1)
    await editAndSave(controller, "之后的修改")
    expect(controller.snapshot().invalidationNotice.receiptId).toBe("receipt-fresh")

    gate.resolve({ novel_id: "p1", items: [invalidationView({ receipt_id: "receipt-stale" })] })
    await settle()

    expect(controller.snapshot().invalidationNotice.receiptId).toBe("receipt-fresh")
    controller.dispose()
  })
})
