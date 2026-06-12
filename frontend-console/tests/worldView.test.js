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
    api.world.listEntities.mockResolvedValue({ items: [{ id: "e1", name: "王都" }] })
    api.world.listEntityBatches.mockResolvedValue([{ batch_id: "b1", entities: [{ id: "e1", name: "王都", entity_type: "location" }] }])

    await worldView.onEnter()

    expect(api.world.listEntities).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(api.world.listEntityBatches).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(worldView._entities).toHaveLength(1)
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
  })

  describe("deleteAlias", () => {
    it("调用 confirmAction", () => {
      const fakeEvent = { target: document.createElement("button") }
      fakeEvent.target.setAttribute("data-alias", "炎帝")
      worldView.deleteAlias("a1", fakeEvent)
      expect(confirmAction).toHaveBeenCalled()
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
