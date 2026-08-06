import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import {
  createEntity,
  createProject,
  cleanupProject,
  waitForBackend,
} from "./helpers/api-client.js"

function isLeafletStubIntegrityNoise(text) {
  return text.includes("Failed to find a valid digest in the 'integrity' attribute")
    && text.includes("https://unpkg.com/leaflet@1.9.4/dist/leaflet")
}

test.describe("worldView 子视图切换", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())
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
        const text = msg.text()
        if (!isLeafletStubIntegrityNoise(text)) {
          consoleErrors.push(text)
        }
      }
    })

    page.on("pageerror", (err) => {
      consoleErrors.push(err.message)
    })

    await openWorkbench(page, { id: testProjectId, title: "视图切换测试项目" }, "world", "objects")

    await page.locator(".world-view-options > summary").click()
    await expect(page.locator('[data-action="set-discovery-mode"][data-mode="hot"]')).toHaveClass(/btn-primary/)
    await page.locator('[data-action="set-discovery-mode"][data-mode="normal"]').click()
    await expect(page).toHaveURL(new RegExp(`world/objects\\?.*mode=normal`))
    await expect(page.locator('[data-action="set-discovery-mode"][data-mode="normal"]')).toHaveClass(/btn-primary/)
    await expect.poll(() => page.evaluate(
      (projectId) => localStorage.getItem(`novel_view_mode:${projectId}:world-objects`),
      testProjectId,
    )).toBe("normal")

    await page.locator(".world-attention-menu > summary").click()
    await page.locator(".world-attention-menu__panel button").first().click()
    await expect(page.locator('[data-action="nav-review-objects"]')).toHaveClass(/active/)

    await page.locator('[data-action="nav-review-relations"]').click()
    await expect(page.locator('[data-action="nav-review-relations"]')).toHaveClass(/active/)

    await page.locator('[data-action="nav-review-aliases"]').click()
    await expect(page.locator('[data-action="nav-review-aliases"]')).toHaveClass(/active/)

    await page.locator('[data-subview="bible"]').click()
    await expect(page.locator('[data-subview="bible"]')).toHaveClass(/active/)
    await expect(page.locator(".world-bible-workspace")).toBeVisible()

    await page.locator(SEL.navItem("map")).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${testProjectId}/map`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page.locator(SEL.workspaceContent)).toContainText("空间总览")
    await page.locator(".map-overview-more > summary").click()
    await expect(page.getByRole("button", { name: "创建世界地图" })).toBeVisible()

    expect(failedResponses, `出现失败的资源请求: ${JSON.stringify(failedResponses)}`).toHaveLength(0)
    expect(consoleErrors, `控制台报错: ${JSON.stringify(consoleErrors)}`).toHaveLength(0)
  })

  test("热点模式真实展示降级状态和重要标签并支持卡片视图", async ({ page }) => {
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
    const card = page.locator(`.world-object-card[data-id="${entity.id}"]`)
    await expect(card).toBeVisible()
    await expect(card).toContainText("重要")

    await page.locator(".world-view-options > summary").click()
    await page.locator('[data-action="set-object-view"][data-view-mode="table"]').click()
    const tableRow = page.locator(`tr[data-id="${entity.id}"]`)
    await expect(tableRow).toContainText("热点主角")
    await expect(tableRow).toContainText("重要")

    await page.locator(".world-view-options > summary").click()
    await page.locator('[data-action="set-object-view"][data-view-mode="card"]').click()
    await expect(card).toBeVisible()
  })
})
