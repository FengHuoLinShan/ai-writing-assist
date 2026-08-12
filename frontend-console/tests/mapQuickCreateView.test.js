import { beforeEach, describe, expect, it, vi } from "vitest"
import mapQuickCreateView from "../views/mapQuickCreateView.js"
import { clearDocument, resetState } from "./helpers.js"

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  vi.clearAllMocks()
  mapQuickCreateView._context = null
  mapQuickCreateView._preview = null
  mapQuickCreateView._activeLayouts = []
  mapQuickCreateView._layoutHistory = []
  mapQuickCreateView._selectedLocationIds = new Set()
  mapQuickCreateView._previousLayoutIds = new Set()
  mapQuickCreateView._selectionOverrides = new Map()
  mapQuickCreateView._selectionTarget = null
  mapQuickCreateView._includeCandidates = false
  mapQuickCreateView._target = "world"
  mapQuickCreateView._replaceMapId = null
  mapQuickCreateView._mapName = ""
  mapQuickCreateView._mapNameTouched = false
  mapQuickCreateView._scopeFilter = "all"
  mapQuickCreateView._parentFilter = "all"
  mapQuickCreateView._detailFilter = "all"
  mapQuickCreateView._filterQuery = ""
  mapQuickCreateView._dragLocationId = null
  mapQuickCreateView._onCreated = null
  mapQuickCreateView._projectId = "p1"
  mapQuickCreateView._openGeneration = 0
  mapQuickCreateView._previewGeneration = 0
  mapQuickCreateView._acceptedPreviewGeneration = 0
  mapQuickCreateView._acceptedPreviewState = null
  mapQuickCreateView._confirmPending = false
})

function mockQuickCreateApis() {
  api.world.getMapQuickCreateContext.mockResolvedValue({
    locations: [{ id: "loc1", name: "洛阳", status: "canonical" }],
    candidate_locations: [{ id: "loc2", name: "候选城", status: "candidate" }],
    existing_maps: [],
    warnings: [],
  })
  api.world.previewQuickCreateMap.mockResolvedValue({
    map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
    location_layouts: [{
      location_entity_id: "loc1",
      center_hex_q: 10,
      center_hex_r: 8,
      occupy_radius: 1,
      locked: false,
    }],
    warnings: [],
  })
}

