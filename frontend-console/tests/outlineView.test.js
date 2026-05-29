/**
 * outlineView 测试
 *
 * 覆盖生命周期、5 个子视图渲染、CRUD、提取任务和事件绑定。
 */
import { describe, it, expect, vi, beforeEach } from "vitest"
import outlineView from "../views/outlineView.js"

beforeEach(() => {
  state.currentProjectId = null
  state.currentSubView = null
  outlineView._threads = []
  outlineView._arcs = []
  outlineView._chapters = []
  outlineView._foreshadowing = []
  outlineView._reveals = []
  outlineView._extractionTasks = {
    world: { taskId: null, status: "idle", message: "" },
    plot: { taskId: null, status: "idle", message: "" },
    cards: { taskId: null, status: "idle", message: "" },
  }
  outlineView._extractionTimer = null
  vi.clearAllMocks()
})

// ============================================================
// onEnter
// ============================================================

describe("onEnter", () => {
  it("无项目时设置空数据列表", async () => {
    await outlineView.onEnter()
    expect(outlineView._threads).toEqual([])
    expect(outlineView._arcs).toEqual([])
    expect(outlineView._chapters).toEqual([])
  })

  it("有项目时加载全部 5 组数据", async () => {
    state.currentProjectId = "p1"
    api.outline.listThreads.mockResolvedValue({ items: [{ id: "t1", name: "主线" }] })
    api.outline.listArcs.mockResolvedValue({ items: [{ id: "a1", title: "第一卷" }] })
    api.outline.listChapterCards.mockResolvedValue({ items: [{ id: "c1", chapter_index: 1 }] })
    api.outline.listForeshadowing.mockResolvedValue({ items: [{ id: "f1", name: "伏笔1" }] })
    api.outline.listReveals.mockResolvedValue({ items: [{ id: "r1", target_type: "character" }] })

    await outlineView.onEnter()

    expect(outlineView._threads).toHaveLength(1)
    expect(outlineView._arcs).toHaveLength(1)
    expect(outlineView._chapters).toHaveLength(1)
    expect(outlineView._foreshadowing).toHaveLength(1)
    expect(outlineView._reveals).toHaveLength(1)
  })

  it("API 失败时数据为空", async () => {
    state.currentProjectId = "p1"
    api.outline.listThreads.mockRejectedValue(new Error("失败"))

    await outlineView.onEnter()

    expect(outlineView._threads).toEqual([])
  })
})

// ============================================================
// render
// ============================================================

describe("render", () => {
  it("总是渲染子标签导航", async () => {
    state.currentSubView = "threads"
    const html = await outlineView.render()
    expect(html).toContain("剧情线")
    expect(html).toContain("篇章纲")
    expect(html).toContain("data-action=\"nav-threads\"")
    expect(html).toContain("data-action=\"nav-arcs\"")
    expect(html).toContain("data-action=\"nav-chapters\"")
    expect(html).toContain("data-action=\"nav-foreshadowing\"")
    expect(html).toContain("data-action=\"nav-reveals\"")
  })

  it("无项目时各子视图显示空提示", async () => {
    state.currentSubView = "threads"
    const html = await outlineView.render()
    expect(html).toContain("请先选择项目")
  })

  it("有项目时渲染当前子视图", async () => {
    state.currentProjectId = "p1"
    state.currentSubView = "threads"
    outlineView._threads = [{ id: "t1", name: "主线", thread_type: "main" }]
    const html = await outlineView.render()
    expect(html).toContain("主线")
  })
})

// ============================================================
// 剧情线子视图
// ============================================================

describe("剧情线", () => {
  describe("_renderThreads", () => {
    it("无项目显示空提示", async () => {
      const html = await outlineView._renderThreads()
      expect(html).toContain("请先选择项目")
    })

    it("无数据显示空状态", async () => {
      state.currentProjectId = "p1"
      outlineView._threads = []
      const html = await outlineView._renderThreads()
      expect(html).toContain("暂无剧情线")
    })

    it("渲染列表包含操作按钮", async () => {
      state.currentProjectId = "p1"
      outlineView._threads = [
        { id: "t1", name: "主线", thread_type: "main", current_stage: "developing", planned_payoff_chapter: 20 },
      ]
      const html = await outlineView._renderThreads()
      expect(html).toContain("主线")
      expect(html).toContain("第20章")
      expect(html).toContain("data-action=\"delete-thread\"")
    })
  })

  describe("_createThread", () => {
    it("调用 showModal 显示创建表单", () => {
      outlineView._createThread()
      expect(showModal).toHaveBeenCalled()
      const html = vi.mocked(showModal).mock.calls[0][1]
      expect(html).toContain("th-name")
    })
  })

  describe("_deleteThread", () => {
    it("调用 confirmAction 进行二次确认", () => {
      outlineView._deleteThread("t1")
      expect(confirmAction).toHaveBeenCalled()
      expect(confirmAction).toHaveBeenCalledWith(
        "确定删除此剧情线？",
        expect.any(Function),
        "确认删除",
      )
    })
  })
})

