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
  worldView._batches = []
  worldView._total = 0
  worldView._entitiesLoadError = null
  worldView._filters = { entity_type: "", status: "", q: "", skip: 0, limit: 20 }
  worldView._autoExtractOpen = false
  if (worldView._autoExtractPoller?.stop) worldView._autoExtractPoller.stop()
  worldView._autoExtractTaskId = null
  worldView._autoExtractStatus = "就绪"
  worldView._autoExtractTimer = null
  worldView._autoExtractProgress = null
  worldView._autoExtractPoller = null
  worldView._autoExtractMeta = null
  localStorage.removeItem("novel_world_extract_task")
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
    expect(api.world.listEntityBatches).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(worldView._entities).toHaveLength(1)
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
// render
// ============================================================

describe("worldView render", () => {
  it("渲染子标签导航（包含候选清洗）", async () => {
    const html = await worldView.render()
    expect(html).toContain("对象库")
    expect(html).toContain("候选清洗")
    expect(html).toContain("关系")
    expect(html).toContain("别名")
  })

  it("world/map 作为兼容入口跳转到一级地图页", async () => {
    state.currentSubView = "map"

    const html = await worldView.render()

    expect(html).toContain("正在打开地图")
    expect(html).not.toContain("map-root")
    await vi.waitFor(() => {
      expect(router.navigate).toHaveBeenCalledWith("map", null)
    })
  })
})

// ============================================================
// 候选清洗
// ============================================================

describe("候选清洗", () => {
  describe("_renderCandidatesList", () => {
    it("空列表显示空状态", () => {
      const html = worldView._renderCandidatesList()
      expect(html).toContain("没有待处理的候选对象")
    })

    it("别名/合并候选显示目标对象名称", () => {
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
      expect(html).toContain('data-action="merge-entity"')
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
  })

  describe("acceptCandidate", () => {
    it("确认 create_new 候选时提升为正史并刷新候选列表", async () => {
      state.currentProjectId = "p1"
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
      expect(container.querySelector(".empty-state [data-action='toggle-extract']")).toBeTruthy()
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
    it("应用过滤参数并重新加载", async () => {
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
      expect(api.world.listEntities).toHaveBeenCalledWith(
        expect.objectContaining({ novel_id: "p1", entity_type: "location", status: "canonical", q: "王都" }),
      )
    })

    it("应用深度导入筛选参数并停留在对象管理视图", async () => {
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

      expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({
        novel_id: "p1",
        status: "deprecated",
        source: "deep_import",
        workflow_id: "wf-18",
        needs_review: true,
        auto_ingested: true,
        skip: 0,
        limit: 20,
      }))
      expect(router.navigate).not.toHaveBeenCalledWith("map", null)
    })
  })

  describe("_changePage", () => {
    it("翻页时更新 skip 并重新加载", async () => {
      state.currentProjectId = "p1"
      worldView._total = 50
      worldView._filters.skip = 0
      api.world.listEntities.mockResolvedValue({ items: [], total: 50 })

      await worldView._changePage(1)

      expect(worldView._filters.skip).toBe(20)
      expect(api.world.listEntities).toHaveBeenCalledWith(expect.objectContaining({ skip: 20, limit: 20 }))
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
      const html = vi.mocked(showModal).mock.calls[0][1]
      expect(html).toContain("create-entity-name")
    })

    it("409 重复时显示确认并支持强制创建", async () => {
      state.currentProjectId = "p1"
      api.world.createEntity
        .mockRejectedValueOnce({ status: 409, message: "Conflict", detail: { requires_confirmation: true, similar_entities: [{ id: "e1", name: "张三" }] } })
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
      api.world.listRelationships.mockResolvedValue({ items: [{ id: "r1", source_id: "src", target_id: "tgt", relation_type: "friend_of" }] })
      const html = await worldView._renderRelations()
      expect(html).toContain('data-action="delete-relation"')
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
    })
  })

  describe("showRelationCreateForm", () => {
    it("showRelationCreateForm 调用 showModal", () => {
      worldView.showRelationCreateForm()
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("deleteRelation", () => {
    it("deleteRelation 调用 confirmAction", () => {
      worldView.deleteRelation("r1")
      expect(confirmAction).toHaveBeenCalled()
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
      expect(html).toContain("炎帝")
      expect(html).toContain("称号")
      expect(html).toContain("80%")
      expect(html).toContain('data-action="delete-alias"')
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
      expect(router.navigate).toHaveBeenCalledWith("world", "objects")
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

  it.each([
    {
      name: "调用 API 并刷新",
      mock: () => api.world.mergeEntity.mockResolvedValue({ target_entity_id: "target-1" }),
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
      expect(router.refresh).toHaveBeenCalled()
    }
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
})