describe("mapQuickCreateView", () => {
  it("opens preview without confirming", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.open()

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", false)
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: false,
    }), "p1")
    expect(api.world.confirmQuickCreateMap).not.toHaveBeenCalled()
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("洛阳") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("已选 1 / 共 1") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("map-quick-select-all") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.stringContaining("map-quick-extra-search") }),
      expect.any(Array),
    )
    expect(showModal).toHaveBeenCalledWith(
      "快速创建地图",
      expect.objectContaining({ html: expect.not.stringContaining("生成人物等结构化标记") }),
      expect.any(Array),
    )
  })

  it("shows placeable locations when only default spacing is available", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [{ id: "loc1", name: "琉璃湾", status: "draft" }],
      candidate_locations: [],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap.mockResolvedValue({
      map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
      location_layouts: [{
        location_entity_id: "loc1",
        center_hex_q: 10,
        center_hex_r: 8,
        occupy_radius: 1,
        locked: false,
        meta: { entity_status: "draft" },
      }],
      warnings: ["缺少地点方向/距离关系，已生成等间距草稿"],
    })

    await mapQuickCreateView.open()

    const modalHtml = showModal.mock.calls.at(-1)[1].html
    expect(modalHtml).toContain("琉璃湾")
    expect(modalHtml).toContain("缺少地点方向/距离关系，已生成等间距草稿")
    expect(modalHtml).not.toContain("暂无可放置地点")
  })

  it("world preview defaults to matching scales and supports filtered bulk selection", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [
        {
          id: "region", name: "鲁恩王国", status: "canonical",
          map_scope: { key: "region", label: "区域级", recommended_targets: ["world"] },
          parent_locations: [], has_detail_map: false,
        },
        {
          id: "city", name: "廷根市", status: "canonical",
          map_scope: { key: "settlement", label: "城市/聚落", recommended_targets: ["world", "detail"] },
          parent_locations: [], has_detail_map: false,
        },
        {
          id: "site", name: "黑荆棘安保公司", status: "canonical",
          map_scope: { key: "site", label: "地点/建筑", recommended_targets: ["detail", "drilldown"] },
          parent_locations: [{ id: "city", name: "廷根市" }], has_detail_map: false,
        },
        {
          id: "interior", name: "炼金室", status: "canonical",
          map_scope: { key: "interior", label: "室内/地下", recommended_targets: ["detail", "drilldown"] },
          parent_locations: [{ id: "site", name: "黑荆棘安保公司" }], has_detail_map: false,
        },
      ],
      candidate_locations: [], existing_maps: [], warnings: [],
    })
    api.world.previewQuickCreateMap.mockResolvedValue({
      map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
      location_layouts: ["region", "city", "site", "interior"].map((id, index) => ({
        location_entity_id: id,
        center_hex_q: index + 1,
        center_hex_r: index + 1,
        occupy_radius: 1,
        locked: false,
      })),
      warnings: ["检测到 2 个建筑或室内地点"],
    })

    await mapQuickCreateView.open()

    expect([...mapQuickCreateView._selectedLocationIds].sort()).toEqual(["city", "region"])
    const modalHtml = showModal.mock.calls.at(-1)[1].html
    expect(modalHtml).toContain("世界图已默认取消选择 2 个建筑或室内地点")
    expect(modalHtml).toContain("map-quick-filter-scope")
    expect(modalHtml).toContain("廷根市")

    mapQuickCreateView._scopeFilter = "site"
    expect(mapQuickCreateView._visibleLayouts().map((item) => item.location_entity_id)).toEqual(["site"])
    mapQuickCreateView._setAllSelected(true)
    expect([...mapQuickCreateView._selectedLocationIds].sort()).toEqual(["city", "region", "site"])
    mapQuickCreateView._setAllSelected(false)
    expect([...mapQuickCreateView._selectedLocationIds].sort()).toEqual(["city", "region"])
  })

  it("keeps preview selection focus and modal scroll during local redraws", () => {
    mapQuickCreateView._context = {
      locations: [
        { id: "loc1", name: "洛阳", status: "canonical" },
        { id: "loc2", name: "长安", status: "canonical" },
      ],
      candidate_locations: [],
    }
    mapQuickCreateView._preview = {
      map: { grid_width: 40, grid_height: 30 },
      warnings: [],
    }
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1, locked: false },
      { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1, locked: false },
    ]
    mapQuickCreateView._selectedLocationIds = new Set(["loc1", "loc2"])
    document.body.innerHTML = `<div id="modal-body">${mapQuickCreateView._render()}</div>`
    mapQuickCreateView._bindModalEvents()
    const modalBody = document.getElementById("modal-body")
    modalBody.scrollTop = 360

    const rowCheckbox = document.querySelector('[data-action="map-quick-select"][data-id="loc1"]')
    rowCheckbox.focus()
    rowCheckbox.checked = false
    rowCheckbox.dispatchEvent(new Event("change"))

    const nextRowCheckbox = document.querySelector('[data-action="map-quick-select"][data-id="loc1"]')
    expect(nextRowCheckbox).not.toBe(rowCheckbox)
    expect(document.activeElement).toBe(nextRowCheckbox)
    expect(modalBody.scrollTop).toBe(360)

    const selectAll = document.getElementById("map-quick-select-all")
    selectAll.focus()
    selectAll.checked = true
    selectAll.dispatchEvent(new Event("change"))

    expect(document.activeElement).toBe(document.getElementById("map-quick-select-all"))
    expect(modalBody.scrollTop).toBe(360)
  })

  it("target changes recompute recommendations without overriding manual choices", async () => {
    const locations = [
      ["auto-world", ["world"]],
      ["auto-detail", ["detail"]],
      ["manual-on", ["world"]],
      ["manual-off", ["world", "detail"]],
    ].map(([id, recommendedTargets]) => ({
      id,
      name: id,
      status: "canonical",
      map_scope: {
        key: id.includes("detail") ? "site" : "region",
        label: id.includes("detail") ? "地点/建筑" : "区域级",
        recommended_targets: recommendedTargets,
      },
      parent_locations: [],
      has_detail_map: false,
    }))
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations,
      candidate_locations: [],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap.mockImplementation(async () => ({
      map: { name: "快速创建地图", grid_width: 20, grid_height: 20 },
      location_layouts: locations.map((location, index) => ({
        location_entity_id: location.id,
        center_hex_q: index,
        center_hex_r: index,
        occupy_radius: 1,
        locked: false,
      })),
      warnings: [],
    }))

    await mapQuickCreateView.open()
    expect([...mapQuickCreateView._selectedLocationIds].sort()).toEqual([
      "auto-world", "manual-off", "manual-on",
    ])

    mapQuickCreateView._toggleSelection("manual-on", true)
    mapQuickCreateView._toggleSelection("manual-off", false)
    await mapQuickCreateView.setTarget("detail")

    expect([...mapQuickCreateView._selectedLocationIds].sort()).toEqual([
      "auto-detail", "manual-on",
    ])
  })

  it("disables filtered bulk selection and ignores hidden canvas locations", () => {
    mapQuickCreateView._context = {
      locations: [{
        id: "site", name: "黑荆棘安保公司", status: "canonical",
        map_scope: { key: "site", label: "地点/建筑", recommended_targets: ["detail"] },
        parent_locations: [], has_detail_map: false,
      }],
      candidate_locations: [],
    }
    mapQuickCreateView._preview = {
      map: { grid_width: 10, grid_height: 10 },
      warnings: [],
    }
    mapQuickCreateView._activeLayouts = [{
      location_entity_id: "site", center_hex_q: 5, center_hex_r: 5,
      occupy_radius: 1, locked: false,
    }]
    mapQuickCreateView._selectedLocationIds = new Set(["site"])
    mapQuickCreateView._scopeFilter = "region"

    expect(mapQuickCreateView._renderPreviewTable()).toContain(
      'id="map-quick-select-all"  disabled',
    )

    document.body.innerHTML = '<canvas id="map-quick-canvas"></canvas>'
    const canvas = document.getElementById("map-quick-canvas")
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 920, height: 420 })
    const history = vi.spyOn(mapQuickCreateView, "_pushHistory")
    mapQuickCreateView._bindCanvasEvents()
    canvas.onpointerdown({ clientX: 484, clientY: 231, preventDefault: vi.fn() })

    expect(history).not.toHaveBeenCalled()
    expect(mapQuickCreateView._dragLocationId).toBeNull()
    history.mockRestore()
  })

  it("candidate toggle refreshes context and preview", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.setIncludeCandidates(true)

    expect(api.world.getMapQuickCreateContext).toHaveBeenCalledWith("p1", true)
    expect(api.world.previewQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_candidates: true,
    }), "p1")
  })

  it("preserves an edited map name across preview refreshes", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    document.body.innerHTML = mapQuickCreateView._render()
    mapQuickCreateView._bindModalEvents()
    const nameInput = document.getElementById("map-quick-name")
    nameInput.value = "廷根空间草图"
    nameInput.dispatchEvent(new Event("input"))

    await mapQuickCreateView._changeSetting("_baseTemplate", "continent")

    expect(mapQuickCreateView._mapName).toBe("廷根空间草图")
    expect(document.getElementById("map-quick-name").value).toBe("廷根空间草图")
  })

  it("远程预览刷新后保留当前设置控件焦点和弹窗位置", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    document.body.innerHTML = '<div id="modal-body" style="overflow:auto"><div class="map-quick-create"></div></div>'
    document.querySelector(".map-quick-create").outerHTML = mapQuickCreateView._render()
    mapQuickCreateView._bindModalEvents()
    const modalBody = document.getElementById("modal-body")
    const target = document.getElementById("map-quick-target")
    modalBody.scrollTop = 360
    target.focus()

    await mapQuickCreateView.setTarget("detail")

    expect(document.activeElement).toBe(document.getElementById("map-quick-target"))
    expect(modalBody.scrollTop).toBe(360)
  })

  it("infers the fixed target level when replacing an existing map", () => {
    expect(mapQuickCreateView._targetForExistingMap({ id: "world" })).toBe("world")
    expect(mapQuickCreateView._targetForExistingMap({
      id: "detail",
      parent_entity_id: "loc1",
    })).toBe("detail")
    expect(mapQuickCreateView._targetForExistingMap({
      id: "drilldown",
      parent_entity_id: "loc2",
      parent_map_id: "detail",
    })).toBe("drilldown")
  })

  it("candidate toggle failure keeps the previous preview and shows feedback", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    const previousPreview = mapQuickCreateView._preview
    const previousLayouts = mapQuickCreateView._activeLayouts
    api.world.getMapQuickCreateContext.mockRejectedValueOnce(new Error("context failed"))

    const result = await mapQuickCreateView.setIncludeCandidates(true)

    expect(result).toBe(false)
    expect(mapQuickCreateView._includeCandidates).toBe(false)
    expect(mapQuickCreateView._preview).toBe(previousPreview)
    expect(mapQuickCreateView._activeLayouts).toEqual(previousLayouts)
    expect(toast).toHaveBeenCalledWith("快速创建预览刷新失败：context failed", "error")
  })

  it("target change failure keeps the previous preview and shows feedback", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    const previousPreview = mapQuickCreateView._preview
    api.world.previewQuickCreateMap.mockRejectedValueOnce(new Error("preview failed"))

    const result = await mapQuickCreateView.setTarget("detail")

    expect(result).toBe(false)
    expect(mapQuickCreateView._target).toBe("world")
    expect(mapQuickCreateView._preview).toBe(previousPreview)
    expect(toast).toHaveBeenCalledWith("快速创建预览刷新失败：preview failed", "error")
  })

  it("快速连改选项时只接收最新预览", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()
    let resolveDetail
    let resolveWorld
    api.world.previewQuickCreateMap.mockImplementation((payload) => new Promise((resolve) => {
      if (payload.target === "detail") resolveDetail = resolve
      else resolveWorld = resolve
    }))

    const detailRequest = mapQuickCreateView.setTarget("detail")
    const worldRequest = mapQuickCreateView.setTarget("world")
    resolveWorld({
      map: { name: "最新世界图", grid_width: 40, grid_height: 30 },
      location_layouts: [],
      warnings: [],
    })
    await worldRequest
    resolveDetail({
      map: { name: "过期详图", grid_width: 20, grid_height: 20 },
      location_layouts: [],
      warnings: [],
    })
    await detailRequest

    expect(mapQuickCreateView._target).toBe("world")
    expect(mapQuickCreateView._preview.map.name).toBe("最新世界图")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("预览刷新失败"), "error")
  })

  it("confirm creates one map and invokes callback", async () => {
    mockQuickCreateApis()
    const onCreated = vi.fn()
    mapQuickCreateView._onCreated = onCreated
    mapQuickCreateView._preview = {
      location_layouts: [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1 }],
    }
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 2 },
    ]
    mapQuickCreateView._selectedLocationIds = new Set(["loc1"])
    api.world.confirmQuickCreateMap.mockResolvedValue({
      map: { id: "m1", name: "快速创建世界地图" },
    })

    await mapQuickCreateView._confirm()

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      include_markers: false,
      layouts: mapQuickCreateView._activeLayouts,
    }), "p1")
    expect(onCreated).toHaveBeenCalledWith({ id: "m1", name: "快速创建世界地图" })
  })

  it("shows a visible error when confirm fails", async () => {
    mockQuickCreateApis()
    mapQuickCreateView._preview = {
      location_layouts: [{ location_entity_id: "loc1", center_hex_q: 1, center_hex_r: 1 }],
    }
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 2 },
    ]
    mapQuickCreateView._selectedLocationIds = new Set(["loc1"])
    api.world.confirmQuickCreateMap.mockRejectedValue(new Error("后端服务器错误"))

    const result = await mapQuickCreateView._confirm()

    expect(result).toBe(false)
    expect(closeModal).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("快速创建地图失败：后端服务器错误", "error")
  })

  it("阻止连点创建，且已成功的服务端写入不因页面回调失败而允许重试", async () => {
    mapQuickCreateView._activeLayouts = [
      { location_entity_id: "loc1", center_hex_q: 2, center_hex_r: 3, occupy_radius: 2 },
    ]
    mapQuickCreateView._selectedLocationIds = new Set(["loc1"])
    mapQuickCreateView._onCreated = vi.fn().mockRejectedValue(new Error("刷新失败"))
    let resolveConfirm
    api.world.confirmQuickCreateMap.mockReturnValue(new Promise((resolve) => {
      resolveConfirm = resolve
    }))

    const first = mapQuickCreateView._confirm()
    const second = mapQuickCreateView._confirm()
    resolveConfirm({ map: { id: "m1", name: "已创建地图" } })
    const [result, repeatedResult] = await Promise.all([first, second])

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledTimes(1)
    expect(result).toEqual({ map: { id: "m1", name: "已创建地图" } })
    expect(repeatedResult).toEqual(result)
    expect(toast).toHaveBeenCalledWith("地图已创建，但页面更新失败：刷新失败", "warning")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("快速创建地图失败"), "error")
  })

  it("submits only selected layouts", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [
        { id: "loc1", name: "洛阳", status: "canonical" },
        { id: "loc2", name: "长安", status: "canonical" },
      ],
      candidate_locations: [],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap.mockResolvedValue({
      map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
      location_layouts: [
        { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
        { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
      ],
      warnings: [],
    })
    api.world.confirmQuickCreateMap.mockResolvedValue({
      map: { id: "m1", name: "快速创建世界地图" },
    })

    await mapQuickCreateView.open()
    mapQuickCreateView._toggleSelection("loc1", false)
    await mapQuickCreateView._confirm()

    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(expect.objectContaining({
      layouts: [
        { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
      ],
    }), "p1")
  })

  it("does not confirm when no layouts are selected", async () => {
    mockQuickCreateApis()

    await mapQuickCreateView.open()
    mapQuickCreateView._setAllSelected(false)
    const result = await mapQuickCreateView._confirm()

    expect(result).toBe(false)
    expect(api.world.confirmQuickCreateMap).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("请至少选择一个地点", "warning")
  })

  it("preserves existing selections and keeps newly loaded candidates read-only", async () => {
    api.world.getMapQuickCreateContext.mockResolvedValue({
      locations: [
        { id: "loc1", name: "洛阳", status: "canonical" },
        { id: "loc2", name: "长安", status: "canonical" },
        { id: "loc3", name: "候选城", status: "candidate" },
      ],
      candidate_locations: [{ id: "loc3", name: "候选城", status: "candidate" }],
      existing_maps: [],
      warnings: [],
    })
    api.world.previewQuickCreateMap
      .mockResolvedValueOnce({
        map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
        location_layouts: [
          { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
        ],
        warnings: [],
      })
      .mockResolvedValueOnce({
        map: { name: "快速创建世界地图", grid_width: 40, grid_height: 30 },
        location_layouts: [
          { location_entity_id: "loc1", center_hex_q: 10, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc2", center_hex_q: 14, center_hex_r: 8, occupy_radius: 1 },
          { location_entity_id: "loc3", center_hex_q: 18, center_hex_r: 8, occupy_radius: 1 },
        ],
        warnings: [],
      })

    await mapQuickCreateView.open()
    mapQuickCreateView._toggleSelection("loc1", false)
    await mapQuickCreateView.setIncludeCandidates(true)

    expect(mapQuickCreateView._selectedLocationIds.has("loc1")).toBe(false)
    expect(mapQuickCreateView._selectedLocationIds.has("loc2")).toBe(true)
    expect(mapQuickCreateView._selectedLocationIds.has("loc3")).toBe(false)
  })

  it("updates active preview layout before confirm", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open()

    mapQuickCreateView._moveLocation("loc1", 1, 0)
    mapQuickCreateView._resizeLocation("loc1", "increase")

    expect(mapQuickCreateView._activeLayouts[0]).toMatchObject({
      center_hex_q: 11,
      center_hex_r: 8,
      occupy_radius: 2,
    })

    mapQuickCreateView._undoLayout()
    expect(mapQuickCreateView._activeLayouts[0]).toMatchObject({
      center_hex_q: 11,
      occupy_radius: 1,
    })
  })

  it("项目切换后拒绝用原弹窗向新项目确认", async () => {
    mockQuickCreateApis()
    await mapQuickCreateView.open({ projectId: "p1" })
    state.currentProjectId = "p2"

    const result = await mapQuickCreateView._confirm()

    expect(result).toBe(false)
    expect(api.world.confirmQuickCreateMap).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(
      "当前项目已切换，请返回原项目重新打开快速创建",
      "warning",
    )
  })

  it("确认期间切换项目不触发原任务完成回调", async () => {
    mockQuickCreateApis()
    const onCreated = vi.fn()
    await mapQuickCreateView.open({ projectId: "p1", onCreated })
    let resolveConfirm
    api.world.confirmQuickCreateMap.mockReturnValue(new Promise((resolve) => {
      resolveConfirm = resolve
    }))
    const confirming = mapQuickCreateView._confirm()
    state.currentProjectId = "p2"
    resolveConfirm({ map: { id: "m1", name: "原项目地图" } })

    const result = await confirming

    expect(result).toBe(true)
    expect(api.world.confirmQuickCreateMap).toHaveBeenCalledWith(
      expect.any(Object),
      "p1",
    )
    expect(onCreated).not.toHaveBeenCalled()
  })
})
