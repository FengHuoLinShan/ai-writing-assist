import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"
import {
  createEntity,
  createProject,
  cleanupProject,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("worldView 子视图切换", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "视图切换测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("切换子视图时不应产生失败的资源请求或控制台错误", async ({ page }) => {
    const failedResponses = []
    const consoleErrors = []

    page.on("response", (response) => {
      if (response.status() >= 400) {
        failedResponses.push({ url: response.url(), status: response.status() })
      }
    })

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text())
      }
    })

    page.on("pageerror", (err) => {
      consoleErrors.push(err.message)
    })

    await openWorkbench(page, { id: testProjectId, title: "视图切换测试项目" }, "world", "objects")

    await page.locator(".world-view-options > summary").click()
    await expect(page.locator('[data-action="set-discovery-mode"][data-mode="hot"]')).toHaveAttribute("aria-pressed", "true")
    await page.locator('[data-action="set-discovery-mode"][data-mode="normal"]').click()
    await expect(page).toHaveURL(new RegExp(`world/objects\\?.*mode=normal`))
    await expect(page.locator('[data-action="set-discovery-mode"][data-mode="normal"]')).toHaveAttribute("aria-pressed", "true")
    await expect.poll(() => page.evaluate(
      (projectId) => localStorage.getItem(`novel_view_mode:${projectId}:world-objects`),
      testProjectId,
    )).toBe("normal")

    const reviewEntry = page.locator('[data-action="nav-review"]')
    await expect(reviewEntry).toBeVisible()
    await expect(reviewEntry.locator(".today-count")).toHaveCount(0)
    await reviewEntry.click()
    await expect(page).toHaveURL(new RegExp(`world/review(?:$|\\?)`))
    await expect(reviewEntry).toHaveAttribute("aria-current", "page")
    await expect(page.locator('[data-action="nav-objects"]')).not.toHaveClass(/active/)
    await expect(page.locator('[data-action="nav-review-all"]')).toHaveClass(/active/)

    await page.locator('[data-action="nav-review-objects"]').click()
    await expect(page).toHaveURL(new RegExp(`world/review\\?kind=objects`))
    await expect(page.locator('[data-action="nav-review-objects"]')).toHaveClass(/active/)

    await page.locator('[data-action="nav-review-relations"]').click()
    await expect(page).toHaveURL(new RegExp(`world/review\\?kind=relations`))
    await expect(page.locator('[data-action="nav-review-relations"]')).toHaveClass(/active/)

    await page.locator('[data-action="nav-review-aliases"]').click()
    await expect(page).toHaveURL(new RegExp(`world/review\\?kind=aliases`))
    await expect(page.locator('[data-action="nav-review-aliases"]')).toHaveClass(/active/)

    await page.locator('[data-subview="bible"]').click()
    await expect(page.locator('[data-subview="bible"]')).toHaveClass(/active/)
    await expect(page.locator(".world-bible-workspace")).toBeVisible()

    await page.locator(SEL.navItem("map")).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${testProjectId}/map`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page.locator(SEL.workspaceContent)).toContainText("AI 地图册")
    await expect(page.getByRole("button", { name: "一键生成地图册" })).toBeVisible()

    expect(failedResponses, `出现失败的资源请求: ${JSON.stringify(failedResponses)}`).toHaveLength(0)
    expect(consoleErrors, `控制台报错: ${JSON.stringify(consoleErrors)}`).toHaveLength(0)
  })

  test("别名队列加载失败可重试，详情默认收起", async ({ page }) => {
    let attempts = 0
    await page.route("**/api/world/aliases/review-groups**", async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary unavailable" }) })
        return
      }
      await route.continue()
    })

    await openWorkbench(page, { id: testProjectId, title: "视图切换测试项目" }, "world", "review-aliases")

    const alert = page.locator('[role="alert"][data-author-action="must_fix"]')
    await expect(alert).toContainText("待决定别名没有加载出来")
    await expect(alert).toContainText("原有资料没有变化，可以重新加载")
    await expect(alert.locator("details")).not.toHaveAttribute("open", "")

    await alert.getByRole("button", { name: "重新加载", exact: true }).click()
    await expect(alert).toBeHidden()
    expect(attempts).toBe(2)
  })

  test("热点模式默认使用表格，并让显式卡片链接在刷新后恢复", async ({ page }) => {
    const entity = await createEntity(testProjectId, {
      entity_type: "character",
      name: "热点主角",
      importance: 0.9,
      importance_level: "important",
      status: "canonical",
    })

    await openWorkbench(
      page,
      { id: testProjectId, title: "视图切换测试项目" },
      "world",
      "objects",
    )

    await expect(page.getByText("近期出场索引暂不可用")).toBeVisible()
    const tableRow = page.locator(`tr[data-id="${entity.id}"]`)
    await expect(tableRow).toContainText("热点主角")
    await expect(tableRow).toContainText("重要")

    await page.locator(".world-view-options > summary").click()
    const cardButton = page.locator('[data-action="set-object-view"][data-view-mode="card"]')
    await expect(page.locator('[data-action="set-object-view"][data-view-mode="table"]')).toHaveAttribute("aria-pressed", "true")
    await cardButton.click()
    const card = page.locator(`.world-object-card[data-id="${entity.id}"]`)
    await expect(card).toBeVisible()
    await expect(card).toContainText("重要")
    await expect(cardButton).toHaveAttribute("aria-pressed", "true")
    await expect(page).toHaveURL(new RegExp(`world/objects\\?.*view=card`))

    await page.reload()
    await expect(card).toBeVisible()

    await page.locator(".world-view-options > summary").click()
    await page.locator('[data-action="set-object-view"][data-view-mode="table"]').click()
    await expect(tableRow).toContainText("热点主角")
    await expect(tableRow).toContainText("重要")

    await expect(page.locator(".world-view-options")).toHaveAttribute("open", "")
    await page.locator('[data-action="close-view-options"]').click()
    await expect(page.locator(".world-view-options")).not.toHaveAttribute("open", "")
  })
})
