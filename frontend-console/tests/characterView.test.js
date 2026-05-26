/**
 * characterView 测试
 *
 * 覆盖生命周期、3 个子视图、人物 CRUD、知识边界、AI 建议和事件绑定。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import characterView from "../views/characterView.js"

beforeEach(() => {
  _state.currentProjectId = null
  _state.currentSubView = null
  _state.selectedItem = null
  _state.rightPanel = null
  characterView._characters = []
  characterView._characterKnowledge = []
  characterView._apiAvailable = false
  vi.clearAllMocks()
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("无项目时设置空列表", async () => {
    await characterView.onEnter()
    expect(characterView._characters).toEqual([])
  })

  it("有项目时加载人物列表", async () => {
    _state.currentProjectId = "p1"
    api.character.list.mockResolvedValue({ items: [{ id: "c1", name: "张三" }] })

    await characterView.onEnter()

    expect(api.character.list).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(characterView._characters).toHaveLength(1)
    expect(characterView._apiAvailable).toBe(true)
  })

  it("API 失败时设置空列表", async () => {
    _state.currentProjectId = "p1"
    api.character.list.mockRejectedValue(new Error("网络错误"))

    await characterView.onEnter()

    expect(characterView._characters).toEqual([])
    expect(characterView._apiAvailable).toBe(false)
  })
})

// ============================================================
// render
// ============================================================

describe("render", () => {
  it("渲染子标签导航", async () => {
    const html = await characterView.render()
    expect(html).toContain("data-action=\"nav-list\"")
    expect(html).toContain("data-action=\"nav-detail\"")
    expect(html).toContain("data-action=\"nav-knowledge\"")
  })

  it("列表子视图调用 _renderList", async () => {
    _state.currentSubView = "list"
    characterView._apiAvailable = true
    const html = await characterView.render()
    expect(html).toContain("还没有人物档案")
  })
})

// ============================================================
// 人物列表
// ============================================================

describe("_renderList", () => {
  it("API 不可用显示错误状态", () => {
    const html = characterView._renderList()
    expect(html).toContain("无法连接到后端服务")
  })

  it("空列表显示空状态", () => {
    characterView._apiAvailable = true
    const html = characterView._renderList()
    expect(html).toContain("还没有人物档案")
    expect(html).toContain("data-action=\"new\"")
  })

  it("有数据时渲染表格", () => {
    characterView._apiAvailable = true
    characterView._characters = [
      { id: "c1", name: "张三", role: "protagonist", current_goal: "寻宝", current_state: "健康" },
    ]
    const html = characterView._renderList()
    expect(html).toContain("张三")
    expect(html).toContain("data-action=\"select-character\"")
    expect(html).toContain("data-action=\"edit-character\"")
  })
})

// ============================================================
// 选中人物
// ============================================================

describe("_selectCharacter", () => {
  it("更新状态并导航", () => {
    characterView._characters = [{ id: "c1", name: "张三", role: "protagonist" }]
    characterView._selectCharacter("c1")
    expect(_state.selectedItem?.name).toBe("张三")
    expect(_state.rightPanel?.title).toBe("张三")
    expect(router.navigate).toHaveBeenCalledWith("character", "detail")
  })

  it("未找到人物不操作", () => {
    characterView._selectCharacter("nonexistent")
    expect(router.navigate).not.toHaveBeenCalled()
  })
})

// ============================================================
// 人物档案详情
// ============================================================

describe("_renderDetail", () => {
  it("无选中人物显示空提示", () => {
    const html = characterView._renderDetail()
    expect(html).toContain("未选择人物")
    expect(html).toContain("data-action=\"nav-list\"")
  })

  it("渲染人物字段网格", () => {
    _state.selectedItem = { id: "c1", name: "张三", role: "protagonist", desire: "权力", fear: "失败" }
    const html = characterView._renderDetail()
    expect(html).toContain("张三")
    expect(html).toContain("权力")
    expect(html).toContain("失败")
  })

  it("有 AI 建议时渲染建议区域", () => {
    _state.selectedItem = {
      id: "c1", name: "张三", role: "protagonist",
      meta: { ai_suggestions: { desire: "财富" } },
    }
    const html = characterView._renderDetail()
    expect(html).toContain("AI 建议")
    expect(html).toContain("财富")
    expect(html).toContain("data-action=\"apply-all-suggestions\"")
    expect(html).toContain("data-action=\"apply-suggestion\"")
    expect(html).toContain("data-action=\"reject-suggestion\"")
  })
})

// ============================================================
// 新建/编辑人物
// ============================================================

describe("_showCreateForm", () => {
  it("调用 showModal 显示表单", () => {
    characterView._showCreateForm()
    expect(showModal).toHaveBeenCalled()
    const html = vi.mocked(showModal).mock.calls[0][1]
    expect(html).toContain("create-char-name")
  })
})

describe("_editCharacter", () => {
  it("未找到人物显示错误", () => {
    characterView._editCharacter("nonexistent")
    expect(toast).toHaveBeenCalledWith("未找到人物数据", "error")
  })

  it("找到人物时显示编辑模态框", () => {
    characterView._characters = [{ id: "c1", name: "张三", role: "protagonist" }]
    characterView._editCharacter("c1")
    expect(showModal).toHaveBeenCalled()
    const html = vi.mocked(showModal).mock.calls[0][1]
    expect(html).toContain("张三")
  })
})

// ============================================================
// 知识边界
// ============================================================

describe("知识边界", () => {
  describe("_renderKnowledge", () => {
    it("无选中人物显示空提示", async () => {
      const html = await characterView._renderKnowledge()
      expect(html).toContain("未选择人物")
    })

    it("加载知识并渲染", async () => {
      _state.selectedItem = { id: "c1", name: "张三" }
      _state.currentProjectId = "p1"
      api.character.listKnowledge.mockResolvedValue({
        items: [{ id: "k1", target_type: "location", target_name: "王都", knowledge_level: "full", known_content: "知道位置" }],
      })
      const html = await characterView._renderKnowledge()
      expect(api.character.listKnowledge).toHaveBeenCalledWith("c1", "p1")
      expect(html).toContain("张三 的知识边界")
      expect(html).toContain("王都")
      expect(html).toContain("完全知道")
    })

    it("API 失败时使用演示数据", async () => {
      _state.selectedItem = { id: "c1", name: "张三" }
      _state.currentProjectId = "p1"
      api.character.listKnowledge.mockRejectedValue(new Error("失败"))
      const html = await characterView._renderKnowledge()
      expect(characterView._characterKnowledge.length).toBeGreaterThan(0)
      expect(html).toContain("张三 的知识边界")
    })
  })

  describe("_addKnowledge", () => {
    it("无选中人物显示警告", () => {
      characterView._addKnowledge()
      expect(toast).toHaveBeenCalledWith("请先选择人物", "warning")
    })

    it("有选中人物显示表单", () => {
      _state.selectedItem = { id: "c1", name: "张三" }
      characterView._addKnowledge()
      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("_deleteKnowledge", () => {
    it("调用 confirmAction", () => {
      characterView._deleteKnowledge("k1")
      expect(confirmAction).toHaveBeenCalled()
    })
  })
})

// ============================================================
// 事件绑定
// ============================================================

describe("_bindEvents", () => {
  it("导航子视图", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="nav-list">列表</button></div>'
    characterView._bindEvents()
    document.querySelector("button").click()
    expect(router.navigate).toHaveBeenCalledWith("character", "list")
  })

  it("选择人物带 data-id", () => {
    const spy = vi.spyOn(characterView, "_selectCharacter").mockImplementation(() => {})
    document.body.innerHTML = '<div id="workspace-content"><button data-action="select-character" data-id="c1">查看</button></div>'
    characterView._bindEvents()
    document.querySelector("button").click()
    expect(spy).toHaveBeenCalledWith("c1")
    spy.mockRestore()
  })
})
