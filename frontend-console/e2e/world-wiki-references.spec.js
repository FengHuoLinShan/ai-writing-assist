import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  createWorldBiblePage,
  waitForBackend,
} from "./helpers/api-client.js"

async function openPageInReader(page, projectId, pageId) {
  await page.evaluate(({ projectId: pid, pageId: ppid }) => {
    window.location.hash = `#workbench/${pid}/world/bible?page_id=${ppid}`
  }, { projectId, pageId })
  await expect(page.locator(".world-page-reader")).toBeVisible({ timeout: 10000 })
}

test.describe("Wiki 引用按名称解析", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async () => {
    const project = await createProject({ title: "Wiki 引用项目", language: "zh" })
    testProjectId = project.id
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("重名引用要求选择，唯一引用直接打开，未找到给出提示", async ({ page }) => {
    const projectId = testProjectId
    // 同名资料：一个资料页 + 一个同名实体，引用必须让作者选择。
    await createWorldBiblePage(projectId, {
      title: "潮门港",
      page_type: "background",
      free_text: "这里是资料页版本的潮门港。",
    })
    await createWorldBiblePage(projectId, {
      title: "潮门港",
      page_type: "species",
      free_text: "这里是另一版潮门港，讲港区物种。",
    })
    await createWorldBiblePage(projectId, {
      title: "北境银币",
      page_type: "background",
      free_text: "银币在冬季升值。",
    })
    const source = await createWorldBiblePage(projectId, {
      title: "北境贸易志",
      page_type: "background",
      free_text: "商队途经 [[潮门港]]，货款以 [[北境银币]] 结算，传说还有 [[无名之地]]。",
    })

    await openWorkbench(page, { id: projectId, title: "Wiki 引用项目" }, "world", "bible")
    await openPageInReader(page, projectId, source.id)

    const chips = page.locator("[data-action='open-wiki-ref']")
    await expect(chips).toHaveCount(3)
    await expect(chips.first()).toHaveText("潮门港")

    // 重名：弹出选择，不自动打开第一条。
    await chips.first().click()
    await expect(page.locator(SEL.modalTitle)).toContainText("有多条同名资料")
    const choices = page.locator("[data-action='choose-wiki-ref']")
    await expect(choices).toHaveCount(2)
    await expect(page.locator("#modal-body")).toContainText("资料页")
    await page.locator("[data-action='choose-wiki-ref']", { hasText: "讲港区物种" }).click()
    await expect(page.locator(".world-page-reader")).toContainText("这里是另一版潮门港，讲港区物种")
    await expect(page.locator(SEL.modalTitle)).toBeHidden()

    // 唯一名称：不弹选择，直接打开。
    await openPageInReader(page, projectId, source.id)
    await page.locator("[data-action='open-wiki-ref']", { hasText: "北境银币" }).click()
    await expect(page.locator(".world-page-reader h2")).toHaveText("北境银币")
    await expect(page.locator(SEL.modalTitle)).toBeHidden()

    // 未找到：提示，不导航。
    await openPageInReader(page, projectId, source.id)
    await page.locator("[data-action='open-wiki-ref']", { hasText: "无名之地" }).click()
    await expect(page.locator(SEL.toastItems).last()).toContainText("没有找到")
    await expect(page.locator(".world-page-reader h2")).toHaveText("北境贸易志")
  })

  test("引用中的 HTML 与指令只作为文本展示", async ({ page }) => {
    const projectId = testProjectId
    const source = await createWorldBiblePage(projectId, {
      title: "危险引用页",
      page_type: "background",
      free_text: "引用 [[<img src=x onerror=alert(1)>]] 与 <script>alert(2)</script>。",
    })
    await createWorldBiblePage(projectId, {
      title: "<img src=x onerror=alert(1)>",
      page_type: "background",
      free_text: "同名注入页甲。",
    })
    await createWorldBiblePage(projectId, {
      title: "<img src=x onerror=alert(1)>",
      page_type: "background",
      free_text: "同名注入页乙。",
    })

    await openWorkbench(page, { id: projectId, title: "Wiki 引用项目" }, "world", "bible")
    await openPageInReader(page, projectId, source.id)

    await expect(page.locator(".world-page-reader img")).toHaveCount(0)
    await expect(page.locator(".world-page-reader script")).toHaveCount(0)
    await expect(page.locator(".world-page-reader")).toContainText("<script>alert(2)</script>")
    const chip = page.locator("[data-action='open-wiki-ref']")
    await expect(chip).toHaveCount(1)
    await chip.click()
    // 名称即纯文本，选择列表同样不执行任何标记。
    await expect(page.locator(SEL.modalTitle)).toContainText("有多条同名资料")
    await expect(page.locator("#modal-body img")).toHaveCount(0)
  })
})