// ============================================================
// 篇章纲子视图
// ============================================================

describe("篇章纲", () => {
  describe("_renderArcs", () => {
    it("无项目显示空提示", async () => {
      const html = await outlineView._renderArcs()
      expect(html).toContain("请先选择项目")
    })

    it("无数据显示空状态", async () => {
      state.currentProjectId = "p1"
      const html = await outlineView._renderArcs()
      expect(html).toContain("暂无篇章纲")
    })

    it("渲染卡片包含高潮和目标", async () => {
      state.currentProjectId = "p1"
      outlineView._arcs = [{ id: "a1", title: "第一卷", start_chapter: 1, end_chapter: 10, arc_goal: "建立世界", core_conflict: "对抗", climax: "大战" }]
      const html = await outlineView._renderArcs()
      expect(html).toContain("第一卷")
      expect(html).toContain("建立世界")
      expect(html).toContain("对抗")
      expect(html).toContain("大战")
      expect(html).toContain("data-action=\"delete-arc\"")
    })
  })

  describe("_createArc", () => {
    it("调用 showModal", () => {
      outlineView._createArc()
      expect(showModal).toHaveBeenCalled()
    })
  })
})

// ============================================================
// 章节卡子视图
// ============================================================

describe("章节卡", () => {
  describe("_renderChapters", () => {
    it("无项目显示空提示", async () => {
      const html = await outlineView._renderChapters()
      expect(html).toContain("请先选择项目")
    })

    it("渲染列表包含确认/编辑/删除按钮", async () => {
      state.currentProjectId = "p1"
      outlineView._chapters = [
        { id: "c1", chapter_index: 1, title: "第一章", chapter_goal: "开场", status: "candidate" },
        { id: "c2", chapter_index: 2, title: "第二章", status: "canonical" },
      ]
      const html = await outlineView._renderChapters()
      expect(html).toContain("data-action=\"confirm-chapter\"")
      expect(html).toContain("data-action=\"edit-chapter\"")
      expect(html).toContain("data-action=\"delete-chapter\"")
      expect(html).toContain("data-action=\"view-chapter\"")
    })
  })

  describe("_confirmChapter", () => {
    it("确认后调用 API 更新为正史", async () => {
      state.currentProjectId = "p1"
      api.outline.updateChapterCard.mockResolvedValue({})
      outlineView._confirmChapter("c1", "第一章")
      // confirmAction 会异步调用回调
      const fn = vi.mocked(confirmAction).mock.calls[0][1]
      await fn()
      expect(api.outline.updateChapterCard).toHaveBeenCalledWith("c1", { status: "canonical" }, "p1")
    })
  })

  describe("_deleteChapter", () => {
    it("二次确认后调用 API 删除", async () => {
      state.currentProjectId = "p1"
      api.outline.deleteChapterCard.mockResolvedValue({})
      outlineView._deleteChapter("c1")
      const fn = vi.mocked(confirmAction).mock.calls[0][1]
      await fn()
      expect(api.outline.deleteChapterCard).toHaveBeenCalledWith("c1", { novel_id: "p1" })
    })
  })
})

// ============================================================
// 伏笔计划子视图
// ============================================================

describe("伏笔计划", () => {
  describe("_renderForeshadowing", () => {
    it("无项目显示空提示", async () => {
      const html = await outlineView._renderForeshadowing()
      expect(html).toContain("请先选择项目")
    })

    it("渲染伏笔列表", async () => {
      state.currentProjectId = "p1"
      outlineView._foreshadowing = [{ id: "f1", name: "神秘匕首", planned_seed_chapter: 3, planned_payoff_chapter: 15 }]
      const html = await outlineView._renderForeshadowing()
      expect(html).toContain("神秘匕首")
      expect(html).toContain("第3章")
      expect(html).toContain("第15章")
    })
  })
})

