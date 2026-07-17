/**
 * worldView 测试
 *
 * 覆盖生命周期、3 个子视图（候选清洗已移除）、实体 CRUD、关系和别名管理。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import worldView from "../views/worldView.js"
import worldBibleView from "../views/worldBibleView.js"
import { autoConfirm, captureModalHandler, renderHtml, resetTestEnvironment } from "./helpers.js"

beforeEach(() => {
  resetTestEnvironment()
  worldView._destroyReferencePickers()
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
  worldView._rankingFacets = null
  worldView._rankingContext = null
  worldView._filters = { entity_type: "", display_state: "active", q: "", skip: 0, limit: 20 }
  worldView._objectViewMode = "table"
  worldView._discoveryMode = "hot"
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
  api.world.getReviewTypeCatalog.mockReset().mockResolvedValue(worldView._reviewTypeCatalog)
  api.world.listRelationReviewGroups.mockReset().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
  api.world.reviewRelationsBatch.mockReset()
  api.world.listAliasReviewGroups.mockReset().mockResolvedValue({ groups: [], group_total: 0, item_total: 0 })
  api.world.reviewAliasesBatch.mockReset()
  router.refresh.mockReset()
  api.world.getEntityMapPresence.mockReset().mockResolvedValue({ items: [], total: 0 })
})

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

  })
})

// ============================================================
// 合并、回滚与知识边界
// ============================================================

describe("合并、回滚与知识边界", () => {
  beforeEach(() => {
    state.currentProjectId = "p1"
  })

  it("合并目标选择器不包含候选对象，避免候选互相合并后两条同时离开候选清洗", async () => {
    const source = { id: "c1", name: "阿兹克", status: "candidate" }
    const entities = [
      source,
      { id: "c2", name: "阿兹克", entity_type: "character", status: "candidate" },
      { id: "d1", name: "阿兹克", entity_type: "character", status: "draft" },
      { id: "k1", name: "阿兹克", entity_type: "character", status: "canonical" },
      { id: "i1", name: "阿兹克", entity_type: "character", status: "ignored" },
    ]
    worldView._entities = entities
    document.body.innerHTML = '<div id="merge-target-picker"></div><input type="hidden" id="merge-target-id" />'
    api.world.listEntities.mockResolvedValue({ items: entities })

    worldView._mountEntityReferencePicker({
      rootId: "merge-target-picker",
      inputId: "merge-target-id",
      sourceId: "c1",
      canonicalOnly: true,
    })
    const query = document.querySelector("[data-reference-query]")
    query.value = "阿兹克"
    query.dispatchEvent(new Event("input"))
    await vi.waitFor(() => expect(api.world.listEntities).toHaveBeenCalled())

    const results = Array.from(document.querySelectorAll("[data-reference-result]"))
    expect(results).toHaveLength(1)
    expect(results[0].getAttribute("data-reference-result")).toContain("k1")
  })

  it("对象名称选定后仍需二次确认才执行合并", async () => {
    const source = { id: "candidate-1", name: "待合并对象", status: "candidate" }
    const target = { id: "target-1", name: "保留对象", status: "canonical" }
    worldView._entities = [source, target]
    worldView._candidates = [source]
    const merge = vi.spyOn(worldView, "_mergeEntity").mockResolvedValue()
    confirmAction.mockImplementation(() => {})

    worldView.showMergeForm(source.id)
    document.body.innerHTML = showModal.mock.calls.at(-1)[1].html
    document.getElementById("merge-target-id").value = target.id
    document.getElementById("merge-target-id").dataset.referenceLabel = target.name
    await showModal.mock.calls.at(-1)[2].find((button) => button.text === "合并").handler()

    expect(merge).not.toHaveBeenCalled()
    expect(confirmAction).toHaveBeenCalledWith(
      expect.stringContaining("待合并对象"),
      expect.any(Function),
      "确认合并",
    )
    expect(confirmAction.mock.calls.at(-1)[0]).toContain("保留对象")

    await confirmAction.mock.calls.at(-1)[1]()
    expect(merge).toHaveBeenCalledWith("candidate-1", "target-1")
    merge.mockRestore()
    confirmAction.mockReset()
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

  it("候选清洗批量确认处理 create_new 和目标未解析的别名候选", async () => {
    worldView._candidates = [
      { id: "c1", name: "新对象", content_json: { _meta: { suggested_action: "create_new" } } },
      { id: "c2", name: "已解析别名", content_json: { _meta: {
        suggested_action: "alias_of_existing",
        suggested_existing_entity_id: "canonical-1",
      } } },
      { id: "c3", name: "仅名称目标", content_json: { _meta: {
        suggested_action: "link_to_existing",
        suggested_existing_entity_name: "仅名称目标",
      } } },
      { id: "c4", name: "指向自己", content_json: { _meta: {
        suggested_action: "alias_of_existing",
        suggested_existing_entity_id: "c4",
      } } },
    ]
    worldView._bulkSelections["world-candidates"] = new Set(["c1", "c2", "c3", "c4"])
    api.world.promoteEntity.mockResolvedValue({})

    await worldView._executeBulkAction("world-candidates", "accept-candidates", worldView._itemsForBulkScope("world-candidates"))

    expect(api.world.promoteEntity).toHaveBeenCalledTimes(3)
    expect(api.world.promoteEntity).toHaveBeenCalledWith("c1", "p1")
    expect(api.world.promoteEntity).toHaveBeenCalledWith("c3", "p1")
    expect(api.world.promoteEntity).toHaveBeenCalledWith("c4", "p1")
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
