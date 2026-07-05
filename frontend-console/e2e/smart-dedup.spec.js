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
    await expect(page.locator("#view-actions")).toContainText("智能去重")
  })

  test("应用一条建议后可以再次扫描并保持页面可交互", async ({ page }) => {
    const project = await createProject({ title: "智能去重应用后重扫", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    let scanCount = 0
    let applyPayload = null

    await page.route("**/api/projects/*/smart-dedup/scan", async (route) => {
      scanCount += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: `smart-dedup-apply-rescan-${scanCount}` }),
      })
    })
    await page.route("**/api/tasks/smart-dedup-apply-rescan-1*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "smart-dedup-apply-rescan-1",
          task_type: "smart_dedup_scan",
          status: "done",
          progress: 100,
          result: {
            total_assets_scanned: 20,
            suggestion_count: 2,
            suggestions: [
              suggestion(0, {
                source_asset_id: "xu-yun-duplicate",
                source_title: "许筠",
                target_asset_id: "xu-yun-primary",
                target_title: "许筠",
                confidence: 1,
                match_method: "exact_name",
              }),
              suggestion(1, {
                source_asset_id: "shen-lan",
                source_title: "沈澜",
                target_asset_id: "mirror-restorer",
                target_title: "北港镜修师",
                recommended_primary_asset_id: "mirror-restorer",
                recommended_primary_title: "北港镜修师",
                confidence: 0.99,
                match_method: "alias_name_match",
              }),
            ],
          },
        }),
      })
    })
    await page.route("**/api/tasks/smart-dedup-apply-rescan-2*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "smart-dedup-apply-rescan-2",
          task_type: "smart_dedup_scan",
          status: "done",
          progress: 100,
          result: {
            total_assets_scanned: 19,
            suggestion_count: 1,
            suggestions: [
              suggestion(1, {
                source_asset_id: "shen-lan",
                source_title: "沈澜",
                target_asset_id: "mirror-restorer",
                target_title: "北港镜修师",
                recommended_primary_asset_id: "mirror-restorer",
                recommended_primary_title: "北港镜修师",
                confidence: 0.99,
                match_method: "alias_name_match",
              }),
            ],
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
    await expect(page.locator("#modal-title")).toHaveText("智能去重建议", { timeout: 10000 })
    await expect(page.locator('[data-smart-dedup-index="0"]')).toBeChecked()
    await expect(page.locator('[data-smart-dedup-index="1"]')).not.toBeChecked()

    await page.getByRole("button", { name: "应用选中建议" }).click()
    await expect(page.locator("#toast-container")).toContainText("已应用 1 条智能去重建议", { timeout: 10000 })
    expect(applyPayload.suggestions).toHaveLength(1)
    await expect(page.locator("#view-actions")).toContainText("智能去重")

    await page.locator('[data-action="start-smart-dedup"]').click()
    await expect(page.locator("#modal-title")).toHaveText("智能去重建议", { timeout: 10000 })
    await expect(page.locator("#modal-body")).toContainText("沈澜")
    await expect(page.locator("#modal-body")).toContainText("高风险别名命中")
    await expect(page.locator('[data-smart-dedup-index="0"]')).not.toBeChecked()
    await expect(page.locator("#view-actions")).toContainText("查看去重建议")
    expect(await page.locator("body").innerText({ timeout: 5000 })).toContain("智能去重建议")
    expect(scanCount).toBe(2)
  })

  test("空结果后可以从前端重新扫描并展示新建议", async ({ page }) => {
    const project = await createProject({ title: "智能去重空结果重扫", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    let scanCount = 0

    await page.route("**/api/projects/*/smart-dedup/scan", async (route) => {
      scanCount += 1
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ task_id: `smart-dedup-rescan-${scanCount}` }),
      })
    })
    await page.route("**/api/tasks/smart-dedup-rescan-1*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "smart-dedup-rescan-1",
          task_type: "smart_dedup_scan",
          status: "done",
          progress: 100,
          result: {
            total_assets_scanned: 2,
            suggestion_count: 0,
            suggestions: [],
          },
        }),
      })
    })
    await page.route("**/api/tasks/smart-dedup-rescan-2*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: "smart-dedup-rescan-2",
          task_type: "smart_dedup_scan",
          status: "done",
          progress: 100,
          result: {
            total_assets_scanned: 3,
            suggestion_count: 1,
            suggestions: [
              suggestion(0, {
                source_asset_id: "beigang-mirror-restorer",
                source_title: "北港镜修师",
                target_asset_id: "shen-lan",
                target_title: "沈澜",
                action: "alias_only",
                match_method: "alias_name_match",
              }),
            ],
          },
        }),
      })
    })

    await openWorkbench(page, project, "world")

    await page.locator('[data-action="start-smart-dedup"]').click()
    await expect(page.locator("#modal-body")).toContainText("没有发现可处理的重复资产", { timeout: 10000 })
    await expect(page.locator("#view-actions")).toContainText("智能去重")

    await page.getByRole("button", { name: "重新扫描" }).click()
    await expect(page.locator("#modal-title")).toHaveText("智能去重建议", { timeout: 10000 })
    await expect(page.locator("#modal-body")).toContainText("北港镜修师")
    await expect(page.locator("#modal-body")).toContainText("沈澜")
    await expect(page.locator("#modal-body")).toContainText("高风险别名命中")
    await expect(page.locator('[data-smart-dedup-index="0"]')).not.toBeChecked()
    await expect(page.getByRole("button", { name: "应用选中建议" })).toBeEnabled()
    expect(scanCount).toBe(2)
  })
})
