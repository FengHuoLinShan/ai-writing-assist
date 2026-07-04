import { test, expect } from "@playwright/test"
import { cleanupProject, createProject, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

function suggestion(index, overrides = {}) {
  return {
    asset_type: "world_entity",
    action: "merge",
    source_asset_id: `source-${index}`,
    source_title: `左侧对象 ${index}`,
    target_asset_id: `target-${index}`,
    target_title: `右侧对象 ${index}`,
    recommended_primary_asset_id: `target-${index}`,
    recommended_primary_title: `右侧对象 ${index}`,
    confidence: 0.9,
    match_method: "llm",
    reason: `重复资产 ${index}`,
    evidence_anchors: [{ snippet: `证据 ${index}` }],
    ...overrides,
  }
}

test.describe("智能去重", () => {
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

  test("浏览器中展示推荐主体、分页并按用户选择应用建议", async ({ page }) => {
    const project = await createProject({ title: "智能去重浏览器烟测", genre: "fantasy", language: "zh" })
    testProjectId = project.id

    const suggestions = [
      suggestion(0, {
        recommended_primary_asset_id: "source-0",
        recommended_primary_title: "左侧对象 0",
      }),
      ...Array.from({ length: 5 }, (_, index) => suggestion(index + 1)),
      suggestion(6, {
        recommended_primary_asset_id: "manual-primary-6",
        recommended_primary_title: "人工主体 6",
      }),
    ]
    let applyPayload = null

    await page.route("**/api/projects/*/smart-dedup/scan", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: "smart-dedup-e2e-task" }),
      })
    })
    await page.route("**/api/tasks/smart-dedup-e2e-task*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "smart-dedup-e2e-task",
          task_type: "smart_dedup_scan",
          status: "done",
          progress: 100,
          result: {
            total_assets_scanned: 9,
            suggestion_count: suggestions.length,
            suggestions,
          },
        }),
      })
    })
    await page.route("**/api/projects/*/smart-dedup/apply", async (route) => {
      applyPayload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ applied: applyPayload?.suggestions?.length || 0 }),
      })
    })

    await openWorkbench(page, project, "world")

    await page.locator('[data-action="start-smart-dedup"]').click()
    await expect(page.locator("#toast-container")).toContainText("智能去重扫描完成", { timeout: 10000 })

    await expect(page.locator("#modal-title")).toHaveText("智能去重建议")
    await expect(page.locator("#modal-body")).toContainText("第 1 / 2 页")
    await expect(page.locator('input[name="smart-dedup-primary-0"][value="source"]')).toBeChecked()

    await page.locator('[data-smart-dedup-page="next"]').click()
    await expect(page.locator("#modal-body")).toContainText("第 2 / 2 页")
    await expect(page.locator('input[name="smart-dedup-primary-6"][value="manual"]')).toBeChecked()
    await expect(page.locator('[data-smart-dedup-manual-primary="6"]')).toHaveValue("manual-primary-6")

    await page.getByRole("button", { name: "应用选中建议" }).click()
    await expect(page.locator("#toast-container")).toContainText("已应用 7 条智能去重建议", { timeout: 10000 })
    expect(applyPayload).toMatchObject({
      confirmed: true,
      suggestions: expect.arrayContaining([
        expect.objectContaining({
          source_asset_id: "target-0",
          target_asset_id: "source-0",
        }),
        expect.objectContaining({
          source_asset_id: "source-6",
          target_asset_id: "manual-primary-6",
        }),
      ]),
    })
    expect(applyPayload.suggestions).toHaveLength(7)
  })
})
