import { beforeEach, describe, expect, it, vi } from "vitest"
import worldBibleView from "../views/worldBibleView.js"
import { clearDocument, resetState } from "./helpers.js"

const page = {
  id: "page-1",
  novel_id: "p1",
  page_type: "background",
  title: "世界基本背景",
  status: "draft",
  free_text: "已有设定正文",
}

beforeEach(() => {
  resetState({ currentProjectId: "p1" })
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  worldBibleView._pages = []
  worldBibleView._activePage = null
  worldBibleView._suggestions = []
  worldBibleView._conflicts = []
  worldBibleView._task = null
  if (worldBibleView._projectionPoller?.stop) worldBibleView._projectionPoller.stop()
  worldBibleView._projectionPoller = null
})

describe("worldBibleView", () => {
  it("新建页面使用应用内弹窗，不依赖浏览器 prompt", async () => {
    api.world.listBiblePages.mockResolvedValue({ items: [], total: 0 })
    api.world.createBiblePage.mockResolvedValue({ ...page, title: "种族设定", page_type: "species" })

    document.body.innerHTML = await worldBibleView.render()
    worldBibleView.bindEvents()
    document.querySelector("[data-action='bible-new-page']").click()

    expect(prompt).not.toHaveBeenCalled()
    expect(showModal).toHaveBeenCalledWith("新建世界书页面", expect.stringContaining("bible-create-title"), expect.any(Array))

    document.body.innerHTML = showModal.mock.calls[0][1]
    document.getElementById("bible-create-title").value = "种族设定"
    document.getElementById("bible-create-type").value = "species"
    await showModal.mock.calls[0][2][0].handler()

    expect(api.world.createBiblePage).toHaveBeenCalledWith({
      novel_id: "p1",
      title: "种族设定",
      page_type: "species",
      status: "draft",
    })
    expect(router.refresh).toHaveBeenCalled()
  })

  it("刷新投影后轮询任务，并用当前项目 ID 查询状态", async () => {
    worldBibleView._activePage = page
    api.world.refreshBibleProjection.mockResolvedValue({ task_id: "task-1", existing: false })
    api.tasks.get
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "pending",
        progress: 0,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "pending",
        progress: 0,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })
      .mockResolvedValueOnce({
        task_id: "task-1",
        task_type: "world_bible_projection_refresh",
        status: "done",
        progress: 1,
        meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
      })

    await worldBibleView._refreshProjection(false)

    expect(router.refresh).toHaveBeenCalled()
    await worldBibleView._restoreProjectionTask(page)
    await vi.waitFor(() => {
      expect(worldBibleView._task.status).toBe("done")
    })
    expect(api.world.refreshBibleProjection).toHaveBeenCalledWith("page-1", "p1", "context_brief", false)
    expect(api.tasks.get).toHaveBeenCalledWith("task-1", "p1")
    expect(localStorage.getItem("worldBibleProjection:p1:page-1:context_brief")).toBe("task-1")
    expect(router.renderCurrentView).toHaveBeenCalled()
  })

  it("普通刷新遇到已完成任务时保留 task_id，刷新后仍可强制重跑", async () => {
    worldBibleView._activePage = page
    const err = new Error("请求失败：status: projection_task_finished；task_id: task-done；task_status: done")
    err.status = 409
    api.world.refreshBibleProjection.mockRejectedValue(err)
    api.tasks.get.mockResolvedValue({
      task_id: "task-done",
      task_type: "world_bible_projection_refresh",
      status: "done",
      progress: 1,
      meta: { novel_id: "p1", page_id: "page-1", projection_type: "context_brief" },
    })

    await worldBibleView._refreshProjection(false)

    expect(localStorage.getItem("worldBibleProjection:p1:page-1:context_brief")).toBe("task-done")
    expect(api.tasks.get).toHaveBeenCalledWith("task-done", "p1")
    expect(worldBibleView._task.status).toBe("done")
    expect(worldBibleView._task.error_message).toContain("强制重新刷新")
    expect(router.refresh).toHaveBeenCalled()
  })

  it("打开建议和冲突弹窗时使用世界书专用过滤条件", async () => {
    api.world.listSuggestions.mockResolvedValue({ items: [], total: 0 })
    api.world.listWorldConflicts.mockResolvedValue({ items: [], total: 0 })

    await worldBibleView._openSuggestions()
    await worldBibleView._openConflicts()

    expect(api.world.listSuggestions).toHaveBeenCalledWith({
      novel_id: "p1",
      source_module: "imports",
      status: "pending",
    })
    expect(api.world.listWorldConflicts).toHaveBeenCalledWith({ novel_id: "p1", status: "pending" })
    expect(showModal.mock.calls[0][0]).toBe("创设建议")
    expect(showModal.mock.calls[1][0]).toBe("冲突检查")
  })
})