// ============================================================
// 信息揭示子视图
// ============================================================

describe("信息揭示", () => {
  describe("_renderReveals", () => {
    it("无项目显示空提示", async () => {
      const html = await outlineView._renderReveals()
      expect(html).toContain("请先选择项目")
    })

    it("渲染揭示列表", async () => {
      state.currentProjectId = "p1"
      outlineView._reveals = [{ id: "r1", target_type: "character", target_id: "uuid-1234", secret_summary: "他就是凶手", reveal_stages: [{ stage: 1 }] }]
      const html = await outlineView._renderReveals()
      expect(html).toContain("character")
      expect(html).toContain("他就是凶手")
      expect(html).toContain("1 个阶段")
    })
  })
})

// ============================================================
// 提取任务
// ============================================================

describe("提取任务", () => {
  describe("_submitExtraction", () => {
    it("无项目显示警告", async () => {
      await outlineView._submitExtraction("world", "world_entity_extraction")
      expect(toast).toHaveBeenCalledWith("请先选择项目", "warning")
    })

    it("提交世界对象抽取任务", async () => {
      state.currentProjectId = "p1"
      state.currentSubView = "threads"
      document.body.innerHTML = '<input id="ext-start" value="1"/> <input id="ext-end" value="5"/>'
      api.tasks.submit.mockResolvedValue({ task_id: "tw1" })

      await outlineView._submitExtraction("world", "world_entity_extraction")

      expect(api.tasks.submit).toHaveBeenCalledWith("world_entity_extraction", {
        novel_id: "p1", start_chapter: 1, end_chapter: 5,
      })
      expect(outlineView._extractionTasks.world.status).toBe("running")
    })

    it("章节卡提取走独立方法", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<input id="ext-start" value="1"/> <input id="ext-end" value="3"/>'
      vi.mocked(prompt).mockReturnValueOnce("1").mockReturnValueOnce("3")
      api.outline.listChapterCards.mockResolvedValue({ items: [] })

      await outlineView._submitExtraction("cards", "chapter_card_extraction")

      expect(showModal).toHaveBeenCalled()
    })
  })

  describe("_pollExtractionTasks", () => {
    it("无运行中任务时清除定时器", async () => {
      outlineView._extractionTimer = setInterval(() => {}, 1000)
      await outlineView._pollExtractionTasks()
      expect(outlineView._extractionTimer).toBeNull()
    })

    it("任务完成时更新状态", async () => {
      outlineView._extractionTimer = setInterval(() => {}, 1000)
      outlineView._extractionTasks = { world: { taskId: "t1", status: "running" } }
      api.tasks.getStatus.mockResolvedValue({ status: "done" })

      await outlineView._pollExtractionTasks()

      expect(outlineView._extractionTasks.world.status).toBe("done")
    })

    it("任务失败时更新状态", async () => {
      outlineView._extractionTimer = setInterval(() => {}, 1000)
      outlineView._extractionTasks = { world: { taskId: "t1", status: "running" } }
      api.tasks.getStatus.mockResolvedValue({ status: "failed", error_message: "超时" })

      await outlineView._pollExtractionTasks()

      expect(outlineView._extractionTasks.world.status).toBe("failed")
    })
  })
})

// ============================================================
// _bindEvents
// ============================================================

describe("_bindEvents", () => {
  it("导航子视图", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="nav-threads">剧情线</button></div>'
    outlineView._bindEvents()
    document.querySelector("button").click()
    expect(router.navigate).toHaveBeenCalledWith("outline", "threads")
  })

  it("创建章节卡", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="create-chapter">新建</button></div>'
    const spy = vi.spyOn(outlineView, "_createChapter").mockImplementation(() => {})
    outlineView._bindEvents()
    document.querySelector("button").click()
    expect(spy).toHaveBeenCalled()
    spy.mockRestore()
  })

  it("删除篇章纲带 data-id", () => {
    document.body.innerHTML = '<div id="workspace-content"><button data-action="delete-arc" data-id="a1">删除</button></div>'
    const spy = vi.spyOn(outlineView, "_deleteArc").mockImplementation(() => {})
    outlineView._bindEvents()
    document.querySelector("button").click()
    expect(spy).toHaveBeenCalledWith("a1")
    spy.mockRestore()
  })
})
