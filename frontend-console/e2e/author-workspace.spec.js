import { test, expect } from "./fixtures.js"
import {
  cleanupProject,
  createDraft,
  createProject,
  waitForBackend,
} from "./helpers/api-client.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { SEL } from "./helpers/selectors.js"

test.describe("作者任务工作台", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60_000)
  })

  test.afterEach(async () => {
    if (project?.id) await cleanupProject(project.id)
    project = null
  })

  test("返回作者两步内继续最近正文，并在 390px 保留带文字导航", async ({ page }) => {
    project = await createProject({ title: "今日工作续写", genre: "fantasy", language: "zh" })
    await createDraft(project.id, 3, "雾港来信", "潮声越过窗沿。")

    await page.goto("/")
    await page.evaluate((projectData) => {
      localStorage.setItem("novel_currentProjectId", projectData.id)
      localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    }, project)
    await page.reload()

    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/today$`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("今日工作")
    await expect(page.getByRole("heading", { name: "雾港来信" })).toBeVisible()

    await page.setViewportSize({ width: 390, height: 844 })
    for (const label of ["首页", "写作", "世界", "结构", "全部"]) {
      await expect(page.locator(".sidebar-mobile-nav").getByRole("button", { name: label })).toBeVisible()
    }
    await expectNoPageOverflow(page)

    await page.getByRole("button", { name: "继续写作" }).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/writing`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
  })

  test("失效的上次作品会清除并回到作品档案", async ({ page }) => {
    const staleId = "00000000-0000-4000-8000-000000000099"
    await page.goto("/")
    await page.evaluate((projectId) => {
      localStorage.setItem("novel_currentProjectId", projectId)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id: projectId, title: "已失效作品" }))
    }, staleId)
    await page.reload()

    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案")
    await expect(page).toHaveURL(/#project$/)
    await expect(page.locator(SEL.toastContainer)).toContainText("上次打开的作品已不可用")
    await expect.poll(() => page.evaluate(() => localStorage.getItem("novel_currentProjectId"))).toBeNull()
  })
})
