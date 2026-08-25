/**
 * useEvidenceDrawer 测试 — 抽屉请求门禁与导航（对应原 ragView.test.js 的
 * 抽屉 projectId 门禁 / onLeave abort 用例）。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope } from "vue"
import { useEvidenceDrawer } from "../../../vue/views/rag/useEvidenceDrawer.js"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ragSearchSession, resetRagSearchSession } from "../../../vue/views/rag/ragSearchSession.js"

const sourceHit = {
  kind: "manuscript",
  title: "第一章",
  source_ref: { content_mode: "canonical", chapter_index: 1, version_number: 2 },
}

beforeEach(() => {
  vi.clearAllMocks()
  resetRagSearchSession()
  ragSearchSession.lastSearchPayload = { content_mode: "canonical", visibility: { mode: "author" } }
  setBridgeOverrides({ state: { currentProjectId: "p1", viewStates: {} } })
  globalThis.api.context.readEvidence = vi.fn(async () => ({
    title: "第一章",
    text: "旧塔的铜铃在夜里响起。",
    highlight_start: 3,
    highlight_end: 5,
    source_ref: { chapter_index: 1, version_number: 2 },
    scene_refs: [],
    object_refs: [],
    warnings: [],
  }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("openHit（原文）", () => {
  it("读取原文并高亮片段", async () => {
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    await drawer.openHit(sourceHit)

    expect(drawer.open.value).toBe(true)
    expect(drawer.content.value.type).toBe("chapter")
    expect(drawer.content.value.mark).toBe("铜铃")
    expect(drawer.content.value.before).toBe("旧塔的")
    expect(globalThis.api.context.readEvidence).toHaveBeenCalledWith(
      expect.objectContaining({
        novel_id: "p1",
        content_mode: "canonical",
        source_ref: sourceHit.source_ref,
      }),
      expect.any(Object),
    )
    scope.stop()
  })

  it("项目切换后晚到响应被丢弃", async () => {
    const state = { currentProjectId: "p1", viewStates: {} }
    setBridgeOverrides({ state })
    let resolveRead
    globalThis.api.context.readEvidence = vi.fn(() => new Promise((resolve) => { resolveRead = resolve }))
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    const pending = drawer.openHit(sourceHit)
    state.currentProjectId = "p2"
    resolveRead({ title: "x", text: "y", warnings: [] })
    await pending
    expect(drawer.content.value).toBeNull()
    scope.stop()
  })

  it("scope 销毁后在途请求被 abort（vanilla onLeave 语义）", async () => {
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    const pending = drawer.openHit(sourceHit)
    scope.stop()
    await pending
    // 不抛错且不写入内容即视为清理成功
    expect(drawer.content.value).toBeNull()
  })

  it("读取失败给作者恢复路径且不暴露内部错误", async () => {
    globalThis.api.context.readEvidence = vi.fn(async () => { throw new Error("internal stack detail") })
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    await drawer.openHit(sourceHit)

    expect(drawer.content.value).toEqual({
      type: "error",
      message: "证据读取失败，请关闭后再次打开这条结果。",
    })
    expect(drawer.content.value.message).not.toContain("internal")
    scope.stop()
  })
})

describe("openHit（对象）与追踪", () => {
  it("inspect 对象并保留作者可读内容", async () => {
    globalThis.api.context.inspectEvidence = vi.fn(async () => ({
      item: { name: "旧塔" },
      evidence_count: 3,
      warnings: [],
    }))
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    await drawer.openHit({ kind: "world_object", title: "旧塔", target_ref: { target_type: "world_entity", target_id: "e1" } })

    expect(drawer.content.value.type).toBe("object")
    expect(drawer.content.value.isWorldObject).toBe(true)
    expect(drawer.content.value.item).toEqual({ name: "旧塔" })
    expect(drawer.content.value).not.toHaveProperty("itemJson")
    expect(ragSearchSession.drawerRefs).toHaveLength(1)
    scope.stop()
  })

  it("trace 对象证据", async () => {
    ragSearchSession.drawerRefs = [{ target_type: "world_entity", target_id: "e1", target_name: "旧塔" }]
    globalThis.api.context.traceEvidence = vi.fn(async () => ({
      links: [{ read: { text: "原文片段" }, source_ref: { chapter_index: 2 }, precision: "exact" }],
      warnings: [],
    }))
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    await drawer.traceRef(0)

    expect(drawer.content.value.type).toBe("trace")
    expect(drawer.content.value.title).toContain("旧塔")
    expect(drawer.content.value.links).toHaveLength(1)
    scope.stop()
  })
})

describe("导航动作", () => {
  it("navigateChapterRef 写 viewStates.writing 并跳转写作台", () => {
    const state = { currentProjectId: "p1", viewStates: {} }
    setBridgeOverrides({ state })
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    drawer.navigateChapterRef("3")

    expect(state.viewStates.writing).toMatchObject({
      projectId: "p1",
      currentChapter: 3,
      currentDraftId: null,
      isReadonly: false,
    })
    expect(globalThis.router.navigate).toHaveBeenCalledWith(
      "writing",
      null,
      true,
      expect.any(URLSearchParams),
    )
    scope.stop()
  })

  it("navigateSceneRef 按 target_id 跳转 scene 路由", () => {
    ragSearchSession.drawerRefs = [{ target_type: "outline_scene", target_id: "s9" }]
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    drawer.navigateSceneRef(0)
    expect(globalThis.router.navigate).toHaveBeenCalledWith("scene", "s9")
    scope.stop()
  })

  it("navigateObjectRef 优先用已有名称跳转世界对象", async () => {
    ragSearchSession.drawerRefs = [{ target_type: "world_entity", target_id: "e1", target_name: "旧塔" }]
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    await drawer.navigateObjectRef(0)
    const call = globalThis.router.navigate.mock.calls[0]
    expect(call[0]).toBe("world")
    expect(call[1]).toBe("objects")
    expect(call[3].get("q")).toBe("旧塔")
    scope.stop()
  })
})

describe("close", () => {
  it("关闭抽屉并终止在途请求", async () => {
    const scope = effectScope()
    const drawer = scope.run(() => useEvidenceDrawer())
    const pending = drawer.openHit(sourceHit)
    drawer.close()
    await pending
    expect(drawer.open.value).toBe(false)
    expect(drawer.content.value).toBeNull()
    scope.stop()
  })
})
