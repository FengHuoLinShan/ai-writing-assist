import { test, expect } from "./fixtures.js"
import {
  cleanupProject,
  createDraft,
  createEntity,
  createProject,
  createWorldBiblePage,
  waitForBackend,
} from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"
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
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/writing\\?home=1$`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
    await expect(page.getByRole("heading", { name: "雾港来信" })).toBeVisible()

    await page.setViewportSize({ width: 390, height: 844 })
    for (const label of ["写作", "世界", "结构", "全部"]) {
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

  for (const width of [1280, 390]) {
    test(`${width}px 资料库与作者任务闭环可恢复`, async ({ page }) => {
      test.setTimeout(60_000)
      project = await createProject({ title: `资料任务闭环 ${width}`, genre: "fantasy", language: "zh" })
      await createWorldBiblePage(project.id, {
        title: "港口资料总览",
        page_type: "background",
        free_text: "记录沉钟港的船期和税则。",
      })
      const entities = []
      for (let index = 1; index <= 24; index += 1) {
        entities.push(await createEntity(project.id, {
          name: `港口资料 ${index}`,
          entity_type: "location",
          status: "canonical",
          summary: `港区备忘 ${index}`,
        }))
      }

      await page.setViewportSize({ width, height: 844 })
      await openWorkbench(page, project, "world", "bible")
      await page.getByRole("group", { name: "资料库显示方式" })
        .getByRole("button", { name: "列表" })
        .click()
      await page.getByRole("search").getByRole("searchbox", { name: "搜索资料" }).fill("港口资料")
      await page.getByRole("search").getByRole("button", { name: "查找" }).click()
      await expect(page).toHaveURL(/world\/bible\?.*q=%E6%B8%AF%E5%8F%A3%E8%B5%84%E6%96%99/)
      await expect(page).toHaveURL(/layout=list/)
      await expect(page.locator(".world-library-list__row")).toHaveCount(25)

      const content = page.locator("#workspace-content")
      await content.evaluate((element) => { element.scrollTop = 260 })
      const savedTop = await content.evaluate((element) => element.scrollTop)
      expect(savedTop).toBeGreaterThan(0)
      await page.locator(".world-library-list__row", { hasText: "港口资料总览" })
        .locator("[data-action='open-world-card']")
        .click()
      await expect(page.locator("#bible-title")).toHaveValue("港口资料总览")
      await page.getByRole("button", { name: /返回资料库/ }).click()
      await expect.poll(() => content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      await expect(page.locator(".world-library-list__row", { hasText: "港口资料总览" })).toBeVisible()

      const target = entities.at(-1)
      await page.locator(".world-library-list__row", { hasText: target.name })
        .locator("[data-action='open-world-card']")
        .click()
      await expect(page.getByRole("heading", { name: target.name })).toBeVisible()
      await page.getByRole("button", { name: "添加到我的任务" }).click()
      await expect(page).toHaveURL(/writing\?home=1&panel=tasks&scope=inbox/)
      const localDate = await page.evaluate(() => {
        const now = new Date()
        return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
      })
      await page.locator("#author-task-date").fill(localDate)
      await page.getByRole("button", { name: "保存任务" }).click()
      await page.getByRole("button", { name: "写作首页" }).click()

      const taskSection = page.locator(".today-author-tasks")
      await expect(taskSection).toContainText(target.name)
      await taskSection.getByRole("checkbox", { name: `完成任务：${target.name}` }).check()
      await expect(taskSection).not.toContainText(target.name)
      await taskSection.getByRole("button", { name: "查看全部" }).click()
      await page.getByRole("button", { name: /已完成/ }).click()
      await page.getByRole("checkbox", { name: `重开任务：${target.name}` }).uncheck()
      await page.getByRole("button", { name: "写作首页" }).click()
      await expect(page.locator(".today-author-tasks")).toContainText(target.name)

      await expectNoPageOverflow(page)
      await expect(page.locator(".today-resume .btn-primary")).toHaveCount(1)
      if (width === 390) {
        const targetHeights = await page.locator(".today-author-task-row__check, .sidebar-mobile-nav button")
          .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))
        expect(targetHeights.length).toBeGreaterThan(0)
        expect(Math.min(...targetHeights)).toBeGreaterThanOrEqual(44)
      }
    })
  }
})
