/**
 * characterView 测试
 *
 * 覆盖生命周期、3 个子视图、人物 CRUD、知识边界、AI 建议和事件绑定。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import characterView from "../views/characterView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = null
  state.selectedItem = null
  state.rightPanel = null
  characterView._characters = []
  characterView._characterKnowledge = []
  characterView._apiAvailable = false
  if (characterView._pollTimer) {
    clearInterval(characterView._pollTimer)
    characterView._pollTimer = null
  }
  vi.useRealTimers()
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
    state.currentProjectId = "p1"
    api.character.list.mockResolvedValue({ items: [{ id: "c1", name: "张三" }] })

    await characterView.onEnter()

    expect(api.character.list).toHaveBeenCalledWith({ novel_id: "p1" })
    expect(characterView._characters).toHaveLength(1)
    expect(characterView._apiAvailable).toBe(true)
  })

  it("API 失败时设置空列表", async () => {
    state.currentProjectId = "p1"
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
    state.currentSubView = "list"
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
      { id: "c1", name: "张三", role: "protagonist", current_goal: "寻宝", currentstate: "健康" },
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
  it("从 API 获取完整数据并导航", async () => {
    state.currentProjectId = "p1"
    characterView._characters = [{ id: "c1", name: "张三", role: "protagonist" }]
    api.character.get.mockResolvedValue({
      id: "c1", name: "张三", role: "protagonist",
      desire: "权力", fear: "失败", secret: "身世",
      current_goal: "寻宝", currentstate: "健康", current_emotion: "平静",
      stance: "中立", voice_style: "冷静",
    })

    await characterView._selectCharacter("c1")

    expect(api.character.get).toHaveBeenCalledWith("c1", "p1")
    expect(state.selectedItem?.name).toBe("张三")
    expect(state.selectedItem?.desire).toBe("权力")
    expect(state.selectedItem?.secret).toBe("身世")
    expect(state.rightPanel?.title).toBe("张三")
    expect(router.navigate).toHaveBeenCalledWith("character", "detail")
  })

  it("API 失败时使用列表数据降级", async () => {
    state.currentProjectId = "p1"
    characterView._characters = [{ id: "c1", name: "张三", role: "protagonist" }]
    api.character.get.mockRejectedValue(new Error("网络错误"))

    await characterView._selectCharacter("c1")

    // 降级到列表数据
    expect(state.selectedItem?.name).toBe("张三")
    expect(router.navigate).toHaveBeenCalledWith("character", "detail")
  })

  it("未找到人物不操作", async () => {
    await characterView._selectCharacter("nonexistent")
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
    state.selectedItem = { id: "c1", name: "张三", role: "protagonist", desire: "权力", fear: "失败" }
    const html = characterView._renderDetail()
    expect(html).toContain("张三")
    expect(html).toContain("权力")
    expect(html).toContain("失败")
  })

  it("有 AI 建议时渲染建议区域", () => {
    state.selectedItem = {
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

describe("editCharacter", () => {
  it("未找到人物显示错误", () => {
    characterView.editCharacter("nonexistent")
    expect(toast).toHaveBeenCalledWith("未找到人物数据", "error")
  })

  it("找到人物时显示编辑模态框", () => {
    characterView._characters = [{ id: "c1", name: "张三", role: "protagonist" }]
    characterView.editCharacter("c1")
    expect(showModal).toHaveBeenCalled()
    const html = vi.mocked(showModal).mock.calls[0][1]
    expect(html).toContain("张三")
  })

  it("详情内容动态刷新后点击编辑档案仍然打开表单", () => {
    const char = { id: "c1", name: "张三", role: "protagonist" }
    state.selectedItem = char
    characterView._characters = [char]
    document.body.innerHTML = '<div id="workspace-content"><div class="subnav"></div></div>'
    characterView._bindEvents()

    document.getElementById("workspace-content").insertAdjacentHTML("beforeend", characterView._renderDetail())
    document.getElementById("btn-edit-character").click()

    expect(showModal).toHaveBeenCalled()
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
      state.selectedItem = { id: "c1", name: "张三" }
      state.currentProjectId = "p1"
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
      state.selectedItem = { id: "c1", name: "张三" }
      state.currentProjectId = "p1"
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
      state.selectedItem = { id: "c1", name: "张三" }
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

// ============================================================
// 人物档案抽取 + AI 建议刷新
// ============================================================

describe("人物档案抽取流程", () => {
  describe("_refreshSuggestions", () => {
    it("更新本地缓存的 ai_suggestions 并刷新 selectedItem", async () => {
      state.currentProjectId = "p1"
      const char = { id: "c1", name: "周明瑞", meta: {} }
      characterView._characters = [char]
      state.selectedItem = char

      api.character.getSuggestions.mockResolvedValue({
        suggestions: { desire: "追求武道巅峰", fear: "失去至亲之人" },
        updated_at: "2025-01-01T00:00:00Z",
      })

      await characterView._refreshSuggestions("c1")

      expect(char.meta.ai_suggestions).toEqual({
        desire: "追求武道巅峰",
        fear: "失去至亲之人",
      })
      expect(char.meta.ai_suggestions_at).toBe("2025-01-01T00:00:00Z")
      expect(state.selectedItem).toBe(char)
      expect(router.navigate).toHaveBeenCalledWith("character", "detail", false)
    })

    it("无建议时不更新 meta", async () => {
      state.currentProjectId = "p1"
      const char = { id: "c1", name: "周明瑞", meta: {} }
      characterView._characters = [char]

      api.character.getSuggestions.mockResolvedValue({
        suggestions: {},
        updated_at: null,
      })

      await characterView._refreshSuggestions("c1")

      expect(char.meta.ai_suggestions).toBeUndefined()
    })

    it("抽取完成但没有建议时提示没有新内容", async () => {
      state.currentProjectId = "p1"
      const char = { id: "c1", name: "周明瑞", meta: {} }
      characterView._characters = [char]

      api.character.getSuggestions.mockResolvedValue({
        suggestions: {},
        updated_at: null,
      })

      await characterView._refreshSuggestions("c1", { status: "no_chunks", fields: [] })

      expect(toast).toHaveBeenCalledWith(
        "人物抽取完成，但没有找到可提取的相关正文片段",
        "warning",
      )
    })

    it("抽取有降级告警时提示结果可能不准确", async () => {
      state.currentProjectId = "p1"
      const char = { id: "c1", name: "周明瑞", meta: {} }
      characterView._characters = [char]

      api.character.getSuggestions.mockResolvedValue({
        suggestions: { desire: "想要回家" },
        updated_at: null,
      })

      await characterView._refreshSuggestions("c1", {
        status: "ok",
        warnings: ["embedding 生成失败，本次生成人物档案可能不准确"],
      })

      expect(toast).toHaveBeenCalledWith(
        "embedding 生成失败，本次生成人物档案可能不准确",
        "warning",
      )
    })
  })

  describe("_applyAllSuggestions", () => {
    it("应用后正式字段更新且 ai_suggestions 被清除", async () => {
      state.currentProjectId = "p1"
      const char = {
        id: "c1",
        name: "周明瑞",
        desire: "",
        fear: "",
        meta: {
          ai_suggestions: { desire: "追求武道巅峰", fear: "失去至亲之人" },
          ai_suggestions_at: "2025-01-01T00:00:00Z",
        },
      }
      state.selectedItem = char
      characterView._characters = [char]

      api.character.applySuggestions.mockResolvedValue({
        id: "c1",
        name: "周明瑞",
        desire: "追求武道巅峰",
        fear: "失去至亲之人",
        meta: {},
      })

      await characterView._applyAllSuggestions()

      expect(api.character.applySuggestions).toHaveBeenCalledWith(
        "c1", "p1", ["desire", "fear"]
      )
      expect(state.selectedItem.desire).toBe("追求武道巅峰")
      expect(state.selectedItem.fear).toBe("失去至亲之人")
      expect(state.selectedItem.meta.ai_suggestions).toBeUndefined()
    })

    it("部分应用后剩余建议保留", async () => {
      state.currentProjectId = "p1"
      const char = {
        id: "c1",
        name: "周明瑞",
        desire: "",
        meta: {
          ai_suggestions: { desire: "追求武道巅峰", weakness: "过于重情" },
          ai_suggestions_at: "2025-01-01T00:00:00Z",
        },
      }
      state.selectedItem = char
      characterView._characters = [char]

      api.character.applySuggestions.mockResolvedValue({
        id: "c1",
        name: "周明瑞",
        desire: "追求武道巅峰",
        meta: {
          ai_suggestions: { weakness: "过于重情" },
          ai_suggestions_at: "2025-01-01T00:00:00Z",
        },
      })

      await characterView._applySuggestion("desire")

      expect(state.selectedItem.desire).toBe("追求武道巅峰")
      expect(state.selectedItem.meta.ai_suggestions).toEqual({ weakness: "过于重情" })
    })
  })

  describe("_extractCharacter + 轮询", () => {
    it("提交抽取任务并启动轮询", async () => {
      state.currentProjectId = "p1"
      const char = { id: "c1", name: "周明瑞" }
      characterView._characters = [char]

      api.character.extract.mockResolvedValue({ task_id: "t1" })
      api.tasks.getStatus.mockResolvedValue({ status: "pending" })

      await characterView._extractCharacter("c1")

      expect(api.character.extract).toHaveBeenCalledWith("c1", "p1")
      expect(characterView._pollTimer).not.toBeNull()
      clearInterval(characterView._pollTimer)
    })

    it("任务失败时提示失败而不是完成", async () => {
      vi.useFakeTimers()
      const onDone = vi.fn()

      api.tasks.getStatus.mockResolvedValue({
        status: "failed",
        error_message: "LLM 调用失败",
        result: {},
      })

      characterView._pollExtractionTasks(["t1"], onDone)
      await vi.advanceTimersByTimeAsync(5000)

      expect(onDone).not.toHaveBeenCalled()
      expect(api.character.list).not.toHaveBeenCalled()
      expect(toast).toHaveBeenCalledWith("人物抽取失败：LLM 调用失败", "error")
      expect(toast).not.toHaveBeenCalledWith("人物抽取完成", "success")
    })
  })

  describe("_refreshCharacterList 同步 selectedItem", () => {
    it("刷新列表后 selectedItem 指向新列表中的对象", async () => {
      state.currentProjectId = "p1"
      const oldChar = { id: "c1", name: "周明瑞", desire: "" }
      characterView._characters = [oldChar]
      state.selectedItem = oldChar

      api.character.list.mockResolvedValue({
        items: [{ id: "c1", name: "周明瑞", desire: "追求武道巅峰" }],
      })

      await characterView._refreshCharacterList()

      expect(characterView._characters).toHaveLength(1)
      const newChar = characterView._characters[0]
      expect(newChar.desire).toBe("追求武道巅峰")
      expect(state.selectedItem).toBe(newChar)
    })

    it("刷新列表后 selectedItem 不再指向旧对象", async () => {
      state.currentProjectId = "p1"
      const oldChar = { id: "c1", name: "周明瑞" }
      characterView._characters = [oldChar]
      state.selectedItem = oldChar

      api.character.list.mockResolvedValue({
        items: [{ id: "c1", name: "周明瑞", desire: "追求武道巅峰" }],
      })

      await characterView._refreshCharacterList()

      expect(state.selectedItem).not.toBe(oldChar)
    })
  })

  describe("_applyAllSuggestions meta 一致性", () => {
    it("全部应用后 meta 不应残留空 ai_suggestions", async () => {
      state.currentProjectId = "p1"
      const char = {
        id: "c1",
        name: "周明瑞",
        desire: "",
        meta: {
          ai_suggestions: { desire: "追求武道巅峰" },
          ai_suggestions_at: "2025-01-01T00:00:00Z",
        },
      }
      state.selectedItem = char
      characterView._characters = [char]

      api.character.applySuggestions.mockResolvedValue({
        id: "c1",
        name: "周明瑞",
        desire: "追求武道巅峰",
        meta: {},
      })

      await characterView._applyAllSuggestions()

      expect(state.selectedItem.desire).toBe("追求武道巅峰")
      expect(state.selectedItem.meta.ai_suggestions).toBeUndefined()
    })

    it("列表条目同步更新正式字段", async () => {
      state.currentProjectId = "p1"
      const char = {
        id: "c1",
        name: "周明瑞",
        desire: "",
        meta: { ai_suggestions: { desire: "追求武道巅峰" } },
      }
      state.selectedItem = char
      characterView._characters = [char]

      api.character.applySuggestions.mockResolvedValue({
        id: "c1",
        name: "周明瑞",
        desire: "追求武道巅峰",
        meta: {},
      })

      await characterView._applyAllSuggestions()

      expect(characterView._characters[0].desire).toBe("追求武道巅峰")
    })
  })
})
