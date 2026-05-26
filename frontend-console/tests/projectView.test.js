/**
 * projectView 测试
 *
 * 测试视图的业务逻辑行为（非 DOM 渲染细节）。
 * 通过 import 获取视图对象，全局 mock 在 setup.js 中提供。
 */

import { describe, it, expect, vi, beforeEach } from "vitest"
import projectView from "../views/projectView.js"

// 清理全局状态，确保各测试隔离
beforeEach(() => {
  _state.currentProjectId = null
  _state.currentProject = null
  _state.projects = []
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
      expect(_state.projects).toEqual(projects)
    })

    it("API 不可用时设置空列表", async () => {
      api.projects.list.mockRejectedValue(new Error("Network error"))

      await projectView.onEnter()

      expect(_state.projects).toEqual([])
    })

    it("自动选中已保存的项目", async () => {
      const projects = [
        { id: "p1", title: "项目A" },
        { id: "p2", title: "项目B" },
      ]
      api.projects.list.mockResolvedValue({ items: projects })
      _state.currentProjectId = "p1"

      await projectView.onEnter()

      expect(_state.currentProject).toEqual(projects[0])
    })

    it("已保存的项目被删除后清除状态", async () => {
      api.projects.list.mockResolvedValue({ items: [] })
      _state.currentProjectId = "p1"
      _state.currentProject = { id: "p1", title: "已删除项目" }

      await projectView.onEnter()

      expect(_state.currentProjectId).toBeNull()
      expect(_state.currentProject).toBeNull()
    })
  })

  // ============================================================
  // openProject
  // ============================================================

  describe("openProject", () => {
    it("选中项目并导航到 world 视图", () => {
      _state.projects = [{ id: "p1", title: "项目A" }]

      projectView.openProject("p1")

      expect(_state.currentProjectId).toBe("p1")
      expect(_state.currentProject?.title).toBe("项目A")
      expect(router.navigate).toHaveBeenCalledWith("world", "objects")
      expect(globalThis.toast).toHaveBeenCalled()
    })

    it("项目不存在时不操作", () => {
      projectView.openProject("nonexistent")

      expect(_state.currentProjectId).toBeNull()
      expect(router.navigate).not.toHaveBeenCalled()
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
      const html = showModalMock.mock.calls[0][1]
      const buttons = showModalMock.mock.calls[0][2]
      expect(title).toBe("新建项目")
      expect(html).toContain("create-title")
      expect(buttons).toHaveLength(1)
      expect(buttons[0].text).toBe("创建")
    })
  })

  // ============================================================
  // editProject
  // ============================================================

  describe("editProject", () => {
    it("项目存在时调用 showModal", () => {
      _state.projects = [{ id: "p1", title: "项目A", genre: "fantasy", current_stage: "writing" }]

      projectView.editProject("p1")

      expect(globalThis.showModal).toHaveBeenCalledOnce()
      const showModalMock = vi.mocked(globalThis.showModal)
      const title = showModalMock.mock.calls[0][0]
      const html = showModalMock.mock.calls[0][1]
      expect(title).toBe("编辑项目")
      expect(html).toContain("项目A")
      expect(html).toContain("fantasy")
    })

    it("项目不存在时不操作", () => {
      projectView.editProject("nonexistent")
      expect(globalThis.showModal).not.toHaveBeenCalled()
    })
  })

  // ============================================================
  // deleteProject
  // ============================================================

  describe("deleteProject", () => {
    it("调用 confirmAction 进行二次确认", () => {
      _state.projects = [{ id: "p1", title: "项目A" }]

      projectView.deleteProject("p1")

      expect(globalThis.confirmAction).toHaveBeenCalledOnce()
      const confirmMock = vi.mocked(globalThis.confirmAction)
      expect(confirmMock.mock.calls[0][0]).toContain("项目A")
      expect(confirmMock.mock.calls[0][2]).toBe("确认删除")
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
})
