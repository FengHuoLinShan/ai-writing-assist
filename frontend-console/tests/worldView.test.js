/**
 * worldView 测试
 *
 * 覆盖生命周期、3 个子视图（候选清洗已移除）、实体 CRUD、关系和别名管理。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import worldView from "../views/worldView.js"
import { resetState, autoConfirm, captureModalHandler, renderHtml } from "./helpers.js"

beforeEach(() => {
  resetState()
  worldView._entities = []
  worldView._candidates = []
  worldView._candidateTotal = 0
  worldView._batches = []
  worldView._relations = []
  worldView._relationTotal = 0
  worldView._relationFilters = { skip: 0, limit: 20 }
  worldView._aliases = []
  worldView._aliasTotal = 0
  worldView._aliasFilters = { skip: 0, limit: 20 }
  worldView._candidateFilters = { skip: 0, limit: 20 }
  worldView._total = 0
  worldView._entitiesLoadError = null
  worldView._filters = { entity_type: "", status: "", q: "", skip: 0, limit: 20 }
  worldView._objectViewMode = "table"
  worldView._advancedFiltersOpen = false
  worldView._autoExtractOpen = false
  if (worldView._autoExtractPoller?.stop) worldView._autoExtractPoller.stop()
  worldView._autoExtractTaskId = null
  worldView._autoExtractStatus = "就绪"
  worldView._autoExtractTimer = null
  worldView._autoExtractProgress = null
  worldView._autoExtractPoller = null
  worldView._autoExtractMeta = null
  worldView._fusionTaskId = null
  worldView._fusionProgress = null
  if (worldView._fusionPoller?.stop) worldView._fusionPoller.stop()
  worldView._fusionPoller = null
  worldView._eventsBound = false
  localStorage.removeItem("novel_world_extract_task")
  localStorage.removeItem("novel_active_workflows_v1")
  vi.clearAllMocks()
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("加载实体列表和批次信息", async () => {
    state.currentProjectId = "p1"
    api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "王都" }], total: 1 })
    api.world.listEntityBatches.mockResolvedValue([{ batch_id: "b1", entities: [{ id: "e1", name: "王都", entity_type: "location" }] }])

    await worldView.onEnter()

    expect(api.world.listEntities).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20 })
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "p1",
      status: "candidate",
      skip: 0,
      limit: 20,
    })
    expect(api.world.listEntityBatches).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(worldView._entities).toHaveLength(1)
    expect(worldView._candidateTotal).toBe(1)
    expect(worldView._total).toBe(1)
    expect(worldView._batches).toHaveLength(1)
  })

  it("API 失败时显示对象列表加载失败提示", async () => {
    state.currentProjectId = "p1"
    api.world.listEntities.mockRejectedValue(new Error("失败"))

    await worldView.onEnter()
    const html = await worldView.render()

    expect(worldView._entities).toEqual([])
    expect(html).toContain("世界对象加载失败")
    expect(html).toContain("可稍后重试")
  })
})

// ============================================================
// onLeave
// ============================================================

describe("onLeave", () => {
  it("stops the fusion poller", () => {
    const stop = vi.fn()
    worldView._fusionPoller = { stop }
    worldView.onLeave()
    expect(stop).toHaveBeenCalled()
    expect(worldView._fusionPoller).toBeNull()
  })
})

// ============================================================
// render
// ============================================================

describe("worldView render", () => {
  it("渲染子标签导航（包含待确认入口）", async () => {
    const html = await worldView.render()
    expect(html).toContain("对象库")
    expect(html).toContain("待确认")
    expect(html).toContain("关系")
    expect(html).toContain("别名")
  })

  it("待确认入口渲染对象/别名/关系三子 tab", async () => {
    state.currentSubView = "review-objects"
    worldView._candidates = [{ id: "c1", name: "候选对象", entity_type: "item", status: "candidate" }]
    const html = await worldView.render()
    expect(html).toContain("对象")
    expect(html).toContain("别名")
    expect(html).toContain("关系")
    expect(html).toContain("候选对象")
  })

  it("旧 candidates 子路由仍渲染待确认对象队列", async () => {
    state.currentSubView = "candidates"
    worldView._candidates = [{ id: "c1", name: "旧路由候选", entity_type: "item", status: "candidate" }]
    const html = await worldView.render()
    expect(html).toContain("旧路由候选")
    expect(html).toContain("对象")
  })

  it("点击地图子标签直接导航到一级地图页", async () => {
    state.currentSubView = "objects"

    document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
    worldView._bindEvents()
    document.querySelector('[data-action="nav-map"]')?.click()

    expect(router.navigate).toHaveBeenCalledWith("map", null)
  })

  it("repeated render and bind does not double-fire direct-bound button clicks", async () => {
    state.currentProjectId = "p1"
    worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical" }]
    const spy = vi.spyOn(worldView, "_showCreateForm").mockImplementation(() => {})

    document.body.innerHTML = await worldView.render()
    worldView._bindEvents()
    document.body.innerHTML = await worldView.render()
    worldView._bindEvents()

    document.getElementById("btn-new-entity").click()
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })

  it("对象库将 resolved_as alias 的 merged 对象显示为已确认为别名", () => {
    worldView._entities = [{
      id: "e1",
      name: "黑荆棘安保公司",
      entity_type: "organization",
      status: "merged",
      content_json: { resolved_as: "alias", merged_into: "target" },
    }]

    const html = worldView._renderEntityList()

    expect(html).toContain("已确认为别名")
  })

  it("从 URL query 恢复对象库筛选、分页和卡片视图", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "objects"
    router.navigate("world", "objects", true, new URLSearchParams({
      entity_type: "character",
      status: "draft",
      q: "克莱恩",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: "true",
      auto_ingested: "true",
      page: "3",
      view: "card",
    }))
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    await worldView.render()

    expect(worldView._filters).toMatchObject({
      entity_type: "character",
      status: "draft",
      q: "克莱恩",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: "true",
      auto_ingested: "true",
      skip: 40,
      limit: 20,
    })
    expect(worldView._objectViewMode).toBe("card")
    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      entity_type: "character",
      status: "draft",
      q: "克莱恩",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: true,
      auto_ingested: true,
      skip: 40,
      limit: 20,
    }))
  })

  it("从 URL query 恢复待确认对象筛选和分页", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "review-objects"
    router.navigate("world", "review-objects", true, new URLSearchParams({
      suggested_action: "link_to_existing",
      source: "deep_import",
      workflow_id: "wf-2",
      scene_index: "5",
      source_chapter_index: "3",
      confidence_min: "0.7",
      confidence_max: "0.95",
      page: "2",
    }))
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    await worldView.render()

    expect(worldView._candidateFilters).toMatchObject({
      suggested_action: "link_to_existing",
      source: "deep_import",
      workflow_id: "wf-2",
      scene_index: "5",
      source_chapter_index: "3",
      confidence_min: "0.7",
      confidence_max: "0.95",
      skip: 20,
      limit: 20,
    })
    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      status: "candidate",
      suggested_action: "link_to_existing",
      source: "deep_import",
      workflow_id: "wf-2",
      scene_index: 5,
      source_chapter_index: 3,
      confidence_min: 0.7,
      confidence_max: 0.95,
      skip: 20,
      limit: 20,
    }))
  })
})

// ============================================================
// 候选清洗
// ============================================================

describe("候选清洗", () => {
  describe("_loadCandidates", () => {
    it("同一候选 ID 重复返回时只保留一条，避免前端重复显示", async () => {
      state.currentProjectId = "p1"
      api.world.listEntities.mockResolvedValue({
        items: [
          { id: "c1", name: "塔罗会", entity_type: "faction", status: "candidate" },
          { id: "c1", name: "塔罗会", entity_type: "faction", status: "candidate" },
        ],
        total: 2,
      })

      await worldView._loadCandidates()

      expect(worldView._candidates).toHaveLength(1)
      expect(worldView._candidates[0].id).toBe("c1")
      expect(worldView._candidateTotal).toBe(2)
    })

    it("待确认对象筛选参数传给 entities API", async () => {
      state.currentProjectId = "p1"
      worldView._candidateFilters = {
        skip: 0,
        limit: 20,
        suggested_action: "link_to_existing",
        source: "deep_import",
        workflow_id: "wf1",
        scene_index: "2",
        source_chapter_index: "",
        confidence_min: "0.8",
        confidence_max: "",
      }
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

      await worldView._loadCandidates()

      expect(api.world.listEntities).toHaveBeenCalledWith({
        novel_id: "p1",
        status: "candidate",
        skip: 0,
        limit: 20,
        suggested_action: "link_to_existing",
        source: "deep_import",
        workflow_id: "wf1",
        scene_index: 2,
        confidence_min: 0.8,
      })
    })
  })

  describe("_renderCandidatesList", () => {
    it("空列表显示空状态", () => {
      const html = worldView._renderCandidatesList()
      expect(html).toContain("没有待处理的候选对象")
    })

    it("别名候选显示目标对象名称并提供确认为别名入口", () => {
      worldView._candidates = [{
        id: "c1",
        name: "岚姐",
        entity_type: "character",
        status: "candidate",
        content_json: {
          _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_name: "林岚",
          },
        },
      }]

      const html = worldView._renderCandidatesList()

      expect(html).toContain("作为林岚别名")
      expect(html).toContain("candidate-action-badge")
      expect(html).toContain('data-action="resolve-candidate-alias"')
      expect(html).toContain("确认为别名")
      expect(html).not.toContain('data-action="merge-entity"')
      expect(html).toContain('data-target-name="林岚"')
    })

    it("temporary_only 候选显示设为临时且不显示提升按钮", () => {
      worldView._candidates = [{
        id: "c1",
        name: "临时钥匙",
        entity_type: "item",
        status: "candidate",
        content_json: { _meta: { suggested_action: "temporary_only" } },
      }]

      const html = worldView._renderCandidatesList()

      expect(html).toContain("设为临时")
      expect(html).toContain('data-action="ignore-candidate"')
      expect(html).not.toContain('data-action="accept-candidate"')
    })

    it("候选超过一页时显示分页控制", () => {
      worldView._candidates = [{ id: "c1", name: "候选1", entity_type: "item" }]
      worldView._candidateTotal = 35

      const html = worldView._renderCandidatesList()

      expect(html).toContain('data-action="prev-candidates-page"')
      expect(html).toContain('data-action="next-candidates-page"')
      expect(html).toContain("共 35 条")
    })
  })

  describe("_changeCandidatePage", () => {
    it("候选翻页时更新 skip 并写入 URL query", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "review-objects"
      worldView._candidateTotal = 45
      api.world.listEntities.mockResolvedValue({ items: [{ id: "c21", name: "候选21" }], total: 45 })

      await worldView._changeCandidatePage(1)

      expect(worldView._candidateFilters.skip).toBe(20)
      expect(api.world.listEntities).toHaveBeenCalledWith({
        novel_id: "p1",
        status: "candidate",
        skip: 20,
        limit: 20,
      })
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(router.navigate).toHaveBeenCalledWith("world", "review-objects", true, expect.any(URLSearchParams))
      expect(query.get("page")).toBe("2")
    })
  })

  describe("_applyCandidateReviewFilters", () => {
    it("待确认对象筛选写入 URL query", async () => {
      state.currentSubView = "review-objects"
      document.body.innerHTML = `
        <select id="review-candidate-action"><option value="link_to_existing" selected>别名</option></select>
        <input id="review-candidate-source" value="deep_import" />
        <input id="review-candidate-workflow" value="wf-12" />
        <input id="review-candidate-scene" value="4" />
        <input id="review-candidate-chapter" value="2" />
        <input id="review-candidate-confidence-min" value="0.7" />
        <input id="review-candidate-confidence-max" value="0.95" />
      `

      await worldView._applyCandidateReviewFilters()

      expect(router.navigate).toHaveBeenCalledWith("world", "review-objects", true, expect.any(URLSearchParams))
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("suggested_action")).toBe("link_to_existing")
      expect(query.get("source")).toBe("deep_import")
      expect(query.get("workflow_id")).toBe("wf-12")
      expect(query.get("scene_index")).toBe("4")
      expect(query.get("source_chapter_index")).toBe("2")
      expect(query.get("confidence_min")).toBe("0.7")
      expect(query.get("confidence_max")).toBe("0.95")
      expect(query.get("page")).toBeNull()
    })

    it("重置待确认对象筛选会清空 URL query", async () => {
      state.currentSubView = "review-objects"
      worldView._candidateFilters = {
        skip: 20,
        limit: 20,
        suggested_action: "create_new",
        source: "deep_import",
        workflow_id: "wf-1",
        scene_index: "3",
        source_chapter_index: "1",
        confidence_min: "0.5",
        confidence_max: "0.9",
      }

      await worldView._resetCandidateReviewFilters()

      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.toString()).toBe("")
      expect(worldView._candidateFilters.skip).toBe(0)
    })
  })

  describe("acceptCandidate", () => {
    it("确认 create_new 候选时提升为正史并刷新候选列表", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "review-objects"
      worldView._candidates = [{
        id: "c1",
        name: "新地点",
        content_json: { _meta: { suggested_action: "create_new" } },
      }]
      api.world.promoteEntity.mockResolvedValue({})
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      autoConfirm()

      await worldView.acceptCandidate("c1")

      expect(api.world.promoteEntity).toHaveBeenCalledWith("c1", "p1")
      expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
        novel_id: "p1",
        status: "candidate",
      }))
    })

    it("确认候选时先乐观移除，失败后恢复", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "review-objects"
      worldView._candidates = [{
        id: "c1",
        name: "新地点",
        entity_type: "location",
        content_json: { _meta: { suggested_action: "create_new" } },
      }]
      worldView._candidateTotal = 1
      api.world.promoteEntity.mockRejectedValue(new Error("network down"))
      autoConfirm()
      document.body.innerHTML = `<main id="workspace-content">${worldView._renderCandidatesList()}</main>`

      await worldView.acceptCandidate("c1")

      expect(api.world.promoteEntity).toHaveBeenCalledWith("c1", "p1")
      expect(worldView._candidates.map((item) => item.id)).toEqual(["c1"])
      expect(worldView._candidateTotal).toBe(1)
      expect(document.getElementById("workspace-content").textContent).toContain("新地点")
      expect(toast).toHaveBeenCalledWith("处理失败：network down", "error")
    })
  })

  describe("ignoreCandidate", () => {
    it("temporary_only 通过状态更新清理，成功后刷新候选列表", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "c1",
        name: "临时钥匙",
        content_json: { _meta: { suggested_action: "temporary_only" } },
      }]
      api.world.updateEntity.mockResolvedValue({})
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      autoConfirm()

      await worldView.ignoreCandidate("c1")

      expect(api.world.updateEntity).toHaveBeenCalledWith(
        "c1",
        expect.objectContaining({ status: "ignored" }),
        "p1",
      )
      expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
        novel_id: "p1",
        status: "candidate",
      }))
    })
  })
})

// ============================================================
// 对象库
// ============================================================

describe("对象库", () => {
  describe("_renderEntityList", () => {
    it("空列表显示空状态", () => {
      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      expect(html).toContain("还没有世界对象")
      expect(html).toContain('data-action="new"')
      expect(container.querySelector("[data-action='toggle-extract']")).toBeTruthy()
      expect(container.querySelector(".empty-state [data-action='toggle-extract']")).toBeNull()
    })

    it("渲染实体表格", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]
      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      const row = [...container.querySelectorAll("tr")]
        .find((tr) => tr.textContent.includes("王都"))

      expect(row?.textContent).toContain("location")
      expect(row?.textContent).toContain("正史")
      expect(row?.querySelector('[data-action="edit-entity"]')).toBeTruthy()
      expect(row?.querySelector('[data-action="open-entity-map"]')).toBeTruthy()
      expect(row?.querySelector('[data-action="delete-entity"]')).toBeTruthy()
    })

    it("从 content_json._meta 渲染对象需复核状态", () => {
      worldView._entities = [{
        id: "e1",
        name: "王都",
        entity_type: "location",
        status: "draft",
        content_json: { _meta: { needs_review: true } },
      }]

      const container = renderHtml(worldView._renderEntityList())
      const row = [...container.querySelectorAll("tr")]
        .find((tr) => tr.textContent.includes("王都"))

      expect(row?.textContent).toContain("需复核")
      expect(row?.querySelector('[data-action="mark-entity-reviewed"]')).toBeTruthy()
      expect(row?.querySelector('[data-action="mark-entity-unreviewed"]')).toBeFalsy()
    })

    it("表格视图转义未知实体状态的 badge class", () => {
      worldView._entities = [{
        id: "e1",
        name: "王都",
        entity_type: "location",
        status: 'candidate" onclick="alert(1)',
        summary: "首都",
      }]

      const container = renderHtml(worldView._renderEntityList())
      const badge = container.querySelector("tbody .badge")

      expect(badge?.getAttribute("onclick")).toBeNull()
      expect(badge?.textContent).toContain('candidate" onclick="alert(1)')
    })

    it("卡片视图复用现有编辑和地图操作", () => {
      worldView._objectViewMode = "card"
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]

      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      const card = container.querySelector(".world-object-card")

      expect(html).toContain('data-action="set-object-view"')
      expect(card?.textContent).toContain("王都")
      expect(card?.textContent).toContain("地点")
      expect(card?.textContent).toContain("首都")
      expect(card?.querySelector('[data-action="edit-entity"]')).toBeTruthy()
      expect(card?.querySelector('[data-action="open-entity-map"]')).toBeTruthy()
      expect(card?.querySelector('[data-action="delete-entity"]')).toBeTruthy()
    })

    it("卡片视图转义未知实体状态的 badge class", () => {
      worldView._objectViewMode = "card"
      worldView._entities = [{
        id: "e1",
        name: "王都",
        entity_type: "location",
        status: 'candidate" onclick="alert(1)',
        summary: "首都",
      }]

      const container = renderHtml(worldView._renderEntityList())
      const badge = container.querySelector(".world-object-card .badge")

      expect(badge?.getAttribute("onclick")).toBeNull()
      expect(badge?.textContent).toContain('candidate" onclick="alert(1)')
    })

    it("对象行打开地图时使用 open-target 并携带 focus_entity_id", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
      state.currentProjectId = "p1"
      api.world.getMapOpenTarget.mockResolvedValue({
        mode: "dashboard",
        map_id: "m1",
        focus_entity_id: "e1",
      })

      await worldView._openEntityMap("e1")

      expect(api.world.getMapOpenTarget).toHaveBeenCalledWith("p1", { focusEntityId: "e1" })
      expect(openSpy).toHaveBeenCalledWith(
        "#workbench/p1/map?map_id=m1&focus_entity_id=e1&mode=dashboard",
        "_blank",
        "noopener",
      )
      openSpy.mockRestore()
    })

    it("对象找不到地图上下文时显示 fallback 文案", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
      state.currentProjectId = "p1"
      api.world.getMapOpenTarget.mockResolvedValue({
        mode: "overview",
        focus_entity_id: "e1",
        fallback_message: "该对象尚未绑定地图，已打开地图总览",
      })

      await worldView._openEntityMap("e1")

      expect(toast).toHaveBeenCalledWith("该对象尚未绑定地图，已打开地图总览", "warning")
      expect(openSpy).toHaveBeenCalledWith(
        "#workbench/p1/map?focus_entity_id=e1&mode=overview",
        "_blank",
        "noopener",
      )
      openSpy.mockRestore()
    })

    it("自动识别面板展开时显示", () => {
      worldView._autoExtractOpen = true
      const html = worldView._renderEntityList()
      expect(html).toContain("世界对象与别名/关系自动提取")
    })

    it("渲染过滤栏与分页", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]
      worldView._total = 30
      const html = worldView._renderEntityList()
      expect(html).toContain("filter-entity-type")
      expect(html).toContain("filter-status")
      expect(html).toContain("filter-q")
      expect(html).toContain("apply-filters")
      expect(html).toContain("reset-filters")
      expect(html).toContain("prev-page")
      expect(html).toContain("next-page")
    })
  })

  describe("_applyFilters", () => {
    it("应用过滤参数并写入对象库 URL query", async () => {
      state.currentProjectId = "p1"
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      document.body.innerHTML = `
        <select id="filter-entity-type"><option value="location" selected>地点</option></select>
        <select id="filter-status"><option value="canonical" selected>正史</option></select>
        <input id="filter-q" value="王都" />
      `

      await worldView._applyFilters()

      expect(worldView._filters.entity_type).toBe("location")
      expect(worldView._filters.status).toBe("canonical")
      expect(worldView._filters.q).toBe("王都")
      expect(worldView._filters.skip).toBe(0)
      expect(api.world.listEntities).not.toHaveBeenCalled()
      expect(router.navigate).toHaveBeenCalledWith("world", "objects", true, expect.any(URLSearchParams))
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.toString()).toBe("entity_type=location&status=canonical&q=%E7%8E%8B%E9%83%BD")
    })

    it("应用深度导入筛选参数并停留在对象管理视图 URL", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "objects"
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      document.body.innerHTML = `
        <select id="filter-entity-type"><option value="">全部类型</option></select>
        <select id="filter-status"><option value="deprecated" selected>废弃</option></select>
        <input id="filter-q" value="" />
        <select id="filter-source"><option value="deep_import" selected>深度导入</option></select>
        <input id="filter-workflow-id" value="wf-18" />
        <select id="filter-needs-review"><option value="true" selected>需复核</option></select>
        <select id="filter-auto-ingested"><option value="true" selected>自动入库</option></select>
      `

      await worldView._applyFilters()

      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("status")).toBe("deprecated")
      expect(query.get("source")).toBe("deep_import")
      expect(query.get("workflow_id")).toBe("wf-18")
      expect(query.get("needs_review")).toBe("true")
      expect(query.get("auto_ingested")).toBe("true")
      expect(query.get("page")).toBeNull()
      expect(router.navigate).not.toHaveBeenCalledWith("map", null)
    })
  })

  describe("_changePage", () => {
    it("翻页时更新 skip 并写入对象库 URL query", async () => {
      state.currentProjectId = "p1"
      worldView._total = 50
      worldView._filters.skip = 0
      api.world.listEntities.mockResolvedValue({ items: [], total: 50 })

      await worldView._changePage(1)

      expect(worldView._filters.skip).toBe(20)
      expect(api.world.listEntities).not.toHaveBeenCalled()
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("page")).toBe("2")
    })
  })

  describe("_setObjectViewMode", () => {
    it("切换对象库视图模式并写入 URL query", async () => {
      await worldView._setObjectViewMode("card")
      expect(worldView._objectViewMode).toBe("card")
      let query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("view")).toBe("card")

      await worldView._setObjectViewMode("unknown")
      expect(worldView._objectViewMode).toBe("table")
      query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("view")).toBeNull()
    })
  })

  describe("editEntity", () => {
    it("未找到实体不操作", () => {
      worldView.editEntity("nonexistent")
      expect(showModal).not.toHaveBeenCalled()
    })

    it("找到实体时显示编辑模态框", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location" }]
      worldView.editEntity("e1")
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("deleteEntity", () => {
    it("deleteEntity 调用 confirmAction", () => {
      worldView._entities = [{ id: "e1", name: "王都" }]
      worldView.deleteEntity("e1")
      expect(confirmAction).toHaveBeenCalled()
    })
  })

  describe("_showCreateForm", () => {
    it("_showCreateForm 调用 showModal 显示表单", () => {
      worldView._showCreateForm()
      expect(showModal).toHaveBeenCalled()
      const html = vi.mocked(showModal).mock.calls[0][1].html
      expect(html).toContain("create-entity-name")
    })

    it("409 重复时显示确认并支持强制创建", async () => {
      state.currentProjectId = "p1"
      const conflict = new Error("请求失败 (409)：requires_confirmation: true；similar_entities: 张三 (0.98)")
      conflict.status = 409
      conflict.detail = {
        requires_confirmation: true,
        similar_entities: [{
          id: "e1",
          name: "张三",
          entity_type: "character",
          similarity_score: 0.98,
        }],
      }
      api.world.createEntity
        .mockRejectedValueOnce(conflict)
        .mockResolvedValueOnce({ id: "e2", name: "张三" })
      autoConfirm()

      worldView._showCreateForm()
      const handler = captureModalHandler()

      document.body.innerHTML = `
        <input id="create-entity-name" value="张三" />
        <select id="create-entity-type"><option value="character" selected>人物</option></select>
        <textarea id="create-entity-summary"></textarea>
      `
      await handler()

      expect(confirmAction.mock.calls[0][0]).toContain("张三 / character / 相似度 0.98")
      expect(api.world.createEntity).toHaveBeenCalledTimes(2)
      expect(api.world.createEntity).toHaveBeenLastCalledWith(
        expect.objectContaining({ name: "张三", force_create: true }),
        "p1",
      )
    })
  })
})

// ============================================================
// 关系
// ============================================================

describe("关系", () => {
  describe("_renderRelations", () => {
    it("_renderRelations 无项目显示空提示", async () => {
      const html = await worldView._renderRelations()
      expect(html).toContain("请先选择项目")
    })

    it("渲染关系列表", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({ items: [{ id: "r1", source_id: "src", source_name: "克莱恩", target_id: "tgt", target_name: "邓恩", relation_type: "friend_of" }] })
      const html = await worldView._renderRelations()
      expect(api.world.listRelationships).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20 })
      expect(html).toContain('data-action="delete-relation"')
      expect(html).toContain('data-action="mark-relation-unreviewed"')
      expect(html).toContain("克莱恩")
      expect(html).toContain("邓恩")
      expect(html).not.toContain("src...")
    })

    it("渲染待确认关系状态", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({
        items: [
          {
            id: "r1",
            source_id: "src",
            target_id: "tgt",
            relation_type: "sibling",
            status: "candidate",
          },
        ],
      })
      const html = await worldView._renderRelations()
      expect(html).toContain("待确认")
      expect(html).toContain('data-action="mark-relation-reviewed"')
      expect(html).toContain("复核通过")
    })

    it("待确认关系队列只请求 candidate 并显示编辑并确认", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({
        items: [{
          id: "r1",
          source_id: "src",
          source_name: "克莱恩",
          target_id: "tgt",
          target_name: "值夜者",
          relation_type: "member_of",
          status: "candidate",
          quote: "证据文本",
        }],
        total: 1,
      })

      const html = await worldView._renderRelations({ reviewOnly: true })

      expect(api.world.listRelationships).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20, status: "candidate" })
      expect(html).toContain("编辑并确认")
      expect(html).toContain("证据文本")
    })

    it("待确认关系筛选参数传给 API", async () => {
      state.currentProjectId = "p1"
      worldView._relationFilters = { skip: 0, limit: 20, q: "克莱恩", relation_type: "member_of", source_chapter_id: "ch1", strength_min: "0.7", strength_max: "" }
      api.world.listRelationships.mockResolvedValue({ items: [], total: 0 })

      await worldView._renderRelations({ reviewOnly: true })

      expect(api.world.listRelationships).toHaveBeenCalledWith({
        novel_id: "p1",
        skip: 0,
        limit: 20,
        status: "candidate",
        q: "克莱恩",
        relation_type: "member_of",
        source_chapter_id: "ch1",
        strength_min: 0.7,
      })
    })

    it("关系超过一页时显示分页并支持翻页", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({
        items: [{ id: "r1", source_name: "A", target_name: "B", relation_type: "ally_of" }],
        total: 41,
      })

      const html = await worldView._renderRelations()
      await worldView._changeRelationPage(1)

      expect(html).toContain('data-action="next-relations-page"')
      expect(html).toContain("共 41 条")
      expect(worldView._relationFilters.skip).toBe(20)
      expect(router.refresh).toHaveBeenCalled()
    })
  })

  describe("showRelationCreateForm", () => {
    it("showRelationCreateForm 调用 showModal", () => {
      worldView.showRelationCreateForm()
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("showRelationReviewEditForm", () => {
    it("关系编辑并确认只提交可编辑字段", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [
        { id: "e1", name: "克莱恩", entity_type: "character", status: "canonical" },
        { id: "e2", name: "值夜者", entity_type: "faction", status: "canonical" },
      ]
      worldView._relations = [{
        id: "r1",
        source_id: "e1",
        target_id: "e2",
        relation_type: "member_of",
        description: "旧描述",
        strength: 0.5,
        quote: "证据文本",
        source_chapter_id: "ch1",
        status: "candidate",
      }]
      api.world.reviewEditRelationship.mockResolvedValue({ affected_ids: ["r1"] })

      worldView.showRelationReviewEditForm("r1")
      const body = showModal.mock.calls[0][1].html
      expect(body).toContain("证据文本")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <select id="rel-review-source"><option value="e1" selected>克莱恩</option></select>
        <select id="rel-review-target"><option value="e2" selected>值夜者</option></select>
        <input id="rel-review-type" value="ally_of" />
        <textarea id="rel-review-description">新描述</textarea>
        <input id="rel-review-strength" value="0.8" />
      `

      await handler()

      expect(api.world.reviewEditRelationship).toHaveBeenCalledWith("r1", {
        source_id: "e1",
        target_id: "e2",
        relation_type: "ally_of",
        description: "新描述",
        strength: 0.8,
        confirm_review: true,
      }, "p1")
      expect(api.world.reviewEditRelationship.mock.calls[0][1]).not.toHaveProperty("quote")
      expect(api.world.reviewEditRelationship.mock.calls[0][1]).not.toHaveProperty("source_chapter_id")
    })
  })

  describe("deleteRelation", () => {
    it("deleteRelation 调用 confirmAction", () => {
      worldView.deleteRelation("r1")
      expect(confirmAction).toHaveBeenCalled()
    })

    it("标记关系复核通过", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "relations"
      api.world.reviewEditRelationship.mockResolvedValue({})
      api.world.listRelationships.mockResolvedValue({
        items: [{ id: "r1", source_name: "A", target_name: "B", relation_type: "ally_of", status: "canonical" }],
        total: 1,
      })
      document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
      document.getElementById("workspace-content").scrollTop = 66

      await worldView._markRelationReviewed("r1")

      expect(api.world.reviewEditRelationship).toHaveBeenCalledWith("r1", { confirm_review: true }, "p1")
      expect(toast).toHaveBeenCalledWith("关系已标记为已复核", "success")
      expect(router.refresh).not.toHaveBeenCalled()
      expect(document.getElementById("workspace-content").scrollTop).toBe(66)
    })

    it("关系复核失败显示反馈并消化 rejection", async () => {
      state.currentProjectId = "p1"
      api.world.reviewEditRelationship.mockRejectedValue(new Error("review failed"))

      const result = await worldView._markRelationReviewed("r1")

      expect(result).toBe(false)
      expect(toast).toHaveBeenCalledWith("关系复核状态更新失败：review failed", "error")
    })
  })
})

// ============================================================
// 别名
// ============================================================

describe("别名", () => {
  describe("_renderAliases", () => {
    it("_renderAliases 无项目显示空提示", async () => {
      const html = await worldView._renderAliases()
      expect(html).toContain("请先选择项目")
    })

    it("渲染别名列表", async () => {
      state.currentProjectId = "p1"
      api.world.listAliases.mockResolvedValue({ items: [{ id: "a1", alias: "炎帝", alias_type: "title", entity_id: "e1", confidence: 0.8 }] })
      const html = await worldView._renderAliases()
      expect(api.world.listAliases).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20 })
      expect(html).toContain("炎帝")
      expect(html).toContain("称号")
      expect(html).toContain("80%")
      expect(html).toContain('data-action="delete-alias"')
      expect(html).toContain('data-action="mark-alias-unreviewed"')
    })

    it("渲染待确认别名元数据", async () => {
      state.currentProjectId = "p1"
      api.world.listAliases.mockResolvedValue({
        items: [
          {
            alias: "周明瑞",
            alias_type: "name",
            entity_id: "e1",
            entity_name: "克莱恩",
            confidence: 0.91,
            status: "candidate",
            source: "deep_import",
            needs_review: true,
          },
        ],
      })
      const html = await worldView._renderAliases()
      expect(html).toContain("克莱恩")
      expect(html).toContain("待确认")
      expect(html).toContain("深度导入")
      expect(html).toContain("91%")
      expect(html).toContain('data-action="edit-alias-review"')
      expect(html).toContain("编辑并确认")
      expect(html).toContain('data-action="mark-alias-reviewed"')
    })

    it("待确认别名队列请求 needs_review 并传递筛选", async () => {
      state.currentProjectId = "p1"
      worldView._aliasFilters = { skip: 0, limit: 20, q: "黑荆棘", source: "deep_import", workflow_id: "wf1", scene_index: "3", confidence_min: "0.8", confidence_max: "", source_chapter_index: "" }
      api.world.listAliases.mockResolvedValue({ items: [], total: 0 })

      await worldView._renderAliases({ reviewOnly: true })

      expect(api.world.listAliases).toHaveBeenCalledWith({
        novel_id: "p1",
        skip: 0,
        limit: 20,
        needs_review: true,
        q: "黑荆棘",
        source: "deep_import",
        workflow_id: "wf1",
        scene_index: 3,
        confidence_min: 0.8,
      })
    })

    it("同一对象的多个别名聚合显示", async () => {
      state.currentProjectId = "p1"
      api.world.listAliases.mockResolvedValue({
        items: [
          { alias: "愚者", alias_type: "title", entity_id: "e1", entity_name: "克莱恩" },
          { alias: "夏洛克", alias_type: "alias", entity_id: "e1", entity_name: "克莱恩" },
          { alias: "小太阳", alias_type: "nickname", entity_id: "e2", entity_name: "戴里克" },
        ],
      })

      const html = await worldView._renderAliases()

      expect(html.match(/克莱恩/g)).toHaveLength(1)
      expect(html).toContain('rowspan="2"')
      expect(html).toContain("2 个别名")
      expect(html).toContain("愚者")
      expect(html).toContain("夏洛克")
      expect(html).toContain("小太阳")
      expect(html).toContain('data-id="e1::愚者"')
      expect(html).toContain('data-id="e1::夏洛克"')
    })

    it("别名超过一页时显示分页并支持翻页", async () => {
      state.currentProjectId = "p1"
      api.world.listAliases.mockResolvedValue({
        items: [{ alias: "炎帝", alias_type: "title", entity_id: "e1" }],
        total: 22,
      })

      const html = await worldView._renderAliases()
      await worldView._changeAliasPage(1)

      expect(html).toContain('data-action="next-aliases-page"')
      expect(html).toContain("共 22 条")
      expect(worldView._aliasFilters.skip).toBe(20)
      expect(router.refresh).toHaveBeenCalled()
    })
  })

  describe("showAliasCreateForm", () => {
    it("调用 showModal", () => {
      worldView.showAliasCreateForm()
      expect(showModal).toHaveBeenCalled()
    })

    it("提交正确的别名载荷和 novel_id 查询参数", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{ id: "e1", name: "主角", entity_type: "character" }]
      api.world.createAlias.mockResolvedValue({ id: "a1" })
      worldView.showAliasCreateForm()

      const handler = captureModalHandler()
      document.body.innerHTML = `
        <select id="alias-entity"><option value="e1" selected>主角 (character)</option></select>
        <input id="alias-text" value="小名" />
        <select id="alias-type"><option value="nickname" selected>昵称</option></select>
      `
      await handler()

      expect(api.world.createAlias).toHaveBeenCalledWith(
        { entity_id: "e1", alias: "小名", alias_type: "nickname" },
        "p1",
      )
      expect(router.navigate).toHaveBeenCalledWith("world", "aliases")
    })
  })

  describe("deleteAlias", () => {
    it("调用 confirmAction 并显示别名", () => {
      worldView.deleteAlias("e1", "炎帝")
      expect(confirmAction).toHaveBeenCalled()
      const message = vi.mocked(confirmAction).mock.calls[0][0]
      expect(message).toContain("炎帝")
    })

    it("标记别名复核通过", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "aliases"
      api.world.updateAlias.mockResolvedValue({})
      api.world.listAliases.mockResolvedValue({
        items: [{ entity_id: "e1", entity_name: "炎帝", alias: "炎帝", status: "canonical", needs_review: false }],
        total: 1,
      })
      document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
      document.getElementById("workspace-content").scrollTop = 58

      await worldView._markAliasReviewed("e1", "炎帝")

      expect(api.world.updateAlias).toHaveBeenCalledWith("e1", "炎帝", {
        status: "canonical",
        needs_review: false,
        reviewed_at: expect.any(String),
        reviewed_by: "manual",
        reviewed_from: "world_aliases",
      }, { novel_id: "p1" })
      expect(toast).toHaveBeenCalledWith("别名已标记为已复核", "success")
      expect(router.refresh).not.toHaveBeenCalled()
      expect(document.getElementById("workspace-content").scrollTop).toBe(58)
    })

    it("别名复核失败显示反馈并消化 rejection", async () => {
      state.currentProjectId = "p1"
      api.world.updateAlias.mockRejectedValue(new Error("alias failed"))

      const result = await worldView._markAliasReviewed("e1", "炎帝")

      expect(result).toBe(false)
      expect(toast).toHaveBeenCalledWith("别名复核状态更新失败：alias failed", "error")
    })

    it("编辑并确认别名只提交目标、文本、类型和确认标记", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [
        { id: "e1", name: "值夜者", entity_type: "faction", status: "canonical" },
        { id: "e2", name: "黑荆棘安保公司", entity_type: "organization", status: "canonical" },
      ]
      worldView._aliases = [{
        entity_id: "e1",
        entity_name: "值夜者",
        alias: "黑荆棘安保公司",
        alias_type: "alias",
        status: "candidate",
        source: "deep_import",
        workflow_id: "wf-1",
        confidence: 0.95,
        quote: "证据文本",
        needs_review: true,
      }]
      api.world.editAlias.mockResolvedValue({ affected_ids: ["e1", "e2"] })

      worldView.showAliasReviewEditForm("e1", "黑荆棘安保公司")
      const body = showModal.mock.calls[0][1].html
      expect(body).toContain("证据文本")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <select id="alias-target-id"><option value="e2" selected>黑荆棘安保公司</option></select>
        <input id="alias-edit-text" value="黑荆棘" />
        <select id="alias-edit-type"><option value="name" selected>名称</option></select>
      `

      await handler()

      expect(api.world.editAlias).toHaveBeenCalledWith("e1", "黑荆棘安保公司", {
        target_entity_id: "e2",
        alias: "黑荆棘",
        alias_type: "name",
        confirm_review: true,
      }, { novel_id: "p1" })
      expect(api.world.editAlias.mock.calls[0][2]).not.toHaveProperty("source")
      expect(api.world.editAlias.mock.calls[0][2]).not.toHaveProperty("confidence")
      expect(api.world.editAlias.mock.calls[0][2]).not.toHaveProperty("quote")
    })

    it("候选可改目标、文本、类型后确认为别名并按 affected ids 刷新", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "candidates"
      worldView._entities = [
        { id: "e1", name: "值夜者", entity_type: "faction", status: "canonical" },
        { id: "e2", name: "黑荆棘安保公司", entity_type: "organization", status: "canonical" },
      ]
      worldView._candidates = [{
        id: "c1",
        name: "黑荆棘安保公司",
        entity_type: "organization",
        status: "candidate",
        content_json: {
          _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_name: "值夜者",
            source: "deep_import",
            workflow_id: "wf-1",
            confidence: 0.95,
            quote: "证据文本",
          },
        },
      }]
      worldView._candidateTotal = 1
      api.world.resolveEntityAsAlias.mockResolvedValue({
        affected_ids: ["c1", "e2"],
        merged_ids: ["c1"],
      })
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

      worldView.showResolveAliasForm("c1")
      const body = showModal.mock.calls[0][1].html
      expect(body).toContain("证据文本")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <select id="alias-target-id"><option value="e2" selected>黑荆棘安保公司</option></select>
        <input id="alias-edit-text" value="黑荆棘" />
        <select id="alias-edit-type"><option value="name" selected>名称</option></select>
      `

      await handler()

      expect(api.world.resolveEntityAsAlias).toHaveBeenCalledWith("c1", {
        target_entity_id: "e2",
        alias: "黑荆棘",
        alias_type: "name",
      }, "p1")
      expect(worldView._candidates).toEqual([])
      expect(router.navigate).toHaveBeenCalledWith("world", "candidates")
    })
  })
})

// ============================================================
// AI 自动识别
// ============================================================

describe("AI 自动识别", () => {
  describe("_toggleAutoExtract", () => {
    it("切换展开状态并刷新视图", () => {
      state.currentSubView = "objects"
      worldView._autoExtractOpen = false
      worldView._toggleAutoExtract()
      expect(worldView._autoExtractOpen).toBe(true)
      expect(router.refresh).toHaveBeenCalled()
    })
  })

  describe("_submitAutoExtract", () => {
    it("无项目显示警告", async () => {
      await worldView._submitAutoExtract("world_object_auto_extraction")
      expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("提交世界对象与别名关系阶段任务", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <input id="w-extract-start" value="1"/>
        <input id="w-extract-end" value="5"/>
      `
      api.imports.startStage.mockResolvedValue({ task_id: "t1" })

      await worldView._submitAutoExtract("world_object_auto_extraction")

      expect(api.imports.startStage).toHaveBeenCalledWith("world_objects", "p1", 1, 5)
      expect(api.world.extractEntities).not.toHaveBeenCalled()
      expect(api.world.extractAliasRelations).not.toHaveBeenCalled()
      expect(worldView._autoExtractTaskId).toBe("t1")
    })

    it("honors the passed taskType when mapping to a stage", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <input id="w-extract-start" value="2"/>
        <input id="w-extract-end" value="4"/>
      `
      api.imports.startStage.mockResolvedValue({ task_id: "t2" })

      await worldView._submitAutoExtract("plot_structure")

      expect(api.imports.startStage).toHaveBeenCalledWith("plot_structure", "p1", 2, 4)
      expect(worldView._autoExtractTaskId).toBe("t2")
    })
  })

  describe("_pollAutoExtract", () => {
    it("任务完成时清理定时器并刷新列表", async () => {
      worldView._autoExtractTimer = setInterval(() => {}, 1000)
      state.currentProjectId = "p1"
      api.tasks.get.mockResolvedValue({ task_id: "t1", task_type: "world_object_auto_extraction", status: "done" })
      api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "新实体" }] })

      await worldView._pollAutoExtract("t1")

      expect(worldView._autoExtractTimer).toBeNull()
      expect(localStorage.getItem("novel_world_extract_task")).toBeNull()
      expect(api.world.listEntities).toHaveBeenCalled()
    })

    it("任务失败时保留错误卡片并允许重新提交", async () => {
      worldView._autoExtractTaskId = "t-fail"
      api.tasks.get.mockResolvedValue({
        task_id: "t-fail",
        task_type: "world_object_auto_extraction",
        status: "failed",
        error_message: "章节范围为空",
      })

      await worldView._pollAutoExtract("t-fail")
      const html = worldView._renderAutoExtractPanel("world_object_auto_extraction", "世界对象与别名/关系自动提取")

      expect(html).toContain("章节范围为空")
      expect(html).toContain("开始提取")
      expect(html).not.toContain("disabled")
    })

    it("阶段面板显示统一提取按钮并随运行状态禁用", () => {
      let html = worldView._renderAutoExtractPanel(
        "world_object_auto_extraction",
        "世界对象与别名/关系自动提取",
      )

      expect(html).toContain("开始提取")
      expect(html).toContain('data-type="world_object_auto_extraction"')
      expect(html).not.toContain("补抽别名/关系")

      worldView._autoExtractTaskId = "running-task"
      worldView._autoExtractProgress = { terminal: false, failed: false }
      html = worldView._renderAutoExtractPanel(
        "world_object_auto_extraction",
        "世界对象与别名/关系自动提取",
      )

      expect(html).toContain("disabled")
    })

    it("onEnter 兼容恢复旧 JSON localStorage 任务并用 api.tasks.get 轮询", async () => {
      state.currentProjectId = "p1"
      localStorage.setItem("novel_world_extract_task", JSON.stringify({ taskId: "legacy-t", status: "running" }))
      api.tasks.get.mockResolvedValue({
        task_id: "legacy-t",
        task_type: "world_object_auto_extraction",
        status: "running",
        progress: null,
      })
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      api.world.listEntityBatches.mockResolvedValue([])

      await worldView.onEnter()

      expect(api.tasks.get).toHaveBeenCalledWith("legacy-t")
      expect(worldView._autoExtractTaskId).toBe("legacy-t")
      expect(localStorage.getItem("novel_world_extract_task")).toBeNull()
    })
  })
})

// ============================================================
// 合并、回滚与知识边界
// ============================================================

describe("合并、回滚与知识边界", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
  })

  it("合并目标列表不包含候选对象，避免候选互相合并后两条同时离开候选清洗", () => {
    const source = { id: "c1", name: "阿兹克", status: "candidate" }
    worldView._entities = [
      source,
      { id: "c2", name: "阿兹克", entity_type: "character", status: "candidate" },
      { id: "d1", name: "阿兹克", entity_type: "character", status: "draft" },
      { id: "k1", name: "阿兹克", entity_type: "character", status: "canonical" },
      { id: "i1", name: "阿兹克", entity_type: "character", status: "ignored" },
    ]

    const targets = worldView._mergeTargetCandidates(source, "", "阿兹克")

    expect(targets.map((item) => item.id)).toEqual(["d1", "k1"])
  })

  it.each([
    {
      name: "调用 API 并刷新",
      mock: () => {
        api.world.mergeEntity.mockResolvedValue({
          target_entity_id: "target-1",
          candidate_entity_id: "candidate-1",
          affected_ids: ["candidate-1", "target-1"],
        })
        api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      },
      expectedCall: ["candidate-1", "target-1", "p1"],
      expectedToast: ["实体已合并", "success"],
      refresh: true,
    },
    {
      name: "API 错误时显示错误提示",
      mock: () => api.world.mergeEntity.mockRejectedValue(new Error("合并失败")),
      expectedToast: ["合并失败", "error"],
    },
  ])("_mergeEntity $name", async ({ mock, expectedCall, expectedToast, refresh }) => {
    mock()
    await worldView._mergeEntity("candidate-1", "target-1")
    if (expectedCall) {
      expect(api.world.mergeEntity).toHaveBeenCalledWith(...expectedCall)
    }
    expect(toast).toHaveBeenCalledWith(...expectedToast)
    if (refresh) {
      expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
        novel_id: "p1",
        status: "candidate",
      }))
      expect(router.navigate).toHaveBeenCalledWith("world", "candidates")
    }
  })

  it("合并后只按 affected_ids 精确移除候选并重新拉取当前页", async () => {
    state.currentSubView = "candidates"
    worldView._candidates = [
      { id: "candidate-1", name: "阿兹克", status: "candidate" },
      { id: "candidate-2", name: "阿兹克", status: "candidate" },
    ]
    worldView._candidateTotal = 2
    api.world.mergeEntity.mockResolvedValue({
      target_entity_id: "target-1",
      candidate_entity_id: "candidate-1",
      affected_ids: ["candidate-1", "target-1"],
    })
    api.world.listEntities
      .mockResolvedValueOnce({
        items: [{ id: "candidate-2", name: "阿兹克", status: "candidate" }],
        total: 1,
      })
      .mockResolvedValueOnce({ items: [], total: 0 })

    await worldView._mergeEntity("candidate-1", "target-1")

    expect(worldView._candidates.map((item) => item.id)).toEqual(["candidate-2"])
    expect(worldView._candidateTotal).toBe(1)
    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      status: "candidate",
    }))
    expect(router.navigate).toHaveBeenCalledWith("world", "candidates")
  })

  it("AI 合并建议使用稳定 key 而不是数组下标提交 payload", async () => {
    worldView._fusionProgress = {
      raw: {
        result: {
          suggestions: [
            {
              action: "merge",
              source_entity_id: "source-1",
              target_entity_id: "target-1",
              source_entity_name: "黑荆棘安保公司",
              target_entity_name: "值夜者",
              alias: "黑荆棘",
              requires_canonical_confirmation: true,
              confidence: 0.93,
            },
            {
              action: "needs_review",
              source_entity_id: "source-2",
              target_entity_id: "target-2",
              source_entity_name: "伦纳德",
              target_entity_name: "克莱恩",
              confidence: 0.4,
            },
          ],
        },
      },
    }
    api.world.applyEntityFusionSuggestions.mockResolvedValue({ applied: 1 })
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    worldView._showEntityFusionSuggestions()

    const modal = showModal.mock.calls.at(-1)
    const html = modal[1].html
    expect(html).toContain("data-fusion-key")
    expect(html).not.toContain("data-fusion-index")
    expect(modal[3]).toEqual({ size: "large" })

    document.body.innerHTML = html
    document.querySelector("[data-canonical-merge]").checked = true
    await modal[2][0].handler()

    expect(api.world.applyEntityFusionSuggestions).toHaveBeenCalledWith({
      novel_id: "p1",
      confirmed: true,
      suggestions: [{
        action: "merge",
        source_entity_id: "source-1",
        target_entity_id: "target-1",
        alias: "黑荆棘",
        allow_canonical_merge: true,
      }],
    })
  })

  it.each([
    {
      name: "调用 API 并刷新（无警告）",
      mock: () => api.world.rollbackEntity.mockResolvedValue({}),
      expectedCall: ["entity-1", 12, "p1"],
      expectedToast: ["回滚完成", "success"],
      refresh: true,
    },
    {
      name: "显示警告当结果含 warnings",
      mock: () => api.world.rollbackEntity.mockResolvedValue({ warnings: ["某字段缺失"] }),
      expectedToast: ["回滚完成，存在警告", "warning"],
    },
    {
      name: "API 错误时显示错误提示",
      mock: () => api.world.rollbackEntity.mockRejectedValue(new Error("回滚失败")),
      expectedToast: ["回滚失败", "error"],
    },
  ])("_rollbackEntity $name", async ({ mock, expectedCall, expectedToast, refresh }) => {
    mock()
    await worldView._rollbackEntity("entity-1", 12)
    if (expectedCall) {
      expect(api.world.rollbackEntity).toHaveBeenCalledWith(...expectedCall)
    }
    expect(toast).toHaveBeenCalledWith(...expectedToast)
    if (refresh) {
      expect(router.refresh).toHaveBeenCalled()
    }
  })

  it.each([
    {
      name: "校验 false_belief 必须填写误解",
      payload: { target_entity_id: "entity-1", knowledge_level: "false_belief", known_content: "他以为真相如此" },
      expectedToast: ["错误认知必须填写误解内容", "warning"],
      apiCalled: false,
    },
    {
      name: "调用 API 并刷新",
      mock: () => api.world.createKnowledge.mockResolvedValue({ id: "k1" }),
      payload: { target_entity_id: "entity-1", knowledge_level: "false_belief", known_content: "他以为真相如此", misconception: "错误认知" },
      expectedToast: ["知识边界已添加", "success"],
      apiCalled: true,
      refresh: true,
    },
    {
      name: "API 错误时显示错误提示",
      mock: () => api.world.createKnowledge.mockRejectedValue(new Error("创建失败")),
      payload: { target_entity_id: "entity-1", knowledge_level: "full", known_content: "他知道真相" },
      expectedToast: ["创建失败", "error"],
      apiCalled: true,
    },
  ])("_createKnowledge $name", async ({ mock, payload, expectedToast, apiCalled, refresh }) => {
    if (mock) mock()
    await worldView._createKnowledge("char-1", payload)
    if (apiCalled) {
      expect(api.world.createKnowledge).toHaveBeenCalled()
    } else {
      expect(api.world.createKnowledge).not.toHaveBeenCalled()
    }
    expect(toast).toHaveBeenCalledWith(...expectedToast)
    if (refresh) {
      expect(router.refresh).toHaveBeenCalled()
    }
  })
})

// ============================================================
// 事件绑定
// ============================================================

describe("_bindEvents", () => {
  it("导航子视图", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="nav-objects">对象库</button></div>'
    worldView._bindEvents()
    document.querySelector("button").click()
    expect(router.navigate).toHaveBeenCalledWith("world", "objects")
  })

  it("编辑实体", () => {
    const spy = vi.spyOn(worldView, "editEntity").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><button data-action="edit-entity" data-id="e1">编辑</button></div>'
    worldView._bindEvents()
    document.querySelector("button").click()
    expect(spy).toHaveBeenCalledWith("e1")
    spy.mockRestore()
  })
})

describe("批量操作", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
    worldView._bulkSelections = {}
  })

  it("对象库批量删除调用现有单项 API", async () => {
    worldView._entities = [
      { id: "e1", name: "王都" },
      { id: "e2", name: "旧城" },
    ]
    worldView._bulkSelections["world-objects"] = new Set(["e1", "e2"])
    api.world.deleteEntity.mockResolvedValue({})

    await worldView._executeBulkAction("world-objects", "delete-entities", worldView._itemsForBulkScope("world-objects"))

    expect(api.world.deleteEntity).toHaveBeenCalledWith("e1", "p1")
    expect(api.world.deleteEntity).toHaveBeenCalledWith("e2", "p1")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
  })

  it("对象库单项复核更新 content_json._meta", async () => {
    state.currentProjectId = "p1"
    worldView._entities = [{
      id: "e1",
      name: "王都",
      needs_review: true,
      content_json: { aliases: ["王城"], _meta: { source: "deep_import", needs_review: true } },
    }]
    api.world.getEntity.mockResolvedValue({
      id: "e1",
      name: "王都",
      content_json: { aliases: ["王城"], _meta: { source: "deep_import", needs_review: true } },
    })
    api.world.updateEntity.mockResolvedValue({})
    api.world.listEntities
      .mockResolvedValueOnce({
        items: [{
          id: "e1",
          name: "王都",
          needs_review: false,
          content_json: { aliases: ["王城"], _meta: { source: "deep_import", needs_review: false } },
        }],
        total: 1,
      })
      .mockResolvedValueOnce({ items: [], total: 0 })
    document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
    document.getElementById("workspace-content").scrollTop = 88

    await worldView._markEntityReviewed("e1")

    expect(api.world.updateEntity).toHaveBeenCalledWith("e1", {
      content_json: {
        aliases: ["王城"],
        _meta: expect.objectContaining({
          source: "deep_import",
          needs_review: false,
          reviewed_at: expect.any(String),
          reviewed_by: "manual",
          reviewed_from: "world_objects",
        }),
      },
    }, "p1")
    expect(toast).toHaveBeenCalledWith("世界对象已标记为已复核", "success")
    expect(router.refresh).not.toHaveBeenCalled()
    expect(document.getElementById("workspace-content").scrollTop).toBe(88)
  })

  it("对象复核失败显示反馈并消化 rejection", async () => {
    state.currentProjectId = "p1"
    worldView._entities = [{ id: "e1", name: "王都", content_json: { _meta: { needs_review: true } } }]
    api.world.getEntity.mockResolvedValue({ id: "e1", name: "王都", content_json: { _meta: { needs_review: true } } })
    api.world.updateEntity.mockRejectedValue(new Error("entity failed"))

    const result = await worldView._markEntityReviewed("e1")

    expect(result).toBe(false)
    expect(toast).toHaveBeenCalledWith("世界对象复核状态更新失败：entity failed", "error")
  })

  it("对象库批量复核调用现有更新 API", async () => {
    worldView._entities = [
      { id: "e1", name: "王都", content_json: { _meta: { source: "deep_import", needs_review: true } } },
      { id: "e2", name: "旧城", content_json: { _meta: { source: "manual", needs_review: true } } },
    ]
    worldView._bulkSelections["world-objects"] = new Set(["e1", "e2"])
    api.world.updateEntity.mockResolvedValue({})

    await worldView._executeBulkAction("world-objects", "review-entities", worldView._itemsForBulkScope("world-objects"))

    expect(api.world.updateEntity).toHaveBeenCalledTimes(2)
    expect(api.world.updateEntity).toHaveBeenCalledWith("e1", {
      content_json: {
        _meta: expect.objectContaining({
          source: "deep_import",
          needs_review: false,
          reviewed_from: "world_objects_bulk",
        }),
      },
    }, "p1")
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
  })

  it("关系和别名批量复核调用对应 API", async () => {
    worldView._relations = [{ id: "r1", relation_type: "ally_of", status: "candidate" }]
    worldView._aliases = [{ entity_id: "e1", alias: "炎帝", status: "candidate", needs_review: true }]
    worldView._bulkSelections["world-relations"] = new Set(["r1"])
    worldView._bulkSelections["world-aliases"] = new Set(["e1::炎帝"])
    api.world.reviewEditRelationship.mockResolvedValue({})
    api.world.updateAlias.mockResolvedValue({})

    await worldView._executeBulkAction("world-relations", "review-relations", worldView._itemsForBulkScope("world-relations"))
    await worldView._executeBulkAction("world-aliases", "review-aliases", worldView._itemsForBulkScope("world-aliases"))

    expect(api.world.reviewEditRelationship).toHaveBeenCalledWith("r1", { confirm_review: true }, "p1")
    expect(api.world.updateAlias).toHaveBeenCalledWith("e1", "炎帝", expect.objectContaining({
      status: "canonical",
      needs_review: false,
      reviewed_from: "world_aliases_bulk",
    }), { novel_id: "p1" })
  })

  it("候选清洗批量确认只处理 create_new 类候选", async () => {
    worldView._candidates = [
      { id: "c1", name: "新对象", content_json: { _meta: { suggested_action: "create_new" } } },
      { id: "c2", name: "别名", content_json: { _meta: { suggested_action: "alias_of_existing" } } },
    ]
    worldView._bulkSelections["world-candidates"] = new Set(["c1", "c2"])
    api.world.promoteEntity.mockResolvedValue({})

    await worldView._executeBulkAction("world-candidates", "accept-candidates", worldView._itemsForBulkScope("world-candidates"))

    expect(api.world.promoteEntity).toHaveBeenCalledTimes(1)
    expect(api.world.promoteEntity).toHaveBeenCalledWith("c1", "p1")
  })

  it("点击对象多选不重绘页面也不强制刷新数据", () => {
    const input = document.createElement("input")
    input.setAttribute("data-scope", "world-objects")
    input.setAttribute("data-id", "e1")
    input.checked = true

    worldView._toggleBulkOne(input)

    expect(worldView._bulkSelections["world-objects"]).toEqual(new Set(["e1"]))
    expect(router.renderCurrentView).not.toHaveBeenCalled()
    expect(router.refresh).not.toHaveBeenCalled()
  })
})
