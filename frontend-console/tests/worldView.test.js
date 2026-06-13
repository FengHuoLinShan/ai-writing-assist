/**
 * worldView 测试
 *
 * 覆盖生命周期、3 个子视图（候选清洗已移除）、实体 CRUD、关系和别名管理。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import worldView from "../views/worldView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = null
  worldView._entities = []
  worldView._batches = []
  worldView._total = 0
  worldView._filters = { entity_type: "", status: "", q: "", skip: 0, limit: 20 }
  worldView._autoExtractOpen = false
  worldView._autoExtractTaskId = null
  worldView._autoExtractStatus = "就绪"
  worldView._autoExtractTimer = null
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

  it("API 失败时设置空列表", async () => {
    state.currentProjectId = "p1"
    api.world.listEntities.mockRejectedValue(new Error("失败"))

    await worldView.onEnter()

    expect(worldView._entities).toEqual([])
  })
})

// ============================================================
// render
// ============================================================

describe("render", () => {
  it("渲染子标签导航（无候选清洗）", async () => {
    const html = await worldView.render()
    expect(html).toContain("对象库")
    expect(html).not.toContain("候选清洗")
    expect(html).toContain("关系")
    expect(html).toContain("别名")
  })
})

// ============================================================
// 对象库
// ============================================================

describe("对象库", () => {
  describe("_renderEntityList", () => {
    it("空列表显示空状态", () => {
      const html = worldView._renderEntityList()
      expect(html).toContain("还没有世界对象")
      expect(html).toContain('data-action="new"')
    })

    it("渲染实体表格", () => {
      worldView._entities = [{ id: "e1", name: "王都", entity_type: "location", status: "canonical", summary: "首都" }]
      const html = worldView._renderEntityList()
      expect(html).toContain("王都")
      expect(html).toContain("location")
      expect(html).toContain("正史")
      expect(html).toContain('data-action="edit-entity"')
      expect(html).toContain('data-action="delete-entity"')
    })

    it("自动识别面板展开时显示", () => {
      worldView._autoExtractOpen = true
      const html = worldView._renderEntityList()
      expect(html).toContain("自动识别")
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
    it("调用 confirmAction", () => {
      worldView._entities = [{ id: "e1", name: "王都" }]
      worldView.deleteEntity("e1")
      expect(confirmAction).toHaveBeenCalled()
    })
  })

  describe("_showCreateForm", () => {
    it("调用 showModal 显示表单", () => {
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
      confirmAction.mockImplementation((_msg, onConfirm) => onConfirm())

      worldView._showCreateForm()
      const handler = vi.mocked(showModal).mock.calls[0][2][0].handler

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
    it("无项目显示空提示", async () => {
      const html = await worldView._renderRelations()
      expect(html).toContain("请先选择项目")
    })

    it("渲染关系列表", async () => {
      state.currentProjectId = "p1"
      api.world.listRelationships.mockResolvedValue({ items: [{ id: "r1", source_id: "src", target_id: "tgt", relation_type: "friend_of" }] })
      const html = await worldView._renderRelations()
      expect(html).toContain('data-action="delete-relation"')
    })
  })

  describe("showRelationCreateForm", () => {
    it("调用 showModal", () => {
      worldView.showRelationCreateForm()
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("deleteRelation", () => {
    it("调用 confirmAction", () => {
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
    it("无项目显示空提示", async () => {
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

      const handler = vi.mocked(showModal).mock.calls[0][2][0].handler
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
      await worldView._submitAutoExtract("world_entity_extraction")
      expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("提交抽取任务", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<input id="w-extract-start" value="1"/> <input id="w-extract-end" value="5"/>'
      api.tasks.submit.mockResolvedValue({ task_id: "t1" })

      await worldView._submitAutoExtract("world_entity_extraction")

      expect(api.tasks.submit).toHaveBeenCalledWith("world_entity_extraction", {
        novel_id: "p1", start_chapter: 1, end_chapter: 5,
      })
      expect(worldView._autoExtractTaskId).toBe("t1")
    })
  })

  describe("_pollAutoExtract", () => {
    it("任务完成时清理定时器并刷新列表", async () => {
      worldView._autoExtractTimer = setInterval(() => {}, 1000)
      state.currentProjectId = "p1"
      api.tasks.getStatus.mockResolvedValue({ status: "done" })
      api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "新实体" }] })

      await worldView._pollAutoExtract("t1")

      expect(worldView._autoExtractTimer).toBeNull()
      expect(localStorage.getItem("novel_world_extract_task")).toBeNull()
      expect(api.world.listEntities).toHaveBeenCalled()
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

  it("_mergeEntity 调用 API 并刷新", async () => {
    api.world.mergeEntity.mockResolvedValue({ target_entity_id: "target-1" })

    await worldView._mergeEntity("candidate-1", "target-1")

    expect(api.world.mergeEntity).toHaveBeenCalledWith("candidate-1", "target-1", "p1")
    expect(toast).toHaveBeenCalledWith("实体已合并", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("_mergeEntity API 错误时显示错误提示", async () => {
    api.world.mergeEntity.mockRejectedValue(new Error("合并失败"))

    await worldView._mergeEntity("candidate-1", "target-1")

    expect(toast).toHaveBeenCalledWith("合并失败", "error")
  })

  it("_rollbackEntity 调用 API 并刷新（无警告）", async () => {
    api.world.rollbackEntity.mockResolvedValue({})

    await worldView._rollbackEntity("entity-1", 12)

    expect(api.world.rollbackEntity).toHaveBeenCalledWith("entity-1", 12, "p1")
    expect(toast).toHaveBeenCalledWith("回滚完成", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("_rollbackEntity 显示警告当结果含 warnings", async () => {
    api.world.rollbackEntity.mockResolvedValue({ warnings: ["某字段缺失"] })

    await worldView._rollbackEntity("entity-1", 12)

    expect(toast).toHaveBeenCalledWith("回滚完成，存在警告", "warning")
  })

  it("_rollbackEntity API 错误时显示错误提示", async () => {
    api.world.rollbackEntity.mockRejectedValue(new Error("回滚失败"))

    await worldView._rollbackEntity("entity-1", 12)

    expect(toast).toHaveBeenCalledWith("回滚失败", "error")
  })

  it("_createKnowledge 校验 false_belief 必须填写误解", async () => {
    await worldView._createKnowledge("char-1", {
      target_entity_id: "entity-1",
      knowledge_level: "false_belief",
      known_content: "他以为真相如此",
    })

    expect(toast).toHaveBeenCalledWith("错误认知必须填写误解内容", "warning")
    expect(api.world.createKnowledge).not.toHaveBeenCalled()
  })

  it("_createKnowledge 调用 API 并刷新", async () => {
    api.world.createKnowledge.mockResolvedValue({ id: "k1" })

    await worldView._createKnowledge("char-1", {
      target_entity_id: "entity-1",
      knowledge_level: "false_belief",
      known_content: "他以为真相如此",
      misconception: "错误认知",
    })

    expect(api.world.createKnowledge).toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith("知识边界已添加", "success")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("_createKnowledge API 错误时显示错误提示", async () => {
    api.world.createKnowledge.mockRejectedValue(new Error("创建失败"))

    await worldView._createKnowledge("char-1", {
      target_entity_id: "entity-1",
      knowledge_level: "full",
      known_content: "他知道真相",
    })

    expect(toast).toHaveBeenCalledWith("创建失败", "error")
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
