import { test, expect } from "@playwright/test"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

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

    await page.locator('[data-subview="candidates"]').click()
    await expect(page.locator('[data-subview="candidates"]')).toHaveClass(/active/)

    await page.locator('[data-subview="relations"]').click()
    await expect(page.locator('[data-subview="relations"]')).toHaveClass(/active/)

    await page.locator('[data-subview="aliases"]').click()
    await expect(page.locator('[data-subview="aliases"]')).toHaveClass(/active/)

    await page.locator('[data-subview="bible"]').click()
    await expect(page.locator('[data-subview="bible"]')).toHaveClass(/active/)
    await expect(page.locator(".world-bible-workspace")).toBeVisible()

    await page.locator('[data-subview="map"]').click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${testProjectId}/map`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("地图")
    await expect(page.locator(SEL.workspaceContent)).toContainText("空间总览")
    await expect(page.getByRole("button", { name: "创建世界地图" })).toBeVisible()

    expect(failedResponses, `出现失败的资源请求: ${JSON.stringify(failedResponses)}`).toHaveLength(0)
    expect(consoleErrors, `控制台报错: ${JSON.stringify(consoleErrors)}`).toHaveLength(0)
  })
})
