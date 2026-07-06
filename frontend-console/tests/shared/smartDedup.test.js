import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createSmartDedupManager } from "../../shared/smartDedup.js"
import { resetState, clearDocument, latestModal } from "../helpers.js"

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

beforeEach(() => {
  resetState({ currentProjectId: "p1", currentView: "world" })
  clearDocument()
  document.body.innerHTML = '<div id="view-actions"></div>'
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
      <div id="view-actions"></div>
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
      <div id="view-actions"></div>
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
    document.body.innerHTML = modal.body.html + '<div id="view-actions"></div>'
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
      <div id="view-actions"></div>
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
    document.body.innerHTML = modal.body.html + '<div id="view-actions"></div>'
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
      <div id="view-actions"></div>
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
        },
        {
          asset_type: "world_entity",
          action: "alias_only",
          source_asset_id: "alias-source",
          target_asset_id: "manual-primary",
          alias: "小名",
          allow_canonical_merge: false,
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
})
