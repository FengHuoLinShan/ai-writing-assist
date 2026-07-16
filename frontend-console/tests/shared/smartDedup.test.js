import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createSmartDedupManager } from "../../shared/smartDedup.js"
import { resetState, clearDocument, latestModal } from "../helpers.js"

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = '<div id="test-root"></div>'
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

function createManager(overrides = {}) {
  return createSmartDedupManager({
    api,
    router,
    toast,
    modal: { showModalHtml, closeModal },
    esc,
    onRenderActions: () => {},
    getCurrentProjectId: () => "p1",
    ...overrides,
  })
}

async function runScanToDone(result) {
  api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-1" })
  api.tasks.get.mockResolvedValue({
    task_id: "scan-1",
    task_type: "smart_dedup_scan",
    status: "done",
    result,
  })
  const manager = createManager()
  await manager.startScan()
  await flushPromises()
  return manager
}

describe("Smart Dedup Manager", () => {
  it("normalizes suggestions from entity-shaped payload and renders them", async () => {
    await runScanToDone({
      total_assets_scanned: 2,
      suggestions: [{
        action: "alias_only",
        source_entity_id: "duplicate-id",
        source_entity_name: "北港镜修师",
        target_entity_id: "primary-id",
        target_entity_name: "沈澜",
        confidence: 0.91,
        evidence_anchors: { snippet: "bad-shape" },
      }],
    })

    const modal = latestModal()
    expect(modal.title).toBe("智能去重建议")
    expect(modal.body.html).toContain("北港镜修师")
    expect(modal.body.html).toContain("沈澜")
    expect(modal.body.html).toContain("登记为别名")
  })

  it("escapes smart dedup suggestion text", async () => {
    await runScanToDone({
      suggestions: [{
        asset_type: "plot_thread",
        action: "deprecate_duplicate",
        source_asset_id: "<script>alert(1)</script>",
        source_title: "<script>alert(1)</script>",
        target_asset_id: "目标线",
        target_title: "目标线",
        confidence: 0.9,
        reason: "<img src=x>",
        evidence_anchors: [{ snippet: "<b>证据</b>" }],
      }],
    })

    const modal = latestModal()
    expect(modal.body.html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(modal.body.html).toContain("&lt;img src=x&gt;")
    expect(modal.body.html).not.toContain("<script>alert(1)</script>")
  })

  it("applies selected smart dedup suggestions through project API", async () => {
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
    `
    api.projects.applySmartDedup.mockResolvedValue({ applied: 1, skipped: 0 })

    await runScanToDone({
      suggestions: [{
        asset_type: "plot_thread",
        action: "deprecate_duplicate",
        source_asset_id: "s1",
        target_asset_id: "t1",
        source_title: "来源",
      }],
    })

    const modal = latestModal()
    await modal.buttons.find((button) => button.text === "应用选中建议").handler()

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      suggestions: [
        {
          asset_type: "plot_thread",
          action: "deprecate_duplicate",
          source_asset_id: "s1",
          target_asset_id: "t1",
          alias: "来源",
          allow_canonical_merge: false,
          allow_canonical_alias: false,
        },
      ],
    })
    expect(closeModal).toHaveBeenCalled()
    expect(api.clearCache).toHaveBeenCalled()
    expect(router.refresh).toHaveBeenCalled()
  })

  it("cleans task progress, poller, and persisted workflow after applying suggestions", async () => {
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
      id: "p1:smart_dedup_scan:scan-1",
      taskId: "scan-1",
      workflowType: "smart_dedup_scan",
      projectId: "p1",
    }]))
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
    `
    api.projects.applySmartDedup.mockResolvedValue({ applied: 1, skipped: 0 })

    const manager = await runScanToDone({
      suggestions: [{
        asset_type: "world_entity",
        action: "merge",
        source_asset_id: "duplicate-id",
        source_title: "重复对象",
        target_asset_id: "primary-id",
        target_title: "主体对象",
      }],
    })

    const modal = latestModal()
    await modal.buttons.find((button) => button.text === "应用选中建议").handler()

    const state = manager.getState()
    expect(state.taskId).toBeNull()
    expect(state.progress).toBeNull()
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([])
  })

  it("renders smart dedup suggestions with recommended primary controls and paginates the panel", async () => {
    const suggestions = Array.from({ length: 8 }, (_, i) => ({
      asset_type: "world_entity",
      action: i === 0 ? "alias_only" : "merge",
      source_asset_id: `s${i + 1}`,
      source_title: `候选${i + 1}`,
      target_asset_id: `t${i + 1}`,
      target_title: `主体${i + 1}`,
      confidence: 0.9,
      reason: `原因${i + 1}`,
    }))

    await runScanToDone({
      total_assets_scanned: 20,
      suggestion_count: suggestions.length,
      suggestions,
    })

    const firstPageBody = latestModal().body.html
    expect(firstPageBody).toContain("第 1 / 2 页")
    expect(firstPageBody).toContain("候选1")
    expect(firstPageBody).toContain("主体对象")
    expect(firstPageBody).toContain("推荐主体")
    expect(firstPageBody).toContain("登记为别名")
    expect(firstPageBody).not.toContain("候选7")
  })

  it("resets empty smart dedup results and exposes rescan", async () => {
    const manager = await runScanToDone({
      total_assets_scanned: 8,
      suggestion_count: 0,
      suggestions: [],
    })

    const modal = latestModal()
    expect(modal.title).toBe("智能去重")
    expect(modal.body.html).toContain("没有发现可处理的重复资产")
    expect(modal.buttons.map((button) => button.text)).toContain("重新扫描")

    api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-2" })
    api.tasks.get.mockResolvedValue({
      task_id: "scan-2",
      task_type: "smart_dedup_scan",
      status: "running",
    })
    await modal.buttons.find((button) => button.text === "重新扫描").handler()

    expect(api.projects.startSmartDedupScan).toHaveBeenCalledWith("p1", {})
    expect(manager.getState().taskId).toBe("scan-2")
    manager.dispose()
  })

  it("does not select risky alias-derived suggestions by default but allows manual apply", async () => {
    await runScanToDone({
      total_assets_scanned: 20,
      suggestions: [{
        asset_type: "world_entity",
        action: "merge",
        source_asset_id: "shen-lan",
        source_title: "沈澜",
        target_asset_id: "mirror-restorer",
        target_title: "北港镜修师",
        recommended_primary_asset_id: "mirror-restorer",
        recommended_primary_title: "北港镜修师",
        confidence: 0.99,
        match_method: "alias_name_match",
        reason: "别名命中",
      }],
    })

    const modal = latestModal()
    expect(modal.body.html).toContain("高风险别名命中")
    document.body.innerHTML = modal.body.html
    const checkbox = document.querySelector('[data-smart-dedup-index="0"]')
    expect(checkbox.checked).toBe(false)

    await modal.buttons.find((button) => button.text === "应用选中建议").handler()
    expect(api.projects.applySmartDedup).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请选择可应用的建议", "warning")

    checkbox.checked = true
    api.projects.applySmartDedup.mockResolvedValue({ applied: 1, skipped: 0 })
    await modal.buttons.find((button) => button.text === "应用选中建议").handler()

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      suggestions: [expect.objectContaining({
        asset_type: "world_entity",
        action: "merge",
        source_asset_id: "shen-lan",
        target_asset_id: "mirror-restorer",
      })],
    })
  })

  it("does not let stale suggestion DOM selection leak into a new scan result", async () => {
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
    `
    await runScanToDone({
      total_assets_scanned: 19,
      suggestions: [{
        asset_type: "world_entity",
        action: "merge",
        source_asset_id: "shen-lan",
        source_title: "沈澜",
        target_asset_id: "mirror-restorer",
        target_title: "北港镜修师",
        confidence: 0.99,
        match_method: "alias_name_match",
      }],
    })

    const modal = latestModal()
    document.body.innerHTML = modal.body.html
    expect(document.querySelector('[data-smart-dedup-index="0"]').checked).toBe(false)
  })

  it("uses the selected primary object when applying merge and alias suggestions", async () => {
    document.body.innerHTML = `
      <input type="checkbox" data-smart-dedup-index="0" checked />
      <input type="radio" name="smart-dedup-primary-0" value="source" checked />
      <input data-smart-dedup-manual-primary="0" value="" />
      <input type="checkbox" data-smart-dedup-index="1" checked />
      <input type="radio" name="smart-dedup-primary-1" value="manual" checked />
      <input data-smart-dedup-manual-primary="1" value="manual-primary" />
    `
    api.projects.applySmartDedup.mockResolvedValue({ applied: 2, skipped: 0 })

    await runScanToDone({
      suggestions: [
        {
          asset_type: "world_entity",
          action: "merge",
          source_asset_id: "candidate-id",
          source_title: "候选对象",
          target_asset_id: "canonical-id",
          target_title: "正史对象",
        },
        {
          asset_type: "world_entity",
          action: "alias_only",
          source_asset_id: "alias-source",
          source_title: "小名",
          target_asset_id: "alias-target",
          target_title: "主体对象",
        },
      ],
    })

    const modal = latestModal()
    await modal.buttons.find((button) => button.text === "应用选中建议").handler()

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      suggestions: [
        {
          asset_type: "world_entity",
          action: "merge",
          source_asset_id: "canonical-id",
          target_asset_id: "candidate-id",
          alias: "正史对象",
          allow_canonical_merge: false,
          allow_canonical_alias: false,
        },
        {
          asset_type: "world_entity",
          action: "alias_only",
          source_asset_id: "alias-source",
          target_asset_id: "manual-primary",
          alias: "小名",
          allow_canonical_merge: false,
          allow_canonical_alias: false,
        },
      ],
    })
  })

  it("stops polling when the current project changes", async () => {
    vi.useFakeTimers()
    api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-switch" })
    api.tasks.get.mockResolvedValue({
      task_id: "scan-switch",
      task_type: "smart_dedup_scan",
      status: "running",
    })

    let currentProjectId = "p1"
    const manager = createManager({ getCurrentProjectId: () => currentProjectId })
    await manager.startScan()
    expect(manager.getState().taskId).toBe("scan-switch")

    await vi.advanceTimersByTimeAsync(10)
    expect(api.tasks.get).toHaveBeenCalledTimes(1)

    currentProjectId = "p2"
    await vi.advanceTimersByTimeAsync(5000)

    expect(api.tasks.get).toHaveBeenCalledTimes(2)
    expect(manager.getState().taskId).toBeNull()
    manager.dispose()
  })

  it("destroys legacy manual primary pickers when the project changes", () => {
    let currentProjectId = "p1"
    const manager = createManager({ getCurrentProjectId: () => currentProjectId })
    document.body.innerHTML = '<div data-smart-dedup-manual-picker="0"></div>'
    const suggestions = [{
      asset_type: "world_entity",
      action: "merge",
      source_asset_id: "source-1",
      target_asset_id: "target-1",
    }]
    manager._mountManualPrimaryPickers(suggestions)
    const root = document.querySelector("[data-smart-dedup-manual-picker]")
    expect(root.classList.contains("reference-picker")).toBe(true)

    currentProjectId = "p2"
    manager.syncProject("p2")

    expect(root.classList.contains("reference-picker")).toBe(false)
    expect(manager._manualPrimaryPickers).toEqual([])
  })

  it("restores the matching active workflow when projects switch", () => {
    vi.useFakeTimers()
    localStorage.setItem("novel_active_workflows_v1", JSON.stringify([
      {
        id: "p1:smart_dedup_scan:scan-p1",
        taskId: "scan-p1",
        workflowType: "smart_dedup_scan",
        projectId: "p1",
      },
      {
        id: "p2:smart_dedup_scan:scan-p2",
        taskId: "scan-p2",
        workflowType: "smart_dedup_scan",
        projectId: "p2",
      },
    ]))
    api.tasks.get.mockResolvedValue({
      task_type: "smart_dedup_scan",
      status: "running",
    })

    let currentProjectId = "p1"
    const renderActions = vi.fn()
    const manager = createManager({
      getCurrentProjectId: () => currentProjectId,
      onRenderActions: renderActions,
    })

    manager.syncProject("p1")
    expect(manager.getState()).toMatchObject({ taskId: "scan-p1", scanProjectId: "p1" })

    currentProjectId = "p2"
    manager.syncProject("p2")
    expect(manager.getState()).toMatchObject({ taskId: "scan-p2", scanProjectId: "p2" })

    currentProjectId = "p1"
    manager.syncProject("p1")
    expect(manager.getState()).toMatchObject({ taskId: "scan-p1", scanProjectId: "p1" })
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toHaveLength(2)
    expect(renderActions).toHaveBeenCalledTimes(3)
    manager.dispose()
  })

  it("keeps a late scan response bound to its original project", async () => {
    let resolveStart
    api.projects.startSmartDedupScan.mockImplementation(() => new Promise((resolve) => {
      resolveStart = resolve
    }))
    let currentProjectId = "p1"
    const manager = createManager({ getCurrentProjectId: () => currentProjectId })

    const startPromise = manager.startScan()
    currentProjectId = "p2"
    manager.syncProject("p2")
    resolveStart({ task_id: "scan-p1-late" })
    await startPromise

    expect(manager.getState()).toMatchObject({ taskId: null, progress: null, scanProjectId: null })
    expect(api.tasks.get).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalledWith("智能去重扫描已提交", "success")
    expect(JSON.parse(localStorage.getItem("novel_active_workflows_v1"))).toEqual([
      expect.objectContaining({
        taskId: "scan-p1-late",
        workflowType: "smart_dedup_scan",
        projectId: "p1",
      }),
    ])
  })

  it("renders schema v2 groups as a large decision workbench without manual IDs", async () => {
    await runScanToDone(groupResult())

    const modal = latestModal()
    const call = showModal.mock.calls.at(-1)
    expect(modal.title).toBe("智能去重裁决工作台")
    expect(modal.body.html).toContain("重复组队列")
    expect(modal.body.html).toContain("只看差异")
    const rendered = document.createElement("div")
    rendered.innerHTML = modal.body.html
    expect(rendered.querySelector("[data-smart-dedup-diff]").checked).toBe(true)
    expect(modal.body.html).toContain("融合内容并迁移引用")
    expect(modal.body.html).not.toContain("手动主体 ID")
    expect(call[3]).toEqual({ size: "large", protectUnsaved: true })
    expect(showModal.mock.calls.filter(([title]) => title === "智能去重裁决工作台")).toHaveLength(1)
  })

  it("keeps an eligible primary selected when the author switches it", async () => {
    const result = groupResult()
    result.groups[0].eligible_primary_asset_ids = ["a", "b"]
    const manager = await runScanToDone(result)
    document.body.innerHTML = `<div id="modal-body">${latestModal().body.html}</div>`
    const groups = manager._groups(result)
    manager._bindGroupControls(groups)

    const nextPrimary = document.querySelector('[data-smart-dedup-group-primary="a"]')
    nextPrimary.checked = true
    nextPrimary.dispatchEvent(new Event("change"))

    expect(manager._groupDraftFor(groups[0]).primaryId).toBe("a")
    const rendered = document.createElement("div")
    rendered.innerHTML = latestModal().body.html
    expect(rendered.querySelector('[data-smart-dedup-group-primary="a"]').checked).toBe(true)
    expect(rendered.querySelectorAll("[data-smart-dedup-operation]").length).toBe(2)
  })

  it("preserves workbench scroll positions when a checkbox rerenders the modal", async () => {
    const result = groupResult()
    const manager = await runScanToDone(result)
    document.body.innerHTML = `<div id="modal-body">${latestModal().body.html}</div>`
    const modalBody = document.getElementById("modal-body")
    const queue = document.querySelector(".smart-dedup-queue")
    const decision = document.querySelector(".smart-dedup-decision")
    modalBody.scrollTop = 40
    queue.scrollTop = 70
    decision.scrollTop = 190
    const restore = vi.spyOn(manager, "_restoreGroupWorkbenchScroll")
    manager._bindGroupControls(manager._groups(result))

    const checkbox = document.querySelector("[data-smart-dedup-diff]")
    checkbox.checked = false
    checkbox.dispatchEvent(new Event("change"))

    expect(restore).toHaveBeenCalledWith(expect.objectContaining({
      modalBodyTop: 40,
      queueTop: 70,
      decisionTop: 190,
    }))
  })

  it("submits all ready schema v2 groups with task-bound fingerprints", async () => {
    api.projects.applySmartDedup.mockResolvedValue({
      applied: 2,
      skipped: 0,
      group_results: [{ group_id: "group-world", status: "success", applied: 2 }],
    })
    await runScanToDone(groupResult())

    await latestModal().buttons.find((button) => button.text === "执行已就绪组 (1)").handler()

    expect(api.projects.applySmartDedup).toHaveBeenCalledWith("p1", {
      confirmed: true,
      scan_task_id: "scan-1",
      groups: [{
        group_id: "group-world",
        asset_type: "world_entity",
        primary_asset_id: "b",
        operations: [
          expect.objectContaining({
            source_asset_id: "a",
            action: "merge",
            expected_source_execution_fingerprint: "a".repeat(64),
            expected_target_execution_fingerprint: "b".repeat(64),
          }),
          expect.objectContaining({
            source_asset_id: "c",
            action: "alias_only",
            expected_source_execution_fingerprint: "c".repeat(64),
            expected_target_execution_fingerprint: "b".repeat(64),
          }),
        ],
      }],
    })
    expect(latestModal().body.html).toContain("执行成功")
    expect(closeModal).not.toHaveBeenCalled()
  })

  it("does not submit a completed group draft after the active project changes", async () => {
    let currentProjectId = "p1"
    api.projects.startSmartDedupScan.mockResolvedValue({ task_id: "scan-switch-done" })
    api.tasks.get.mockResolvedValue({
      task_id: "scan-switch-done",
      task_type: "smart_dedup_scan",
      status: "done",
      result: groupResult(),
    })
    const manager = createManager({ getCurrentProjectId: () => currentProjectId })
    await manager.startScan()
    await flushPromises()
    const button = latestModal().buttons.find((item) => item.text === "执行已就绪组 (1)")

    currentProjectId = "p2"
    await button.handler()

    expect(api.projects.applySmartDedup).not.toHaveBeenCalled()
    expect(closeModal).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("项目已切换，旧扫描裁决已清理", "warning")
  })

  it("requires a fresh Scene workbench preview before a Scene group is ready", async () => {
    api.outline.previewSceneMerge.mockResolvedValue({
      operation: "merge",
      field_changes: { goal: { before: "A", after: "B" } },
      chapter_mapping_change: { before: { s1: [1] }, after: { s2: [1, 2] } },
    })
    const result = sceneGroupResult()
    const manager = await runScanToDone(result)
    let modal = latestModal()
    expect(modal.body.html).toContain("生成 Scene 影响预览")
    expect(modal.buttons[0].text).toBe("执行已就绪组 (0)")

    document.body.innerHTML = modal.body.html
    const groups = manager._groups(result)
    manager._bindGroupControls(groups)
    document.querySelector("[data-smart-dedup-preview-scene]").click()
    await flushPromises()

    expect(api.outline.previewSceneMerge).toHaveBeenCalledWith("p1", {
      target_scene_id: "s2",
      source_scene_ids: ["s1"],
      confirmed: false,
    })
    modal = latestModal()
    expect(modal.body.html).toContain("我已核对当前预览")
    expect(manager._groupReadiness(groups[0]).ready).toBe(false)

    manager._groupDraftFor(groups[0]).operations.s1.scenePreviewConfirmed = true
    expect(manager._groupReadiness(groups[0]).ready).toBe(true)
  })

  it("keeps stale group results visible and offers a rescan instead of retrying them", async () => {
    const manager = await runScanToDone(groupResult())
    manager._groupResults["group-world"] = {
      group_id: "group-world",
      status: "failed",
      error_code: "stale_suggestion",
      message: "fingerprint changed",
    }

    manager._showGroupWorkbench()

    const modal = latestModal()
    expect(modal.body.html).toContain("建议已过期")
    expect(modal.buttons.map((button) => button.text)).toContain("重新扫描")
    expect(modal.buttons[0].text).toBe("执行已就绪组 (0)")
  })
})

function groupResult() {
  return {
    schema_version: 2,
    total_assets_scanned: 3,
    groups: [{
      group_id: "group-world",
      asset_type: "world_entity",
      presentation: "cluster",
      members: [
        { asset_id: "a", title: "周明瑞", status: "draft", summary: "A" },
        { asset_id: "b", title: "克莱恩·莫雷蒂", status: "canonical", summary: "B" },
        { asset_id: "c", title: "克莱恩", status: "candidate", summary: "C" },
      ],
      eligible_primary_asset_ids: ["b"],
      recommended_primary_asset_id: "b",
      edges: [
        {
          source_asset_id: "a",
          target_asset_id: "b",
          recommended_action: "merge",
          allowed_actions: ["merge", "alias_only", "keep_separate"],
          reason: "主人公同一身份",
          source_execution_fingerprint: "a".repeat(64),
          target_execution_fingerprint: "b".repeat(64),
        },
        {
          source_asset_id: "c",
          target_asset_id: "b",
          recommended_action: "alias_only",
          allowed_actions: ["merge", "alias_only", "keep_separate"],
          reason: "简称命中",
          source_execution_fingerprint: "c".repeat(64),
          target_execution_fingerprint: "b".repeat(64),
        },
      ],
    }],
  }
}

function sceneGroupResult() {
  return {
    schema_version: 2,
    total_assets_scanned: 2,
    groups: [{
      group_id: "group-scene",
      asset_type: "scene",
      presentation: "pair",
      members: [
        { asset_id: "s1", title: "Scene A", status: "draft", details: { goal: "A", chapter_ids: [1] } },
        { asset_id: "s2", title: "Scene B", status: "canonical", details: { goal: "B", chapter_ids: [2] } },
      ],
      eligible_primary_asset_ids: ["s1", "s2"],
      recommended_primary_asset_id: "s2",
      edges: [{
        source_asset_id: "s1",
        target_asset_id: "s2",
        recommended_action: "merge",
        allowed_actions: ["merge", "keep_separate"],
        source_execution_fingerprint: "1".repeat(64),
        target_execution_fingerprint: "2".repeat(64),
      }],
    }],
  }
}
