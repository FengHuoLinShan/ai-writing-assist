import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { createScene, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — 场景工作台", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({
      title: "场景入口 E2E 测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectWorkbench(project, "outline", "scenes")
  })

  test("outline/scenes 直接显示场景工作台", async ({ page }) => {
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)
    await expect(scenesTab).toHaveText("场景")

    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()
    await expect(page.locator('.nav-item[data-view="scene"]')).toHaveCount(0)
  })

  test("从大纲其他子标签返回场景工作台", async ({ page }) => {
    const sceneCurrent = page.locator('.subnav-item[data-action="nav-scenes"]')
    const threads = page.locator('.subnav-item[data-action="nav-threads"]')
    await expect(sceneCurrent).toHaveJSProperty("tagName", "SPAN")
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
    await expect(threads).toHaveAttribute("type", "button")
    await expect(threads).not.toHaveAttribute("aria-current", /.+/)

    await threads.focus()
    await threads.press("Enter")
    await expect(page).toHaveURL(/#workbench\/[^/]+\/outline\/threads/)
    await expect(threads).toHaveAttribute("aria-current", "page")

    const headerScenes = page.locator('.subnav-item[data-action="nav-scenes"]')
    await expect(headerScenes).toHaveAttribute("type", "button")
    await headerScenes.focus()
    await headerScenes.press(" ")

    await expect(page.locator(SEL.viewTitle)).toHaveText("故事结构")
    await expect(page).toHaveURL(/#workbench\/[^/]+\/outline\/scenes/)
    await expect(sceneCurrent).toHaveJSProperty("tagName", "SPAN")
    await expect(sceneCurrent).toHaveAttribute("aria-current", "page")
    await expect(page.locator('[aria-label="场景筛选"]')).toBeVisible()
  })

  test("按名称选择 Scene 完成合并，请求仍使用 ID", async ({ page }) => {
    const target = await createScene(testProjectId, {
      scene_index: 0,
      title: "密道入口",
      goal: "找到进入王宫的路线",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const source = await createScene(testProjectId, {
      scene_index: 1,
      title: "潜入王宫",
      goal: "取得密信",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    const targetRow = page.locator(".scene-workbench-row", { hasText: "密道入口" })
    await targetRow.locator('[data-action="select-workbench-scene"]').click()
    await page.locator('.scene-detail-panel [data-action="start-merge-scene"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("选择要合并的场景")

    const picker = page.locator("#scene-merge-reference-picker")
    await picker.locator("[data-reference-query]").fill("潜入王宫")
    await picker.locator("[data-reference-result]", { hasText: "潜入王宫" }).click()
    await expect(picker.locator("[data-reference-selected]")).toContainText("潜入王宫")
    await page.getByRole("button", { name: "预览合并影响" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并场景影响预览")

    const mergeRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return request.method() === "POST"
        && url.pathname.endsWith("/api/outline/scene-workbench/merge")
    })
    await page.getByRole("button", { name: "确认合并" }).click()
    const payload = (await mergeRequest).postDataJSON()

    expect(payload).toEqual({
      target_scene_id: target.id,
      source_scene_ids: [source.id],
      confirmed: true,
    })
    await expect(page.locator(SEL.toastContainer)).toContainText("场景已合并", { timeout: 10000 })
  })
})
