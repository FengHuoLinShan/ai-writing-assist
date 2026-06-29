import { test, expect } from "@playwright/test"
import { openWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createDraft,
  createProject,
  createScene,
  listScenesOrdered,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("Scene 工作台", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("从写作页整理按钮进入场景工作台并定位当前 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 工作台跳转", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "写作联动 Scene",
      goal: "进入宫门",
      core_conflict: "守卫阻拦",
      must_happen: "交出令牌",
      must_not_happen: "身份暴露",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "writing")
    await page.locator('[data-action="open-scene-workbench"]').click()

    await expect(page.locator("#view-title")).toHaveText("场景")
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveClass(/is-selected/)
  })

  test("未归类章节可以分配到 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 分配", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "目标 Scene",
      goal: "整理章节",
      core_conflict: "结构混乱",
      must_happen: "章节归位",
      must_not_happen: "误删正文",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")
    await createDraft(project.id, 3, "第三章", "未归类正文")

    await openWorkbench(page, project, "scene")
    await expect(page.locator(".scene-workbench-row--unassigned")).toContainText("第 3 章")
    page.once("dialog", (dialog) => dialog.accept(scene.id))
    await page.locator('[data-action="assign-unassigned-chapter"]').click()

    await expect(page.locator(".scene-workbench-row--unassigned")).toHaveCount(0, { timeout: 10000 })
    const scenes = await listScenesOrdered(project.id)
    expect(scenes[0].chapter_ids).toEqual(["1", "3"])
  })

  test("拆分必须先展示影响预览，确认后才执行", async ({ page }) => {
    const project = await createProject({ title: "Scene 拆分", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "长 Scene",
      goal: "潜入",
      core_conflict: "守卫阻拦",
      must_happen: "拿到文书",
      must_not_happen: "身份暴露",
      chapter_ids: ["1", "2"],
    })

    await openWorkbench(page, project, "scene", scene.id)
    page.once("dialog", (dialog) => dialog.accept("2"))
    await page.locator('[data-action="start-split-scene"]').click()

    await expect(page.locator("#modal-title")).toHaveText("拆分 Scene 影响预览")
    let scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(1)

    await page.getByRole("button", { name: "确认拆分" }).click()
    await expect(page.locator("#toast-container")).toContainText("Scene 已拆分", { timeout: 10000 })
    scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(2)
    expect(scenes[0].chapter_ids).toEqual(["1"])
    expect(scenes[1].chapter_ids).toEqual(["2"])
  })

  test("编辑 Scene 字段后写作页驾驶舱刷新", async ({ page }) => {
    const project = await createProject({ title: "Scene 编辑联动", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "旧标题",
      goal: "旧目标",
      core_conflict: "冲突",
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "scene", scene.id)
    await page.locator("#scene-detail-title").fill("新标题")
    await page.locator("#scene-detail-goal").fill("新目标")
    await page.locator('[data-action="save-scene-detail"]').click()
    await expect(page.locator("#toast-container")).toContainText("Scene 已保存", { timeout: 10000 })
    await page.locator('[data-action="open-writing-scene"]').click()

    await expect(page.locator("#view-title")).toHaveText("写作台")
    await expect(page.locator("#writing-panel-container")).toContainText("新标题")
    await expect(page.locator("#writing-panel-container")).toContainText("新目标")
  })

  test("窄屏下详情进入抽屉，列表仍是主操作面", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 })
    const project = await createProject({ title: "Scene 移动端", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await createScene(project.id, {
      scene_index: 0,
      title: "移动端 Scene",
      goal: "目标",
      core_conflict: "冲突",
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })

    await openWorkbench(page, project, "scene")

    await expect(page.locator(".scene-workbench__organize")).toBeVisible()
    await expect(page.locator(".scene-workbench-drawer")).toBeVisible()
    await expect(page.locator('[data-action="close-scene-detail"]')).toBeVisible()
  })
})
