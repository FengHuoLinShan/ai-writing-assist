/**
 * projectView 测试
 *
 * 测试视图的业务逻辑行为（非 DOM 渲染细节）。
 * 通过 import 获取视图对象，全局 mock 在 setup.js 中提供。
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import projectView from "../views/projectView.js"
import { resetState, autoConfirm, captureModalHandler } from "./helpers.js"

// 清理全局状态，确保各测试隔离
beforeEach(() => {
  resetState()
  localStorage.clear()
  projectView._uploadProgress = null
  vi.clearAllMocks()
})

describe("projectView", () => {
  // ============================================================
  // onEnter
  // ============================================================

  describe("onEnter", () => {
    it("从 API 加载项目列表", async () => {
      const projects = [
        { id: "p1", title: "项目A", genre: "fantasy", current_stage: "world_building", status: "active" },
        { id: "p2", title: "项目B", genre: "scifi", current_stage: "writing", status: "active" },
      ]
      api.projects.list.mockResolvedValue({ items: projects })

      await projectView.onEnter()

      expect(api.projects.list).toHaveBeenCalledOnce()
      expect(state.projects).toEqual(projects)
    })

    it("API 不可用时设置空列表", async () => {
      api.projects.list.mockRejectedValue(new Error("Network error"))

      await projectView.onEnter()

      expect(state.projects).toEqual([])
    })

    it("自动选中已保存的项目", async () => {
      const projects = [
        { id: "p1", title: "项目A" },
        { id: "p2", title: "项目B" },
      ]
      api.projects.list.mockResolvedValue({ items: projects })
      state.currentProjectId = "p1"

      await projectView.onEnter()

      expect(state.currentProject).toEqual(projects[0])
    })

    it("已保存的项目被删除后清除状态", async () => {
      api.projects.list.mockResolvedValue({ items: [] })
      state.currentProjectId = "p1"
      state.currentProject = { id: "p1", title: "已删除项目" }
      state.viewStates.writing = {
        projectId: "p1",
        currentChapter: 1,
        currentContent: "旧项目章节正文",
      }
      localStorage.setItem("novel_currentProject", JSON.stringify(state.currentProject))

      await projectView.onEnter()

      expect(state.currentProjectId).toBeNull()
      expect(state.currentProject).toBeNull()
      expect(state.viewStates.writing).toBeUndefined()
      expect(localStorage.getItem("novel_currentProjectId")).toBeNull()
      expect(localStorage.getItem("novel_currentProject")).toBeNull()
    })
  })

  // ============================================================
  // openProject
  // ============================================================

  describe("openProject", () => {
    it("选中项目并导航到写作视图", () => {
      state.projects = [{ id: "p1", title: "项目A" }]

      projectView.openProject("p1")

      expect(state.currentProjectId).toBe("p1")
      expect(state.currentProject?.title).toBe("项目A")
      expect(router.navigate).toHaveBeenCalledWith("writing")
      expect(globalThis.toast).toHaveBeenCalled()
    })

    it("项目不存在时不操作", () => {
      projectView.openProject("nonexistent")

      expect(state.currentProjectId).toBeNull()
      expect(router.navigate).not.toHaveBeenCalled()
    })
  })

  describe("project stats and activity", () => {
    it("按最近活跃时间排序并显示统计待接入占位", async () => {
      state.projects = [
        { id: "old", title: "旧项目", created_at: "2026-01-01T00:00:00Z" },
        { id: "new", title: "新项目", updated_at: "2026-02-01T00:00:00Z" },
      ]

      const html = await projectView.render()

      expect(html.indexOf("新项目")).toBeLessThan(html.indexOf("旧项目"))
      expect(html).toContain("待接入")
      expect(html).toContain("统计接入后显示总字数")
      expect(html).toContain("统计接入后显示章节数")
      expect(html).toContain('data-action="continue-writing"')
    })

    it("已有统计字段时直接显示现有字段", () => {
      const stats = projectView._projectStats({ total_words: 12000, chapter_count: 8 })

      expect(stats.wordCountText).toBe("12,000")
      expect(stats.chapterCountText).toBe("8")
    })
  })

  // ============================================================
  // showCreateForm
  // ============================================================

  describe("showCreateForm", () => {
    it("调用 showModal 显示创建表单", () => {
      projectView.showCreateForm()

      expect(globalThis.showModal).toHaveBeenCalledOnce()
      const showModalMock = vi.mocked(globalThis.showModal)
      const title = showModalMock.mock.calls[0][0]
      const html = showModalMock.mock.calls[0][1].html
      const buttons = showModalMock.mock.calls[0][2]
      expect(title).toBe("新建项目")
      expect(html).toContain("create-title")
      expect(buttons).toHaveLength(1)
      expect(buttons[0].text).toBe("创建")
    })

    it("创建成功后导航到写作视图", async () => {
      api.projects.create.mockResolvedValue({ id: "p-new", title: "新项目" })
      projectView.showCreateForm()

      const handler = captureModalHandler()
      // 模拟用户输入
      const titleInput = document.createElement("input")
      titleInput.id = "create-title"
      titleInput.value = "新项目"
      document.body.appendChild(titleInput)

      await handler()

      expect(api.projects.create).toHaveBeenCalledWith({
        title: "新项目",
        genre: "",
        tone: "",
        language: "zh",
      })
      expect(state.currentProjectId).toBe("p-new")
      expect(router.navigate).toHaveBeenCalledWith("writing")

      titleInput.remove()
    })

    it("空标题提交时提示请输入项目标题", async () => {
      api.projects.create.mockResolvedValue({ id: "p-new", title: "新项目" })
      projectView.showCreateForm()

      const handler = captureModalHandler()
      const titleInput = document.createElement("input")
      titleInput.id = "create-title"
      titleInput.value = ""
      document.body.appendChild(titleInput)

      await handler()

      expect(api.projects.create).not.toHaveBeenCalled()
      expect(globalThis.toast).toHaveBeenCalledWith("请输入项目标题", "warning")

      titleInput.remove()
    })
  })

  // ============================================================
  // editProject
  // ============================================================

  describe("editProject", () => {
    it("项目存在时调用 showModal", () => {
      state.projects = [{ id: "p1", title: "项目A", genre: "fantasy", tone: "黑暗", target_length: "novel", current_stage: "writing" }]

      projectView.editProject("p1")

      expect(globalThis.showModal).toHaveBeenCalledOnce()
      const showModalMock = vi.mocked(globalThis.showModal)
      const title = showModalMock.mock.calls[0][0]
      const html = showModalMock.mock.calls[0][1].html
      expect(title).toBe("编辑项目")
      expect(html).toContain("项目A")
      expect(html).toContain("edit-tone")
      expect(html).toContain("edit-target-length")
    })

    it("项目不存在时不操作", () => {
      projectView.editProject("nonexistent")
      expect(globalThis.showModal).not.toHaveBeenCalled()
    })

    it("保存成功后同步项目列表与面包屑状态", async () => {
      state.projects = [{ id: "p1", title: "项目A", genre: "fantasy", tone: "黑暗", target_length: "novel" }]
      state.currentProjectId = "p1"
      state.currentProject = { ...state.projects[0] }

      const updated = { id: "p1", title: "项目A-改", genre: "武侠", tone: "热血", target_length: "epic" }
      api.projects.update.mockResolvedValue(updated)

      projectView.editProject("p1")
      const handler = captureModalHandler()

      const titleInput = document.createElement("input")
      titleInput.id = "edit-title"
      titleInput.value = "项目A-改"
      document.body.appendChild(titleInput)

      const genreInput = document.createElement("input")
      genreInput.id = "edit-genre"
      genreInput.value = "武侠"
      document.body.appendChild(genreInput)

      const toneInput = document.createElement("input")
      toneInput.id = "edit-tone"
      toneInput.value = "热血"
      document.body.appendChild(toneInput)

      const targetSelect = document.createElement("select")
      targetSelect.id = "edit-target-length"
      targetSelect.innerHTML = `<option value="">未设置</option><option value="epic" selected>史诗</option>`
      document.body.appendChild(targetSelect)

      await handler()

      expect(api.projects.update).toHaveBeenCalledWith("p1", {
        title: "项目A-改",
        genre: "武侠",
        tone: "热血",
        target_length: "epic",
        current_stage: null,
      })
      expect(state.projects[0]).toEqual(updated)
      expect(state.currentProject).toEqual(updated)

      titleInput.remove()
      genreInput.remove()
      toneInput.remove()
      targetSelect.remove()
    })
  })

  // ============================================================
  // deleteProject
  // ============================================================

  describe("deleteProject", () => {
    it("调用 confirmAction 进行二次确认", () => {
      state.projects = [{ id: "p1", title: "项目A" }]

      projectView.deleteProject("p1")

      expect(globalThis.confirmAction).toHaveBeenCalledOnce()
      const confirmMock = vi.mocked(globalThis.confirmAction)
      expect(confirmMock.mock.calls[0][0]).toContain("项目A")
      expect(confirmMock.mock.calls[0][2]).toBe("移至回收站")
    })

    it("确认后删除并调用 router.refresh 刷新列表", async () => {
      state.projects = [{ id: "p1", title: "项目A" }]
      api.projects.remove.mockResolvedValue({})
      autoConfirm()

      projectView.deleteProject("p1")
      // 等待 confirmAction 内的异步回调结算
      await Promise.resolve()
      await Promise.resolve()

      expect(api.projects.remove).toHaveBeenCalledWith("p1")
      // 回归：必须用 refresh（重新拉数据），而非同位置 navigate（会因 isSameRender 跳过 onEnter 显示旧数据）
      expect(router.refresh).toHaveBeenCalledOnce()
    })
  })

  // ============================================================
  // importFile
  // ============================================================

  // importFile() 创建离屏 input 并触发 click，
  // 属于浏览器交互行为，在 Vitest/happy-dom 环境无法完整测试。
  // 在 Playwright E2E 中覆盖。

  // ============================================================
  // _toggleImportSection
  // ============================================================

  describe("_toggleImportSection", () => {
    it("切换折叠状态并重定向", () => {
      const initial = projectView._importSectionOpen

      projectView._toggleImportSection()

      expect(projectView._importSectionOpen).toBe(!initial)
      expect(router.navigate).toHaveBeenCalledWith("project")
    })
  })

  describe("upload progress rendering", () => {
    it("使用 shared progress 样式显示导入阶段和真实百分比", () => {
      projectView._uploadProgress = {
        stage: "上传文件",
        percent: 42,
        message: "正在上传文件 42%",
      }

      const html = projectView._renderUploadProgress()

      expect(html).toContain("workflow-progress")
      expect(html).toContain("导入小说")
      expect(html).toContain("上传文件")
      expect(html).toContain("42%")
      expect(html).toContain('aria-valuenow="42"')
    })
  })

  describe("import history rendering", () => {
    it("转义后端返回的未知导入状态", async () => {
      state.currentProjectId = "p1"
      document.body.innerHTML = '<div id="import-list-body"></div>'
      api.imports.list.mockResolvedValue({
        items: [{
          file_name: "novel.txt",
          status: '<img src=x onerror="alert(1)">',
          imported_chapters: 1,
          total_chapters: 2,
        }],
      })

      await projectView._renderImportHistory()

      const container = document.getElementById("import-list-body")
      expect(container?.querySelector("img")).toBeNull()
      expect(container?.textContent).toContain('<img src=x onerror="alert(1)">')
    })
  })

  describe("批量项目操作", () => {
    it("批量移入回收站调用项目删除 API", async () => {
      state.projects = [{ id: "p1", title: "项目A" }, { id: "p2", title: "项目B" }]
      projectView._bulkSelections = { "project-cards": new Set(["p1", "p2"]) }
      api.projects.remove.mockResolvedValue({})
      autoConfirm()
      vi.spyOn(projectView, "onEnter").mockResolvedValue()

      await projectView._runProjectBulkAction("delete-projects")

      expect(api.projects.remove).toHaveBeenCalledWith("p1")
      expect(api.projects.remove).toHaveBeenCalledWith("p2")
      await vi.waitFor(() => {
        expect(toast).toHaveBeenCalledWith(expect.stringContaining("成功 2 / 2"), "success")
      })
    })
  })
})
