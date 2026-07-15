/**
 * worldView 测试
 *
 * 覆盖生命周期、3 个子视图（候选清洗已移除）、实体 CRUD、关系和别名管理。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import worldView from "../views/worldView.js"
import worldBibleView from "../views/worldBibleView.js"
import { resetState, autoConfirm, captureModalHandler, renderHtml } from "./helpers.js"

beforeEach(() => {
  resetState()
  worldView._entities = []
  worldView._candidates = []
  worldView._candidateTotal = 0
  worldView._candidateLoadError = null
  worldView._batches = []
  worldView._relations = []
  worldView._relationGroups = []
  worldView._relationTotal = 0
  worldView._relationGroupTotal = 0
  worldView._relationFilters = { skip: 0, limit: 20, q: "", relation_type: "" }
  worldView._aliases = []
  worldView._aliasGroups = []
  worldView._aliasTotal = 0
  worldView._aliasGroupTotal = 0
  worldView._aliasFilters = { skip: 0, limit: 20, q: "" }
  worldView._relationReviewDrafts = {}
  worldView._aliasReviewDrafts = {}
  worldView._relationReviewErrors = {}
  worldView._aliasReviewErrors = {}
  worldView._reviewCounts = { objects: 0, aliases: 0, relations: 0 }
  worldView._reviewTypeCatalog = {
    custom_allowed: true,
    relation_types: [{ value: "friend_of", label: "朋友", category: "社会", synonyms: ["朋友"] }],
    alias_types: [{ value: "alias", label: "别名", category: "别名", synonyms: ["别称"] }],
  }
  worldView._candidateFilters = { skip: 0, limit: 20 }
  worldView._total = 0
  worldView._entitiesLoadError = null
  worldView._filters = { entity_type: "", display_state: "active", q: "", skip: 0, limit: 20 }
  worldView._objectViewMode = "table"
  worldView._advancedFiltersOpen = false
  worldView._filterPanelsOpen = {
    objects: false,
    "review-objects": false,
    "review-aliases": false,
    "review-relations": false,
  }
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
  worldView._lifecycleEpoch = 0
  worldView._eventsBound = false
  localStorage.removeItem("novel_world_extract_task")
  localStorage.removeItem("novel_active_workflows_v1")
  localStorage.removeItem("novel_world_filter_panels:p1")
  localStorage.removeItem("novel_world_filter_panels:p2")
  vi.clearAllMocks()
  api.world.getReviewTypeCatalog.mockReset().mockResolvedValue(worldView._reviewTypeCatalog)
  api.world.listRelationReviewGroups.mockReset().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
  api.world.reviewRelationsBatch.mockReset()
  api.world.listAliasReviewGroups.mockReset().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
  api.world.reviewAliasesBatch.mockReset()
  router.refresh.mockReset()
  api.world.getEntityMapPresence.mockReset().mockResolvedValue({ items: [], total: 0 })
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("加载项目类型目录并保留自定义类型用于筛选", async () => {
    state.currentProjectId = "p1"
    api.world.listEntityTypes.mockResolvedValue({
      items: [
        { value: "character", label: "人物", kind: "system" },
        { value: "宗教/神祇", label: "宗教/神祇", kind: "custom" },
      ],
    })
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
    api.world.listEntityBatches.mockResolvedValue([])

    await worldView.onEnter()

    expect(api.world.listEntityTypes).toHaveBeenCalledWith("p1")
    expect(worldView._entityTypes).toContainEqual({
      value: "宗教/神祇",
      label: "宗教/神祇",
      kind: "custom",
    })
    worldView._filters.entity_type = "宗教/神祇"
    expect(worldView._renderFilters()).toContain('value="宗教/神祇" selected')
  })

  it("加载实体列表和批次信息", async () => {
    state.currentProjectId = "p1"
    api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "王都" }], total: 1 })
    api.world.listEntityBatches.mockResolvedValue([{ batch_id: "b1", entities: [{ id: "e1", name: "王都", entity_type: "location" }] }])

    await worldView.onEnter()

    expect(api.world.listEntities).toHaveBeenCalledWith({ novel_id: "p1", display_state: "active", skip: 0, limit: 20 })
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "p1",
      display_state: "review",
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

describe("对象库搜索", () => {
  it("回车会应用模糊搜索筛选", async () => {
    state.currentProjectId = "p1"
    document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
    worldView._bindEvents()
    const input = document.getElementById("filter-q")
    input.value = "值夜着"
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))

    await vi.waitFor(() => {
      expect(router.navigate).toHaveBeenCalledWith(
        "world",
        "objects",
        true,
        expect.any(URLSearchParams),
      )
    })
    expect(router.getCurrentQuery().get("q")).toBe("值夜着")
  })

  it("应用筛选时由路由 query 触发数据重载", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "objects"
    document.body.innerHTML = `
      <select id="filter-entity-type"><option value="location" selected>location</option></select>
      <select id="filter-display-state"><option value="active" selected>active</option></select>
      <input id="filter-q" value="王都">
    `
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    await worldView._applyFilters()

    expect(worldView._filters).toMatchObject({ entity_type: "", q: "", skip: 0 })
    expect(router.getCurrentQuery().get("entity_type")).toBe("location")
    expect(router.getCurrentQuery().get("q")).toBe("王都")

    await worldView.render()

    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      entity_type: "location",
      display_state: "active",
      q: "王都",
      skip: 0,
      limit: 20,
    }))
  })

  it("重置筛选时在路由同步前保留已加载状态", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "objects"
    worldView._filters = {
      entity_type: "location",
      display_state: "review",
      q: "王都",
      skip: 20,
      limit: 20,
    }
    worldView._objectViewMode = "card"
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    await worldView._resetFilters()

    expect(worldView._filters).toMatchObject({ entity_type: "location", q: "王都", skip: 20 })
    expect(worldView._advancedFiltersOpen).toBe(false)
    expect(router.getCurrentQuery().toString()).toBe("display_state=active")

    await worldView.render()

    expect(worldView._filters).toMatchObject({ entity_type: "", display_state: "active", q: "", skip: 0 })
    expect(worldView._objectViewMode).toBe("table")
    expect(api.world.listEntities).toHaveBeenCalledWith({
      novel_id: "p1",
      display_state: "active",
      skip: 0,
      limit: 20,
    })
  })

  it("翻页时在路由同步后使用新的 skip 重载", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "objects"
    worldView._total = 22
    api.world.listEntities.mockResolvedValue({ items: [], total: 22 })

    await worldView._changePage(1)

    expect(worldView._filters.skip).toBe(0)
    expect(router.getCurrentQuery().get("page")).toBe("2")

    await worldView.render()

    expect(worldView._filters.skip).toBe(20)
    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      display_state: "active",
      skip: 20,
      limit: 20,
    }))
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

  it("世界书子视图委托未保存离开门禁", () => {
    state.currentSubView = "bible"
    const guard = vi.spyOn(worldBibleView, "canLeave").mockReturnValue(false)

    expect(worldView.canLeave()).toBe(false)
    expect(guard).toHaveBeenCalledOnce()

    state.currentSubView = "objects"
    expect(worldView.canLeave()).toBe(true)
    guard.mockRestore()
  })
})

// ============================================================
// render
// ============================================================

describe("worldView render", () => {
  it("渲染子标签导航（包含待处理入口）", async () => {
    const html = await worldView.render()
    expect(html).toContain("对象库")
    expect(html).toContain("待处理")
    expect(html).toContain("关系")
    expect(html).toContain("别名")
  })

  it("待处理入口渲染对象/别名/关系三子 tab", async () => {
    state.currentSubView = "review-objects"
    worldView._candidates = [{ id: "c1", name: "候选对象", entity_type: "item", status: "candidate" }]
    const html = await worldView.render()
    expect(html).toContain("对象")
    expect(html).toContain("别名")
    expect(html).toContain("关系")
    expect(html).toContain("候选对象")
  })

  it("旧 candidates 子路由仍渲染待处理对象队列", async () => {
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

    expect(router.navigate).toHaveBeenCalledWith(
      "map",
      null,
      true,
      expect.any(URLSearchParams),
    )
    expect(router.navigate.mock.calls.at(-1)[3].toString()).toBe("mode=overview")
  })

  it("对象库渲染顶部工具栏，包含新建对象、自动提取和视图切换", async () => {
    state.currentProjectId = "p1"
    worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical" }]
    worldView._total = 1
    const html = await worldView.render()

    expect(html).toContain("world-toolbar")
    expect(html).toContain("世界对象")
    expect(html).toContain("btn-new-entity")
    expect(html).toContain('data-action="toggle-extract"')
    expect(html).toContain('data-action="set-object-view"')
  })

  it("自动提取面板默认收起，点击 toggle 后展开", async () => {
    state.currentProjectId = "p1"
    worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical" }]
    worldView._autoExtractOpen = false

    document.body.innerHTML = `<main id="workspace-content">${await worldView.render()}</main>`
    worldView._bindEvents()
    expect(document.querySelector(".world-extract-drawer")).toBeNull()

    document.querySelector('[data-action="toggle-extract"]')?.click()
    expect(worldView._autoExtractOpen).toBe(true)
  })

  it("工具栏显示当前项目名称", async () => {
    state.currentProjectId = "p1"
    state.currentProject = { id: "p1", title: "测试项目" }
    worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical" }]

    const html = await worldView.render()

    expect(html).toContain("测试项目")
    expect(html).toContain("view-toolbar__project")
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

  it("对象库将 resolved_as alias 的 merged 对象归入历史", () => {
    worldView._entities = [{
      id: "e1",
      name: "黑荆棘安保公司",
      entity_type: "organization",
      status: "merged",
      content_json: { resolved_as: "alias", merged_into: "target" },
    }]

    const html = worldView._renderEntityList()

    expect(html).toContain("历史")
    expect(html).not.toContain("已确认为别名")
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
      display_state: "review",
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
      display_state: "review",
      q: "克莱恩",
      source: "deep_import",
      workflow_id: "wf-1",
      needs_review: true,
      auto_ingested: true,
      skip: 40,
      limit: 20,
    }))
  })

  it("从 URL query 恢复待处理对象筛选和分页", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "review-objects"
    router.navigate("world", "review-objects", true, new URLSearchParams({
      entity_type: "location",
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
      entity_type: "location",
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
      entity_type: "location",
    }))
    expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      display_state: "review",
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

    it("待处理对象筛选参数传给 entities API", async () => {
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
        display_state: "review",
        skip: 0,
        limit: 20,
        suggested_action: "link_to_existing",
        source: "deep_import",
        workflow_id: "wf1",
        scene_index: 2,
        confidence_min: 0.8,
      })
    })

    it("加载失败保留可见错误和重试入口", async () => {
      state.currentProjectId = "p1"
      api.world.listEntities.mockRejectedValue(new Error("网络中断"))

      await worldView._loadCandidates()

      expect(worldView._candidateLoadError).toBe("网络中断")
      expect(worldView._renderCandidatesList()).toContain("retry-candidate-load")
      expect(toast).toHaveBeenCalledWith("待处理对象加载失败，可重试", "warning")
    })
  })

  describe("_renderCandidatesList", () => {
    it("空列表显示空状态", () => {
      const html = worldView._renderCandidatesList()
      expect(html).toContain("没有待处理对象")
    })

    it("别名建议显示目标对象名称并提供设为别名入口", () => {
      worldView._candidates = [{
        id: "c1",
        name: "岚姐",
        entity_type: "character",
        display_state: "review",
        content_json: {
          _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_id: "e-target",
            suggested_existing_entity_name: "林岚",
          },
        },
      }]

      const html = worldView._renderCandidatesList()

      expect(html).toContain("作为林岚别名")
      expect(html).toContain("candidate-action-badge")
      expect(html).toContain('data-action="resolve-candidate-alias"')
      expect(html).toContain("设为别名")
      expect(html).toContain("编辑后采用")
      expect(html).not.toContain('data-action="merge-entity"')
      expect(html).toContain('data-target-name="林岚"')
      expect(html).toContain("全选当前待处理项")
      expect(html).toContain('class="world-candidate-alias-group"')
      expect(html).toContain('data-target-id="e-target"')
      expect(html).toContain("已有对象")
      expect(html).not.toContain('<tr data-id="c1"')
    })

    it("按建议目标把多个别名候选合并到同一展示组", () => {
      worldView._candidates = [
        {
          id: "c1",
          name: "岚姐",
          entity_type: "character",
          status: "candidate",
          content_json: { _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_id: "e1",
            suggested_existing_entity_name: "林岚",
          } },
        },
        {
          id: "c2",
          name: "小岚",
          entity_type: "character",
          status: "candidate",
          content_json: { _meta: {
            suggested_action: "alias_of_existing",
            suggested_existing_entity_id: "e1",
            suggested_existing_entity_name: "林岚",
          } },
        },
      ]

      const html = worldView._renderCandidatesList()

      expect(html.match(/data-target-id="e1"/g)).toHaveLength(1)
      expect(html).toContain("岚姐")
      expect(html).toContain("小岚")
      expect(html).toContain("以下 2 个候选建议作为林岚别名")
    })

    it("目标只有名称或指向候选自身时不标记为已有对象", () => {
      worldView._candidates = [
        {
          id: "c1",
          name: "黑荆棘安保公司",
          entity_type: "faction",
          status: "candidate",
          content_json: { _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_name: "黑荆棘安保公司",
          } },
        },
        {
          id: "c2",
          name: "廷根值夜者小队",
          entity_type: "faction",
          status: "candidate",
          content_json: { _meta: {
            suggested_action: "link_to_existing",
            suggested_existing_entity_id: "c2",
            suggested_existing_entity_name: "廷根值夜者小队",
          } },
        },
      ]

      const html = worldView._renderCandidatesList()

      expect(html).not.toContain("已有对象")
      expect(html).not.toContain('class="world-candidate-alias-group"')
      expect(html).toContain('<tr data-id="c1"')
      expect(html).toContain('<tr data-id="c2"')
      expect(html).toContain('data-action="resolve-candidate-alias"')
    })

    it("同类型的高相似名称直接合并展示但不自动裁决", () => {
      worldView._candidates = [
        { id: "c1", name: "克莱恩", entity_type: "character", status: "candidate" },
        { id: "c2", name: "克莱恩·莫雷蒂", entity_type: "character", status: "candidate" },
        { id: "c3", name: "克莱恩的穿越秘密", entity_type: "secret", status: "candidate" },
      ]

      const html = worldView._renderCandidatesList()
      const similarGroup = html.match(
        /<section class="world-candidate-alias-group world-candidate-similar-group">([\s\S]*?)<\/section>/,
      )?.[1] || ""

      expect(similarGroup).toContain("克莱恩")
      expect(similarGroup).toContain("克莱恩·莫雷蒂")
      expect(similarGroup).not.toContain("克莱恩的穿越秘密")
      expect(similarGroup).toContain('data-action="resolve-candidate-alias"')
      expect(similarGroup).toContain('data-action="merge-entity"')
      expect(html).toContain("合并展示，请逐条决定")
    })

    it("temporary_only 候选显示设为临时且不显示提升按钮", () => {
      worldView._candidates = [{
        id: "c1",
        name: "临时钥匙",
        entity_type: "item",
        display_state: "review",
        content_json: { _meta: { suggested_action: "temporary_only" } },
      }]

      const html = worldView._renderCandidatesList()

      expect(html).toContain("设为临时")
      expect(html).toContain('data-action="ignore-candidate"')
      expect(html).not.toContain('data-action="accept-candidate"')
    })

    it("建议兼容影子通过队列暴露完整裁决动作", () => {
      worldView._candidates = [{
        id: "shadow-1",
        name: "星门",
        entity_type: "location",
        status: "candidate",
        content_json: {
          _meta: {
            compatibility_shadow: true,
            suggestion_id: "suggestion-1",
            suggested_action: "merge_with_existing",
          },
        },
      }]

      const html = worldView._renderCandidatesList()

      expect(html).toContain('data-action="accept-candidate"')
      expect(html).toContain('data-action="ignore-candidate"')
      expect(html).toContain('data-action="edit-entity"')
      expect(html).toContain("编辑后采用")
      expect(html).toContain('data-action="merge-entity"')
      expect(html).toContain('data-action="resolve-candidate-alias"')
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
        display_state: "review",
        skip: 20,
        limit: 20,
      })
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(router.navigate).toHaveBeenCalledWith("world", "review-objects", true, expect.any(URLSearchParams))
      expect(query.get("page")).toBe("2")
    })
  })

  describe("_applyCandidateReviewFilters", () => {
    it("待处理对象筛选写入 URL query", async () => {
      state.currentSubView = "review-objects"
      document.body.innerHTML = `
        <select id="review-candidate-entity-type"><option value="location" selected>地点</option></select>
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
      expect(query.get("entity_type")).toBe("location")
      expect(query.get("suggested_action")).toBe("link_to_existing")
      expect(query.get("source")).toBe("deep_import")
      expect(query.get("workflow_id")).toBe("wf-12")
      expect(query.get("scene_index")).toBe("4")
      expect(query.get("source_chapter_index")).toBe("2")
      expect(query.get("confidence_min")).toBe("0.7")
      expect(query.get("confidence_max")).toBe("0.95")
      expect(query.get("page")).toBeNull()
    })

    it("重置待处理对象筛选会清空 URL query", async () => {
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

    it("全部类型可单独清除 location 深链且保留 workflow", async () => {
      state.currentSubView = "review-objects"
      worldView._candidateFilters = {
        skip: 0,
        limit: 20,
        entity_type: "location",
        source: "deep_import",
        workflow_id: "wf-location",
      }
      document.body.innerHTML = `
        <select id="review-candidate-entity-type"><option value="" selected>全部类型</option></select>
        <input id="review-candidate-source" value="deep_import" />
        <input id="review-candidate-workflow" value="wf-location" />
      `

      await worldView._applyCandidateReviewFilters()

      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("entity_type")).toBeNull()
      expect(query.get("source")).toBe("deep_import")
      expect(query.get("workflow_id")).toBe("wf-location")
    })
  })

  describe("acceptCandidate", () => {
    it("采用 create_new 建议时刷新待处理列表", async () => {
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
        display_state: "review",
      }))
    })

    it("兼容影子采用走权威建议队列", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "shadow-1",
        name: "星门",
        status: "candidate",
        content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
      }]
      api.world.confirmSuggestion.mockResolvedValue({})
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      autoConfirm()

      await worldView.acceptCandidate("shadow-1")

      expect(api.world.confirmSuggestion).toHaveBeenCalledWith("s1", "p1")
      expect(api.world.promoteEntity).not.toHaveBeenCalled()
      expect(api.world.updateEntity).not.toHaveBeenCalled()
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
        display_state: "review",
      }))
    })

    it("兼容影子忽略走权威建议队列", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "shadow-1",
        name: "星门",
        status: "candidate",
        content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
      }]
      api.world.rejectSuggestion.mockResolvedValue({})
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      autoConfirm()

      await worldView.ignoreCandidate("shadow-1")

      expect(api.world.rejectSuggestion).toHaveBeenCalledWith("s1", "p1")
      expect(api.world.updateEntity).not.toHaveBeenCalled()
      expect(api.world.deleteEntity).not.toHaveBeenCalled()
    })
  })
})

// ============================================================
// 对象库
// ============================================================

describe("对象库", () => {
  describe("_renderEntityList", () => {
    it("空列表显示空状态", async () => {
      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      expect(html).toContain("还没有世界对象")
      expect(html).toContain('data-action="new"')
      const fullHtml = await worldView.render()
      const fullContainer = renderHtml(fullHtml)
      expect(fullContainer.querySelector("[data-action='toggle-extract']")).toBeTruthy()
      expect(container.querySelector(".empty-state [data-action='toggle-extract']")).toBeNull()
    })

    it("渲染实体表格", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]
      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      const row = [...container.querySelectorAll("tr")]
        .find((tr) => tr.textContent.includes("王都"))

      expect(row?.textContent).toContain("location")
      expect(row?.textContent).toContain("已采用")
      expect(row?.querySelector('[data-action="edit-entity"]')).toBeTruthy()
      expect(row?.querySelector('[data-action="open-entity-map"]')).toBeTruthy()
      expect(row?.querySelector('[data-action="delete-entity"]')).toBeTruthy()
    })

    it("从 content_json._meta 渲染对象注意原因", () => {
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

      expect(row?.textContent).toContain("需要人工检查")
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
      expect(badge?.textContent).toContain("待处理")
      expect(container.textContent).not.toContain('onclick="alert(1)')
    })

    it("卡片视图复用现有编辑和地图操作", async () => {
      worldView._objectViewMode = "card"
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]

      const html = worldView._renderEntityList()
      const container = renderHtml(html)
      const card = container.querySelector(".world-object-card")

      const fullHtml = await worldView.render()
      expect(fullHtml).toContain('data-action="set-object-view"')
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
      expect(badge?.textContent).toContain("待处理")
      expect(container.textContent).not.toContain('onclick="alert(1)')
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

    it("对象只有一个地图 presence 时直接定位该地图", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
      state.currentProjectId = "p1"
      worldView._entities = [{ id: "e1", status: "canonical" }]
      api.world.getEntityMapPresence.mockResolvedValue({
        items: [{
          map_id: "m2",
          map_name: "王都详图",
          roles: ["location"],
          representative_hex_q: 12,
          representative_hex_r: 9,
          open_target: { mode: "live", map_id: "m2", focus_entity_id: "e1" },
        }],
      })

      await worldView._openEntityMap("e1")

      expect(api.world.getMapOpenTarget).not.toHaveBeenCalled()
      expect(openSpy).toHaveBeenCalledWith(
        "#workbench/p1/map?map_id=m2&focus_entity_id=e1&focus_hex_q=12&focus_hex_r=9&mode=live",
        "_blank",
        "noopener",
      )
      openSpy.mockRestore()
    })

    it("对象关联多个地图时展示角色与绑定数量选择器", async () => {
      state.currentProjectId = "p1"
      api.world.getEntityMapPresence.mockResolvedValue({
        items: [
          { map_id: "m1", map_name: "世界", roles: ["marker.character"], binding_count: 1 },
          { map_id: "m2", map_name: "王都", roles: ["location", "territory"], binding_count: 8 },
        ],
      })

      await worldView._openEntityMap("e1")

      const [, body] = showModalHtml.mock.calls.at(-1)
      expect(body).toContain("世界")
      expect(body).toContain("人物标记")
      expect(body).toContain("8 个空间绑定")
    })

    it("同一地图的多条线路 presence 可逐条打开并激活所在楼层", async () => {
      const openSpy = vi.spyOn(window, "open").mockImplementation(() => null)
      showModalHtml.mockImplementationOnce((_title, body) => {
        document.body.innerHTML = body
      })
      state.currentProjectId = "p1"
      worldView._entities = [{ id: "e1", status: "canonical" }]
      api.world.getEntityMapPresence.mockResolvedValue({
        items: [{
          map_id: "m1",
          map_name: "地下城",
          roles: ["path.start"],
          representative_world_q: 1.5,
          representative_world_r: 2.25,
          path_refs: [
            { path_id: "p-a", path_name: "上层通道", layer_node_id: "floor-a", roles: ["path.start"] },
            { path_id: "p-b", path_name: "下层河道", layer_node_id: "floor-b", roles: ["path.end"] },
          ],
        }],
      })

      await worldView._openEntityMap("e1")
      const [, body] = showModalHtml.mock.calls.at(-1)
      expect(body).toContain("上层通道")
      expect(body).toContain("下层河道")
      expect(body).toContain("线路起点")
      expect(body).toContain("线路终点")

      document.querySelector("[data-map-presence-index='1']").click()
      expect(openSpy.mock.calls.at(-1)[0]).toContain("focus_path_id=p-b")
      expect(openSpy.mock.calls.at(-1)[0]).toContain("focus_layer_node_id=floor-b")
      expect(openSpy.mock.calls.at(-1)[0]).not.toContain("focus_hex_q")
      expect(openSpy.mock.calls.at(-1)[0]).not.toContain("focus_hex_r")
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
      expect(html).toContain("确认并开始提取")
      expect(html).toContain("自动采用通过门禁")
      expect(html).toContain("进入待处理")
    })

    it("渲染过滤栏与分页", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]
      worldView._total = 30
      const html = worldView._renderEntityList()
      expect(html).toContain("filter-entity-type")
      expect(html).toContain("filter-display-state")
      expect(html).toContain("filter-q")
      expect(html).toContain("apply-filters")
      expect(html).toContain("reset-filters")
      expect(html).toContain("展开筛选")
      expect(html).toContain("prev-page")
      expect(html).toContain("next-page")
    })

    it("卡片视图在批量工具条提供全选当前页", () => {
      worldView._objectViewMode = "card"
      worldView._entities = [
        { id: "e1", name: "王都", entity_type: "location", status: "canonical" },
        { id: "e2", name: "旧城", entity_type: "location", status: "canonical" },
      ]

      const html = worldView._renderEntityList()

      expect(html).toContain("全选当前页对象")
      expect(html).toContain('data-action="bulk-toggle-all"')
    })

    it("筛选区默认折叠，展开后同步可访问状态并缓存", () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = worldView._renderFilters()
      const button = document.querySelector('[data-action="toggle-filter-panel"]')
      const panel = document.getElementById(button.getAttribute("aria-controls"))

      worldView._toggleFilterPanel("objects", button)

      expect(button.getAttribute("aria-expanded")).toBe("true")
      expect(button.textContent).toContain("收起筛选")
      expect(panel.hidden).toBe(false)
      expect(worldView._filterPanelsOpen.objects).toBe(true)
      expect(JSON.parse(localStorage.getItem("novel_world_filter_panels:p1"))).toEqual({
        objects: true,
        "review-objects": false,
        "review-aliases": false,
        "review-relations": false,
      })
    })

    it("进入世界对象页时按项目恢复筛选栏展开状态", async () => {
      state.currentProjectId = "p1"
      localStorage.setItem("novel_world_filter_panels:p1", JSON.stringify({
        objects: true,
        "review-aliases": true,
      }))
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      api.world.listEntityBatches.mockResolvedValue([])

      await worldView.onEnter()

      expect(worldView._filterPanelsOpen).toEqual({
        objects: true,
        "review-objects": false,
        "review-aliases": true,
        "review-relations": false,
      })
    })
  })

  describe("_applyFilters", () => {
    it("应用过滤参数并写入对象库 URL query", async () => {
      state.currentProjectId = "p1"
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      document.body.innerHTML = `
        <select id="filter-entity-type"><option value="location" selected>地点</option></select>
        <select id="filter-display-state"><option value="active" selected>已采用</option></select>
        <input id="filter-q" value="王都" />
      `

      await worldView._applyFilters()

      expect(worldView._filters.entity_type).toBe("")
      expect(worldView._filters.display_state).toBe("active")
      expect(worldView._filters.q).toBe("")
      expect(worldView._filters.skip).toBe(0)
      expect(api.world.listEntities).not.toHaveBeenCalled()
      expect(router.navigate).toHaveBeenCalledWith("world", "objects", true, expect.any(URLSearchParams))
      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.toString()).toBe("entity_type=location&display_state=active&q=%E7%8E%8B%E9%83%BD")
    })

    it("应用深度导入筛选参数并停留在对象管理视图 URL", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "objects"
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })
      document.body.innerHTML = `
        <select id="filter-entity-type"><option value="">全部类型</option></select>
        <select id="filter-display-state"><option value="archived" selected>历史</option></select>
        <input id="filter-q" value="" />
        <select id="filter-source"><option value="deep_import" selected>深度导入</option></select>
        <input id="filter-workflow-id" value="wf-18" />
        <select id="filter-needs-review"><option value="true" selected>需复核</option></select>
        <select id="filter-auto-ingested"><option value="true" selected>自动入库</option></select>
      `

      await worldView._applyFilters()

      const query = router.navigate.mock.calls.at(-1)[3]
      expect(query.get("display_state")).toBe("archived")
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

      expect(worldView._filters.skip).toBe(0)
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

    it("编辑成功时等待刷新完成后再显示成功提示", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{
        id: "e1", name: "王都", entity_type: "location", status: "canonical",
      }]
      api.world.updateEntity.mockResolvedValue({})
      api.world.listEntityTypes.mockResolvedValue({ items: [] })
      let resolveRefresh
      router.refresh.mockImplementation(() => new Promise((resolve) => {
        resolveRefresh = resolve
      }))

      worldView.editEntity("e1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新王都" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">更新后的概要</textarea>
      `

      const pending = handler()
      await vi.waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1))
      expect(toast).not.toHaveBeenCalledWith("已保存", "success")

      resolveRefresh()
      await expect(pending).resolves.toBe(true)
      expect(toast).toHaveBeenCalledWith("已保存", "success")
    })

    it("编辑请求未完成时忽略快速重复提交", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{
        id: "e1", name: "王都", entity_type: "location", status: "canonical",
      }]
      let resolveUpdate
      api.world.updateEntity.mockImplementation(() => new Promise((resolve) => {
        resolveUpdate = resolve
      }))
      router.refresh.mockResolvedValue(true)

      worldView.editEntity("e1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新王都" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">更新后的概要</textarea>
      `

      const firstSubmission = handler()
      await vi.waitFor(() => expect(api.world.updateEntity).toHaveBeenCalledTimes(1))
      await expect(handler()).resolves.toBe(false)
      expect(api.world.updateEntity).toHaveBeenCalledTimes(1)

      resolveUpdate({})
      await expect(firstSubmission).resolves.toBe(true)
      expect(router.refresh).toHaveBeenCalledTimes(1)
      expect(toast).toHaveBeenCalledWith("已保存", "success")
      expect(toast).toHaveBeenCalledTimes(1)
    })

    it("编辑已写入但刷新失败时关闭弹窗并避免误报保存失败", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{
        id: "e1", name: "王都", entity_type: "location", status: "canonical",
      }]
      api.world.updateEntity.mockResolvedValue({})
      api.world.listEntityTypes.mockResolvedValue({ items: [] })
      router.refresh.mockRejectedValue(new Error("刷新网络失败"))

      worldView.editEntity("e1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新王都" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">更新后的概要</textarea>
        <div id="edit-entity-error" hidden></div>
      `

      await expect(handler()).resolves.toBe(true)
      expect(toast).not.toHaveBeenCalledWith("已保存", "success")
      expect(document.getElementById("edit-entity-error").textContent).toBe("")
      expect(toast).toHaveBeenCalledWith(
        "已保存，但列表刷新失败：刷新网络失败",
        "warning",
      )
      expect(api.world.updateEntity).toHaveBeenCalledTimes(1)
      expect(toast).toHaveBeenCalledTimes(1)
    })

    it("编辑请求完成前离开页面时不刷新或发送过期提示", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{
        id: "e1", name: "王都", entity_type: "location", status: "canonical",
      }]
      let resolveUpdate
      api.world.updateEntity.mockImplementation(() => new Promise((resolve) => {
        resolveUpdate = resolve
      }))

      worldView.editEntity("e1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新王都" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">更新后的概要</textarea>
      `

      const pending = handler()
      await vi.waitFor(() => expect(resolveUpdate).toBeTypeOf("function"))
      worldView.onLeave()
      resolveUpdate({})

      await expect(pending).resolves.toBe(true)
      expect(router.refresh).not.toHaveBeenCalled()
      expect(toast).not.toHaveBeenCalled()
    })

    it("建议兼容影子编辑后通过队列采用", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "shadow-1",
        name: "旧星门",
        entity_type: "location",
        status: "candidate",
        content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
      }]
      api.world.editAndConfirmSuggestion.mockResolvedValue({})

      worldView.editEntity("shadow-1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新星门" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">编辑后的概要</textarea>
      `

      await handler()

      expect(api.world.editAndConfirmSuggestion).toHaveBeenCalledWith("s1", {
        name: "新星门",
        entity_type: "location",
        summary: "编辑后的概要",
      }, "p1")
      expect(api.world.updateEntity).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith("已编辑并采用", "success")
    })

    it("普通待处理对象通过 promote 在采用时携带微调", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "candidate-1",
        name: "旧星门",
        entity_type: "location",
        status: "candidate",
        summary: "旧概要",
      }]
      api.world.promoteEntity.mockResolvedValue({})

      worldView.editEntity("candidate-1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="新星门" />
        <select id="edit-entity-type"><option value="location" selected>地点</option></select>
        <textarea id="edit-entity-summary">作者微调后的概要</textarea>
      `

      await handler()

      expect(api.world.promoteEntity).toHaveBeenCalledWith("candidate-1", "p1", {
        name: "新星门",
        entity_type: "location",
        summary: "作者微调后的概要",
      })
      expect(api.world.updateEntity).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith("已编辑并采用", "success")
    })

    it("建议对象编辑后可采用为新自定义类型", async () => {
      state.currentProjectId = "p1"
      worldView._candidates = [{
        id: "shadow-1",
        name: "月廷",
        entity_type: "organization",
        status: "candidate",
        content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
      }]
      api.world.editAndConfirmSuggestion.mockResolvedValue({})

      worldView.editEntity("shadow-1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="月廷" />
        <select id="edit-entity-type"><option value="__custom_entity_type__" selected>新建</option></select>
        <input id="edit-custom-entity-type" value="宗教/神祇" />
        <textarea id="edit-entity-summary">月神教团</textarea>
      `

      await handler()

      expect(api.world.editAndConfirmSuggestion).toHaveBeenCalledWith("s1", {
        name: "月廷",
        entity_type: "宗教/神祇",
        summary: "月神教团",
      }, "p1")
    })

    it("已采用对象改类型需确认且 blocker 保留弹窗内容", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [{
        id: "e1", name: "王都", entity_type: "location", status: "canonical",
      }]
      window.confirm = vi.fn(() => true)
      const error = new Error("请求冲突")
      error.body = {
        error: "entity_type_change_blocked",
        detail: "对象仍有依赖当前类型的专属数据",
        context: { blockers: [{ kind: "map_location_binding", count: 2 }] },
      }
      api.world.updateEntity.mockRejectedValue(error)

      worldView.editEntity("e1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="edit-entity-name" value="王都" />
        <select id="edit-entity-type"><option value="宗教/神祇" selected>宗教/神祇</option></select>
        <textarea id="edit-entity-summary">保留的概要</textarea>
        <div id="edit-entity-error" hidden></div>
      `

      const result = await handler()

      expect(window.confirm).toHaveBeenCalled()
      expect(result).toBe(false)
      expect(document.getElementById("edit-entity-summary").value).toBe("保留的概要")
      expect(document.getElementById("edit-entity-error").textContent).toContain("map_location_binding（2）")
      expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("保存失败"), "error")
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

    it("新建入口发送经过共享控件读取的自定义类型", async () => {
      state.currentProjectId = "p1"
      api.world.createEntity.mockResolvedValue({ id: "e1" })
      worldView._showCreateForm()
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="create-entity-name" value="月廷" />
        <select id="create-entity-type"><option value="__custom_entity_type__" selected>新建</option></select>
        <input id="create-custom-entity-type" value="宗教/神祇" />
        <textarea id="create-entity-summary">月神教团</textarea>
      `

      await handler()

      expect(api.world.createEntity).toHaveBeenCalledWith({
        name: "月廷",
        entity_type: "宗教/神祇",
        summary: "月神教团",
      }, "p1")
    })

    it("创建成功时等待刷新完成后再显示成功提示", async () => {
      state.currentProjectId = "p1"
      api.world.createEntity.mockResolvedValue({ id: "e1" })
      api.world.listEntityTypes.mockResolvedValue({ items: [] })
      let resolveRefresh
      router.refresh.mockImplementation(() => new Promise((resolve) => {
        resolveRefresh = resolve
      }))

      worldView._showCreateForm()
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="create-entity-name" value="月廷" />
        <select id="create-entity-type"><option value="organization" selected>组织</option></select>
        <textarea id="create-entity-summary">月神教团</textarea>
      `

      const pending = handler()
      await vi.waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1))
      expect(toast).not.toHaveBeenCalledWith('对象 "月廷" 已创建', "success")

      resolveRefresh()
      await expect(pending).resolves.toBe(true)
      expect(toast).toHaveBeenCalledWith('对象 "月廷" 已创建', "success")
    })

    it("创建请求未完成时忽略快速重复提交", async () => {
      state.currentProjectId = "p1"
      let resolveCreate
      api.world.createEntity.mockImplementation(() => new Promise((resolve) => {
        resolveCreate = resolve
      }))
      router.refresh.mockResolvedValue(true)

      worldView._showCreateForm()
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="create-entity-name" value="月廷" />
        <select id="create-entity-type"><option value="organization" selected>组织</option></select>
        <textarea id="create-entity-summary">月神教团</textarea>
      `

      const firstSubmission = handler()
      await vi.waitFor(() => expect(api.world.createEntity).toHaveBeenCalledTimes(1))
      await expect(handler()).resolves.toBe(false)
      expect(api.world.createEntity).toHaveBeenCalledTimes(1)

      resolveCreate({ id: "e1" })
      await expect(firstSubmission).resolves.toBe(true)
      expect(router.refresh).toHaveBeenCalledTimes(1)
      expect(toast).toHaveBeenCalledWith('对象 "月廷" 已创建', "success")
      expect(toast).toHaveBeenCalledTimes(1)
    })

    it("强制创建请求未完成时忽略快速重复确认", async () => {
      state.currentProjectId = "p1"
      confirmAction.mockImplementation(() => {})
      const conflict = new Error("请求失败 (409)")
      conflict.status = 409
      conflict.detail = {
        requires_confirmation: true,
        similar_entities: [{ id: "e1", name: "月廷", entity_type: "organization" }],
      }
      let resolveForceCreate
      api.world.createEntity
        .mockRejectedValueOnce(conflict)
        .mockImplementationOnce(() => new Promise((resolve) => {
          resolveForceCreate = resolve
        }))
      router.refresh.mockResolvedValue(true)

      worldView._showCreateForm()
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="create-entity-name" value="月廷" />
        <select id="create-entity-type"><option value="organization" selected>组织</option></select>
        <textarea id="create-entity-summary">月神教团</textarea>
      `

      await expect(handler()).resolves.toBe(false)
      const forceHandler = confirmAction.mock.calls[0][1]
      const firstForceSubmission = forceHandler()
      await vi.waitFor(() => expect(api.world.createEntity).toHaveBeenCalledTimes(2))
      await expect(forceHandler()).resolves.toBe(false)
      expect(api.world.createEntity).toHaveBeenCalledTimes(2)

      resolveForceCreate({ id: "e2" })
      await expect(firstForceSubmission).resolves.toBe(true)
      expect(router.refresh).toHaveBeenCalledTimes(1)
      expect(toast).toHaveBeenCalledWith('对象 "月廷" 已创建', "success")
      expect(toast).toHaveBeenCalledTimes(1)
    })

    it("创建已写入但刷新失败时不允许重复提交", async () => {
      state.currentProjectId = "p1"
      api.world.createEntity.mockResolvedValue({ id: "e1" })
      router.refresh.mockRejectedValue(new Error("刷新网络失败"))

      worldView._showCreateForm()
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <input id="create-entity-name" value="月廷" />
        <select id="create-entity-type"><option value="organization" selected>组织</option></select>
        <textarea id="create-entity-summary">月神教团</textarea>
      `

      await expect(handler()).resolves.toBe(true)
      expect(api.world.createEntity).toHaveBeenCalledTimes(1)
      expect(toast).toHaveBeenCalledWith(
        '对象 "月廷" 已创建，但列表刷新失败：刷新网络失败',
        "warning",
      )
      expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("创建失败"), "error")
      expect(toast).toHaveBeenCalledTimes(1)
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
      expect(api.world.listRelationships).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20, status: "canonical" })
      expect(html).toContain('data-action="delete-relation"')
      expect(html).not.toContain('data-action="mark-relation-reviewed"')
      expect(html).toContain("克莱恩")
      expect(html).toContain("邓恩")
      expect(html).not.toContain("src...")
    })

    it("渲染待处理关系状态", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "src:tgt",
          source_id: "src",
          source_name: "克莱恩",
          target_id: "tgt",
          target_name: "邓恩",
          member_count: 1,
          evidence_count: 1,
          type_variants: ["sibling"],
          scene_indices: [3],
          source_chapter_indices: [2],
          canonical_relations: [],
          execution_fingerprint: "f".repeat(64),
          members: [{
            id: "r1",
            relation_type: "sibling",
            status: "candidate",
            strength: 0.8,
            evidence_summary: { source: "deep_import", scene_index: 3, source_chapter_index: 2, quote: "原文" },
          }],
        }],
        group_total: 1,
        item_total: 1,
      })
      const html = await worldView._renderRelations({ reviewOnly: true })
      expect(html).toContain("待处理")
      expect(html).toContain('data-action="prepare-relation-review"')
      expect(html).toContain("处理本组")
      expect(html).toContain("全选当前页关系组")
      expect(html).toContain("深度导入 · Scene 3 · 第 2 章 · 强度 80%")
      expect(html).toContain("展开筛选")
    })

    it("待处理关系按有向对象对分组并显示证据", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "src:tgt",
          source_id: "src", source_name: "克莱恩",
          target_id: "tgt", target_name: "值夜者",
          member_count: 1, evidence_count: 1,
          type_variants: ["member_of"], scene_indices: [], source_chapter_indices: [],
          canonical_relations: [], execution_fingerprint: "f".repeat(64),
          members: [{ id: "r1", relation_type: "member_of", status: "candidate", evidence_summary: { quote: "证据文本" } }],
        }],
        group_total: 1, item_total: 1,
      })

      const html = await worldView._renderRelations({ reviewOnly: true })

      expect(api.world.listRelationReviewGroups).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20 })
      expect(html).toContain("克莱恩 → 值夜者")
      expect(html).toContain("证据文本")
    })

    it("反向关系只显示提示且不进入当前组", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "src:tgt",
          source_id: "src", source_name: "甲",
          target_id: "tgt", target_name: "乙",
          member_count: 1, evidence_count: 0,
          type_variants: ["supports"], members: [{ id: "r1", relation_type: "supports" }],
          canonical_relations: [], execution_fingerprint: "f".repeat(64),
          reverse_candidate_count: 2,
          reverse_type_variants: ["opposes"],
          reverse_canonical_relations: [{ relation_type: "related_to" }],
        }],
        group_total: 1, item_total: 1,
      })

      const html = await worldView._renderRelations({ reviewOnly: true })

      expect(html).toContain("反向关联提示：乙 → 甲")
      expect(html).toContain("反向记录不会自动归并")
      expect(html).toContain("2 条候选")
    })

    it("关系证据展示导入来源且转义 review_meta 动态内容", () => {
      const html = worldView._inlineRelationEvidenceHtml({
        strength: 0.86,
        review_meta: {
          source: "deep_import",
          workflow_id: "workflow-2<script>",
          scene_id: "scene-9",
          scene_index: 9,
          source_chapter_index: 12,
          quote: "引用文本",
          evidence_refs: [{
            scene_id: "scene-9",
            source_chapter_index: 12,
            quote: "<img src=x onerror=alert(1)>",
          }],
        },
      })

      expect(html).toContain("深度导入")
      expect(html).toContain("workflow-2&lt;script&gt;")
      expect(html).toContain("scene-9（序号 9）")
      expect(html).toContain("章节 12")
      expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;")
      expect(html).not.toContain("<img src=x")
    })

    it("待处理关系筛选参数传给 API", async () => {
      state.currentProjectId = "p1"
      worldView._relationFilters = { skip: 0, limit: 20, q: "克莱恩", relation_type: "member_of", source_chapter_id: "ch1", strength_min: "0.7", strength_max: "" }
      api.world.listRelationReviewGroups.mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })

      const html = await worldView._renderRelations({ reviewOnly: true })

      expect(api.world.listRelationReviewGroups).toHaveBeenCalledWith({
        novel_id: "p1",
        skip: 0,
        limit: 20,
        q: "克莱恩",
        relation_type: "member_of",
        source_chapter_id: "ch1",
        strength_min: 0.7,
      })
      expect(html).toContain('data-filter-panel="review-relations"')
      expect(html).toContain("已筛选")
    })

    it("关系超过一页时显示分页并支持翻页", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({
        items: [{ id: "r1", source_name: "A", target_name: "B", relation_type: "ally_of" }],
        total: 41,
      })

      const html = await worldView._renderRelations()
      state.currentSubView = "relations"
      await worldView._changeRelationPage(1)

      expect(html).toContain('data-action="next-relations-page"')
      expect(html).toContain("共 41 条")
      expect(worldView._relationFilters.skip).toBe(20)
      expect(router.navigate).toHaveBeenCalledWith("world", "relations", true, expect.any(URLSearchParams))
    })
  })

  describe("showRelationCreateForm", () => {
    it("showRelationCreateForm 调用 showModal", () => {
      worldView.showRelationCreateForm()
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("showRelationReviewEditForm", () => {
    it("关系编辑后采用只提交可编辑字段", async () => {
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
      expect(body).toContain("强度 50%")
      expect(body).not.toContain("置信度 50%")
      expect(showModal.mock.calls[0][2][0].text).toBe("采用")
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

  describe("关系分组决策", () => {
    it("端点搜索调用全项目对象接口，可选中首批之外的结果", async () => {
      state.currentProjectId = "p1"
      worldView._relationGroups = [{
        group_id: "g1",
        source_id: "e1", source_name: "源对象",
        target_id: "e2", target_name: "旧目标",
        execution_fingerprint: "f".repeat(64),
        canonical_relations: [],
        members: [{ id: "r1", relation_type: "friend", description: "旧描述", strength: 0.5 }],
      }]
      worldView.showRelationGroupReviewForm("g1")
      const body = showModal.mock.calls[0][1].html
      document.body.innerHTML = body
      api.world.listEntities.mockResolvedValue({
        items: [{ id: "e25", name: "第二十五个对象", entity_type: "character", status: "canonical" }],
      })
      worldView._bindReviewEntitySearch("relation-target", "e2")

      document.getElementById("relation-target-query").value = "二十五"
      document.getElementById("relation-target-search").click()
      await vi.waitFor(() => expect(api.world.listEntities).toHaveBeenCalledWith({
        novel_id: "p1", q: "二十五", skip: 0, limit: 20,
      }))

      expect(document.getElementById("relation-target-select").innerHTML).toContain("第二十五个对象")
      expect(document.getElementById("relation-target-select").innerHTML).toContain('value="e25"')
    })

    it("一次确认只发出一个关系批处理请求并反馈部分失败", async () => {
      state.currentProjectId = "p1"
      autoConfirm()
      const groups = [
        { group_id: "g1", members: [{ id: "r1" }], execution_fingerprint: "1".repeat(64) },
        { group_id: "g2", members: [{ id: "r2" }], execution_fingerprint: "2".repeat(64) },
      ]
      worldView._relationReviewDrafts = {
        g1: { client_decision_id: "g1", action: "accept" },
        g2: { client_decision_id: "g2", action: "accept" },
      }
      api.world.reviewRelationsBatch.mockResolvedValue({
        succeeded_count: 1, stale_count: 0, failed_count: 1,
        results: [
          { client_decision_id: "g1", status: "success" },
          { client_decision_id: "g2", status: "failed", message: "冲突" },
        ],
      })

      worldView._applyRelationReviewBatch(groups)
      await vi.waitFor(() => expect(api.world.reviewRelationsBatch).toHaveBeenCalledTimes(1))

      expect(api.world.reviewRelationsBatch).toHaveBeenCalledWith({
        confirmed: true,
        decisions: [
          { client_decision_id: "g1", action: "accept" },
          { client_decision_id: "g2", action: "accept" },
        ],
      }, "p1")
      expect(worldView._relationReviewDrafts.g1).toBeUndefined()
      expect(worldView._relationReviewDrafts.g2).toBeDefined()
      expect(worldView._relationReviewErrors.g2).toBe("处理失败：冲突")
      expect(toast).toHaveBeenCalledWith("已处理 1 个关系组，1 个失败", "warning")
    })

    it("关系批处理超过 20 个决策时不发请求", () => {
      const groups = Array.from({ length: 21 }, (_, index) => ({
        group_id: `g${index}`,
        members: [{ id: `r${index}` }],
        execution_fingerprint: "f".repeat(64),
      }))
      worldView._relationReviewDrafts = Object.fromEntries(groups.map((group) => [
        group.group_id,
        { client_decision_id: group.group_id, action: "accept", member_relation_ids: [group.members[0].id] },
      ]))

      worldView._applyRelationReviewBatch(groups)

      expect(api.world.reviewRelationsBatch).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("单次最多处理 20 个关系决策"), "warning")
    })

    it("关系批处理累计超过 50 条所选关系时不发请求", () => {
      const groups = Array.from({ length: 20 }, (_, groupIndex) => ({
        group_id: `g${groupIndex}`,
        members: Array.from({ length: 3 }, (_, memberIndex) => ({ id: `r${groupIndex}-${memberIndex}` })),
        execution_fingerprint: "f".repeat(64),
      }))
      worldView._relationReviewDrafts = Object.fromEntries(groups.map((group) => [
        group.group_id,
        {
          client_decision_id: group.group_id,
          action: "ignore",
          group_id: group.group_id,
          member_relation_ids: group.members.map((item) => item.id),
          expected_execution_fingerprint: group.execution_fingerprint,
        },
      ]))

      worldView._applyRelationReviewBatch(groups)

      expect(api.world.reviewRelationsBatch).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("50 条所选关系"), "warning")
    })

    it("关系批处理网络失败保留草稿并标记可重试原因", async () => {
      state.currentProjectId = "p1"
      autoConfirm()
      const groups = [{ group_id: "g1", members: [{ id: "r1" }], execution_fingerprint: "f".repeat(64) }]
      worldView._relationReviewDrafts = {
        g1: { client_decision_id: "g1", action: "accept", member_relation_ids: ["r1"] },
      }
      api.world.reviewRelationsBatch.mockRejectedValue(new Error("网络中断"))

      worldView._applyRelationReviewBatch(groups)
      await vi.waitFor(() => expect(api.world.reviewRelationsBatch).toHaveBeenCalledTimes(1))

      expect(worldView._relationReviewDrafts.g1).toBeDefined()
      expect(worldView._relationReviewErrors.g1).toBe("网络中断")
      expect(toast).toHaveBeenCalledWith("网络中断", "error")
    })

    it("关系决策抽屉显示采用结果预览", () => {
      worldView._relationGroups = [{
        group_id: "g1", source_id: "e1", source_name: "甲", target_id: "e2", target_name: "乙",
        execution_fingerprint: "f".repeat(64), canonical_relations: [],
        members: [{ id: "r1", relation_type: "friend_of", description: "朋友", strength: 0.8 }],
      }]

      worldView.showRelationGroupReviewForm("g1")

      const body = showModal.mock.calls[0][1].html
      expect(body).toContain('id="relation-review-preview"')
      document.body.innerHTML = body
      worldView._updateRelationReviewPreview(worldView._relationGroups[0])
      expect(document.getElementById("relation-review-preview").textContent).toContain("采用后结果预览")
      expect(document.getElementById("relation-review-preview").textContent).toContain("所选证据：1 条")
    })

    it("处理完成后自动进入同位置的下一个关系组", async () => {
      worldView._relationGroups = [{ group_id: "next-group" }]
      const open = vi.spyOn(worldView, "showRelationGroupReviewForm").mockImplementation(() => {})

      await worldView._advanceRelationReview(0)

      expect(open).toHaveBeenCalledWith("next-group")
      open.mockRestore()
    })

    it("当前页处理为空时校正页码并保留滚动位置", async () => {
      state.currentSubView = "review-relations"
      worldView._relationGroups = []
      worldView._relationGroupTotal = 21
      worldView._relationFilters = { skip: 40, limit: 20, q: "克莱恩" }
      document.body.innerHTML = '<main id="workspace-content"></main>'
      document.getElementById("workspace-content").scrollTop = 72

      await worldView._advanceRelationReview(0)

      expect(worldView._relationFilters.skip).toBe(20)
      expect(router.replace).toHaveBeenCalledWith("world", "review-relations", expect.any(URLSearchParams))
      const query = router.replace.mock.calls.at(-1)[2]
      expect(query.get("q")).toBe("克莱恩")
      expect(query.get("page")).toBe("2")
      expect(document.getElementById("workspace-content").scrollTop).toBe(72)
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
      expect(toast).toHaveBeenCalledWith("关系已采用", "success")
      expect(router.refresh).not.toHaveBeenCalled()
      expect(document.getElementById("workspace-content").scrollTop).toBe(66)
    })

    it("关系复核失败显示反馈并消化 rejection", async () => {
      state.currentProjectId = "p1"
      api.world.reviewEditRelationship.mockRejectedValue(new Error("review failed"))

      const result = await worldView._markRelationReviewed("r1")

      expect(result).toBe(false)
      expect(toast).toHaveBeenCalledWith("关系采用失败：review failed", "error")
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
      expect(api.world.listAliases).toHaveBeenCalledWith({ novel_id: "p1", skip: 0, limit: 20, display_state: "active" })
      expect(html).toContain("炎帝")
      expect(html).toContain("称号")
      expect(html).toContain("80%")
      expect(html).toContain('data-action="delete-alias"')
      expect(html).toContain("已采用")
      expect(html).not.toContain('data-action="mark-alias-reviewed"')
    })

    it("渲染待处理别名元数据", async () => {
      state.currentProjectId = "p1"
      api.world.listAliasReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "e1",
          entity_id: "e1",
          entity_name: "克莱恩",
          member_count: 1,
          members: [{
            alias: "周明瑞",
            alias_type: "name",
            entity_id: "e1",
            entity_name: "克莱恩",
            confidence: 0.91,
            status: "candidate",
            source: "deep_import",
            needs_review: true,
            execution_fingerprint: "a".repeat(64),
          }],
        }],
        group_total: 1,
        item_total: 1,
      })
      const html = await worldView._renderAliases({ reviewOnly: true })
      expect(html).toContain("克莱恩")
      expect(html).toContain("深度导入")
      expect(html).toContain("置信度 91%")
      expect(html).toContain('data-action="prepare-alias-review"')
      expect(html).toContain("编辑决策")
      expect(html).toContain("全选当前页别名")
      expect(html).toContain("展开筛选")
    })

    it("建议队列拥有的别名不进入分组复核选择", async () => {
      state.currentProjectId = "p1"
      api.world.listAliasReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "shadow",
          entity_id: "shadow",
          entity_name: "建议影子",
          member_count: 1,
          members: [{
            alias: "影子别名",
            alias_type: "alias",
            entity_id: "shadow",
            managed_by_suggestion: true,
            execution_fingerprint: "a".repeat(64),
          }],
        }],
        group_total: 1,
        item_total: 1,
      })

      const html = await worldView._renderAliases({ reviewOnly: true })

      expect(html).toContain("随对象建议处理")
      expect(html).not.toContain('data-action="prepare-alias-review"')
      expect(html).not.toContain('data-id="shadow::影子别名"')
      expect(worldView._visibleIdsForBulkScope("world-aliases")).toEqual([])
      expect(worldView._bulkSelections["world-aliases"]?.size || 0).toBe(0)
    })

    it("待处理别名队列按展示态并传递筛选", async () => {
      state.currentProjectId = "p1"
      worldView._aliasFilters = { skip: 0, limit: 20, q: "黑荆棘", source: "deep_import", workflow_id: "wf1", scene_index: "3", confidence_min: "0.8", confidence_max: "", source_chapter_index: "" }
      api.world.listAliasReviewGroups.mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })

      const html = await worldView._renderAliases({ reviewOnly: true })

      expect(api.world.listAliasReviewGroups).toHaveBeenCalledWith({
        novel_id: "p1",
        skip: 0,
        limit: 20,
        q: "黑荆棘",
        source: "deep_import",
        workflow_id: "wf1",
        scene_index: 3,
        confidence_min: 0.8,
      })
      expect(html).toContain('data-filter-panel="review-aliases"')
      expect(html).toContain("已筛选")
    })

    it("分组响应中的自定义别名类型保持原值", async () => {
      state.currentProjectId = "p1"
      api.world.listAliasReviewGroups.mockResolvedValue({
        groups: [{
          group_id: "e1",
          entity_id: "e1",
          entity_name: "克莱恩",
          member_count: 1,
          members: [{
            alias: "夏洛克",
            alias_type: "别称",
            entity_id: "e1",
            entity_name: "克莱恩",
            type_kind: "custom",
            suggested_alias_type: "alias",
            execution_fingerprint: "a".repeat(64),
          }],
        }],
        group_total: 1,
        item_total: 1,
      })

      const html = await worldView._renderAliases({ reviewOnly: true })

      expect(html).toContain("别称")
      expect(html).toContain("自定义")
      worldView.showAliasReviewDecisionForm("e1", "夏洛克")
      expect(showModal.mock.calls[0][1].html).toContain("保留原类型：别称")
      expect(showModal.mock.calls[0][1].html).toContain('value="别称" selected')
    })

    it("别名决策编辑器把 Workflow 和 Scene UUID 收进诊断折叠区", () => {
      worldView._aliases = [{
        entity_id: "e1", entity_name: "克莱恩", alias: "夏洛克", alias_type: "别称",
        source: "deep_import", workflow_id: "workflow-secret", scene_id: "scene-uuid-secret", scene_index: 3,
        confidence: 0.9, quote: "原文", execution_fingerprint: "a".repeat(64),
      }]

      worldView.showAliasReviewDecisionForm("e1", "夏洛克")
      const body = showModal.mock.calls[0][1].html

      expect(body).toContain("深度导入")
      expect(body).toContain("Scene 3")
      expect(body.indexOf("<details>")).toBeLessThan(body.indexOf("workflow-secret"))
      expect(body).not.toContain("<strong>Workflow：</strong>")
    })

    it("别名目标搜索排除 suggestion shadow", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = `
        <input id="alias-target-query" value="克莱恩" />
        <button id="alias-target-search"></button>
        <select id="alias-target-id"></select>
      `
      api.world.listEntities.mockResolvedValue({ items: [
        { id: "shadow", name: "克莱恩建议影子", status: "candidate", content_json: { _meta: { compatibility_shadow: true } } },
        { id: "valid", name: "克莱恩", status: "canonical", content_json: {} },
      ] })

      worldView._bindAliasTargetSearch({ sourceId: "source" })
      document.getElementById("alias-target-search").click()
      await vi.waitFor(() => expect(api.world.listEntities).toHaveBeenCalled())

      expect(document.getElementById("alias-target-id").innerHTML).toContain('value="valid"')
      expect(document.getElementById("alias-target-id").innerHTML).not.toContain('value="shadow"')
    })

    it("别名批处理超过 50 条时不发请求", () => {
      const items = Array.from({ length: 51 }, (_, index) => ({
        entity_id: `e${index}`, alias: `别名${index}`, execution_fingerprint: "a".repeat(64),
      }))

      worldView._applyAliasReviewBatch(items, "accept")

      expect(api.world.reviewAliasesBatch).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith(expect.stringContaining("单次最多处理 50 条别名"), "warning")
    })

    it("别名部分失败保留草稿并显示具体原因", async () => {
      state.currentProjectId = "p1"
      autoConfirm()
      const items = [
        { entity_id: "e1", alias: "成功项", execution_fingerprint: "a".repeat(64) },
        { entity_id: "e2", alias: "冲突项", execution_fingerprint: "b".repeat(64) },
      ]
      worldView._aliases = items
      worldView._aliasReviewDrafts = {
        "e1::成功项": { alias_type: "alias" },
        "e2::冲突项": { alias_type: "别称" },
      }
      api.world.reviewAliasesBatch.mockResolvedValue({
        succeeded_count: 1, stale_count: 1, failed_count: 0,
        results: [
          { client_decision_id: "alias-0-e1", status: "success" },
          { client_decision_id: "alias-1-e2", status: "stale", message: "已被其他复核修改" },
        ],
      })

      worldView._applyAliasReviewBatch(items, "accept")
      await vi.waitFor(() => expect(api.world.reviewAliasesBatch).toHaveBeenCalledTimes(1))

      expect(worldView._aliasReviewDrafts["e1::成功项"]).toBeUndefined()
      expect(worldView._aliasReviewDrafts["e2::冲突项"]).toBeDefined()
      expect(worldView._aliasReviewErrors["e2::冲突项"]).toBe("已过期：已被其他复核修改")
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
      state.currentSubView = "aliases"
      await worldView._changeAliasPage(1)

      expect(html).toContain('data-action="next-aliases-page"')
      expect(html).toContain("共 22 条")
      expect(worldView._aliasFilters.skip).toBe(20)
      expect(router.navigate).toHaveBeenCalledWith("world", "aliases", true, expect.any(URLSearchParams))
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
      expect(toast).toHaveBeenCalledWith("别名已采用", "success")
      expect(router.refresh).not.toHaveBeenCalled()
      expect(document.getElementById("workspace-content").scrollTop).toBe(58)
    })

    it("别名复核失败显示反馈并消化 rejection", async () => {
      state.currentProjectId = "p1"
      api.world.updateAlias.mockRejectedValue(new Error("alias failed"))

      const result = await worldView._markAliasReviewed("e1", "炎帝")

      expect(result).toBe(false)
      expect(toast).toHaveBeenCalledWith("别名采用失败：alias failed", "error")
    })

    it("编辑后采用别名只提交目标、文本、类型和确认标记", async () => {
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
      expect(showModal.mock.calls[0][2][0].text).toBe("保存并采用")
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
      expect(toast).toHaveBeenCalledWith("别名已保存并采用", "success")
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

    it("建议兼容影子设为别名走权威队列", async () => {
      state.currentProjectId = "p1"
      worldView._entities = [
        { id: "e1", name: "林岚", entity_type: "character", status: "canonical" },
      ]
      worldView._candidates = [{
        id: "shadow-1",
        name: "岚姐",
        entity_type: "character",
        status: "candidate",
        content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
      }]
      api.world.resolveSuggestionAsAlias.mockResolvedValue({
        result_ref_json: { affected_ids: ["shadow-1", "e1"] },
      })
      api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

      worldView.showResolveAliasForm("shadow-1")
      const handler = captureModalHandler()
      document.body.innerHTML = `
        <select id="alias-target-id"><option value="e1" selected>林岚</option></select>
        <input id="alias-edit-text" value="岚姐" />
        <select id="alias-edit-type"><option value="alias" selected>别名</option></select>
      `

      await handler()

      expect(api.world.resolveSuggestionAsAlias).toHaveBeenCalledWith("s1", {
        target_entity_id: "e1",
        alias: "岚姐",
        alias_type: "alias",
      }, "p1")
      expect(api.world.resolveEntityAsAlias).not.toHaveBeenCalled()
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

      expect(api.imports.startStage).toHaveBeenCalledWith(
        "world_objects",
        "p1",
        1,
        5,
        false,
        false,
        {
          adoption_policy: "user_authorized_pipeline",
          authorization_confirmed: true,
        },
      )
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

      expect(api.imports.startStage).toHaveBeenCalledWith(
        "plot_structure",
        "p1",
        2,
        4,
        false,
        false,
        {
          adoption_policy: "user_authorized_pipeline",
          authorization_confirmed: true,
        },
      )
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

    expect(targets.map((item) => item.id)).toEqual(["k1"])
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
        display_state: "review",
      }))
      expect(router.navigate).toHaveBeenCalledWith("world", "candidates")
    }
  })

  it("建议兼容影子合并走权威队列", async () => {
    worldView._candidates = [{
      id: "shadow-1",
      name: "古代星门",
      status: "candidate",
      content_json: { _meta: { compatibility_shadow: true, suggestion_id: "s1" } },
    }]
    api.world.mergeSuggestion.mockResolvedValue({
      result_ref_json: {
        candidate_entity_id: "shadow-1",
        affected_ids: ["shadow-1", "target-1"],
      },
    })
    api.world.listEntities.mockResolvedValue({ items: [], total: 0 })

    await worldView._mergeEntity("shadow-1", "target-1")

    expect(api.world.mergeSuggestion).toHaveBeenCalledWith("s1", "target-1", "p1")
    expect(api.world.mergeEntity).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("实体已合并", "success")
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
      display_state: "review",
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
        allow_canonical_alias: false,
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

  it("已采用对象库多选工具条只提供融合、标记为别名和删除", () => {
    worldView._entities = [
      { id: "e1", name: "克莱恩", entity_type: "character", status: "canonical" },
      { id: "e2", name: "周明瑞", entity_type: "character", status: "canonical" },
    ]

    const html = worldView._renderEntityTable(worldView._entities, { showNewBadge: false })

    expect(html).toContain('data-bulk-action="fuse-entities"')
    expect(html).toContain('data-bulk-action="alias-entities"')
    expect(html).toContain('data-bulk-action="delete-entities"')
    expect(html).not.toContain('data-bulk-action="review-entities"')
    expect(html).not.toContain('data-bulk-action="promote-entities"')
  })

  it("标记为别名要求选择保留对象并提交 canonical 二次授权", async () => {
    const items = [
      { id: "e1", name: "克莱恩", entity_type: "character", status: "canonical" },
      { id: "e2", name: "周明瑞", entity_type: "character", status: "canonical" },
      { id: "e3", name: "愚者先生", entity_type: "character", status: "canonical" },
    ]
    api.world.applyEntityFusionSuggestions.mockResolvedValue({ applied: 2, skipped: 0 })
    const refresh = vi.spyOn(worldView, "_refreshCurrentSubViewInPlace").mockResolvedValue()

    worldView._showBulkEntityResolution("alias-entities", items)
    const modal = showModal.mock.calls.at(-1)
    document.body.innerHTML = modal[1].html
    document.querySelector('input[value="e2"]').checked = true
    await modal[2][0].handler()

    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("周明瑞"),
      expect.any(Function),
      "确认执行",
    )
    await confirmAction.mock.calls.at(-1)[1]()

    expect(api.world.applyEntityFusionSuggestions).toHaveBeenCalledWith({
      novel_id: "p1",
      confirmed: true,
      suggestions: [
        {
          action: "alias_only",
          source_entity_id: "e1",
          target_entity_id: "e2",
          alias: "克莱恩",
          allow_canonical_merge: false,
          allow_canonical_alias: true,
        },
        {
          action: "alias_only",
          source_entity_id: "e3",
          target_entity_id: "e2",
          alias: "愚者先生",
          allow_canonical_merge: false,
          allow_canonical_alias: true,
        },
      ],
    })
    refresh.mockRestore()
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
    expect(toast).toHaveBeenCalledWith("世界对象已标记为已检查", "success")
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
    expect(toast).toHaveBeenCalledWith("世界对象检查状态更新失败：entity failed", "error")
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
