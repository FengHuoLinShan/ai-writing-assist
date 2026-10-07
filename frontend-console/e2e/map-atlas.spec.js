import { test, expect } from "./fixtures.js"
import { cleanupProject, createProject, waitForBackend } from "./helpers/api-client.js"

import { openWorkbench, openWorkspaceTools } from "./helpers/workbench.js"

import { atlasPage, mockAtlas } from "./helpers/atlas-fixture.js"

test.describe("AI 地图册", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async () => {
    project = await createProject({ title: "地图册 E2E 项目", genre: "fantasy", language: "zh" })
  })

  test.afterEach(async () => {
    if (project?.id) await cleanupProject(project.id)
    project = null
  })

  test("结构引导生图先审查 Context 并提交同一 confirmation", async ({ page }) => {
    const requests = []
    const nodeId = "20000000-0000-0000-0000-000000000001"
    const revisionId = "30000000-0000-0000-0000-000000000001"
    const document = { schema_version: 1, layout_version: 1, features: [], constraints: [], images: [], annotation_bindings: [] }
    const run = {
      id: "run-context",
      novel_id: project.id,
      task_id: "task-context",
      run_kind: "initial",
      status: "planning",
      style_note: null,
      include_working_drafts: false,
      include_interiors: false,
      review_image_prompts: false,
      layout: "landscape",
      quality: "standard",
      page_limit: 12,
      planned_page_count: 0,
      completed_page_count: 0,
      stop_requested: false,
      created_at: new Date().toISOString(),
    }
    await page.route("**/api/world/map-atlas/**", async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (request.method() === "GET" && path.endsWith("/capabilities")) return route.fulfill({ json: { upload: { available: true }, image_generation: { available: true } } })
      if (request.method() === "POST" && path.endsWith("/runs")) {
        requests.push(request.postDataJSON())
        return route.fulfill({ status: 202, json: run })
      }
      if (request.method() === "GET" && path.endsWith("/runs/latest")) {
        return route.fulfill({ json: null })
      }
      if (request.method() === "GET" && path.endsWith("/atlas")) {
        return route.fulfill({ json: { mode: "atlas", total_pages: 0, nodes: [{ id: nodeId, title: "区域", level: "region", current_revision_id: revisionId, pages: [], children: [] }] } })
      }
      if (request.method() === "GET" && path.endsWith("/map")) {
        return route.fulfill({ json: { node_id: nodeId, revision: { id: revisionId, document, problems: [], status: "saved" }, candidates: [], image_layers: [] } })
      }
      if (request.method() === "GET" && path.endsWith("/pages/history")) {
        return route.fulfill({ json: [] })
      }
      if (request.method() === "GET" && path.endsWith("/runs/run-context")) {
        return route.fulfill({ json: run })
      }
      return route.fulfill({ status: 404, json: { detail: "unexpected atlas request" } })
    })

    await page.setViewportSize({ width: 390, height: 844 })
    await openWorkbench(page, project, "map")
    await openWorkspaceTools(page)
    await page.locator('[data-action="map-tool-images"]').click()
    await page.getByRole("button", { name: "添加地图画面" }).click()
    await expect(page.locator("#modal-overlay")).toContainText("AI 参考资料")
    const start = page.getByRole("button", { name: "按这份资料开始" })
    await expect(start).toBeEnabled()
    await start.click()

    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0].context_confirmation_id).toEqual(expect.any(String))
    expect(requests[0].target_node_id).toBe(nodeId)
    expect(requests[0].source_map_revision_id).toBe(revisionId)

  })

  test("候选、旧图、历史和采用保持独立", async ({ page }) => {
    const candidate = atlasPage("candidate-page")
    const oldPage = atlasPage("old-page", { review_status: "adopted" })
    const rejected = atlasPage("rejected-page", { run_id: "run-0", title: "旧候选", review_status: "rejected" })
    const removed = atlasPage("removed-page", { run_id: "run-0", title: "旧地图", review_status: "deprecated" })
    const state = await mockAtlas(page, { candidate, adopted: [oldPage], history: [rejected, removed] })

    await openWorkbench(page, project, "map")
    await expect(page.locator(".atlas-header h1")).toHaveText("地图")
    await expect(page.getByText("地图册已有图片", { exact: true })).toBeVisible()
    await expect(page.getByText("新候选", { exact: true })).toBeVisible()

    await page.locator(".atlas-history summary").click()
    await expect(page.locator(".atlas-history")).toContainText("已决定不加入")
    await expect(page.locator(".atlas-history")).toContainText("已从地图册移出")
    await expect(page.locator(".atlas-history button")).toHaveCount(1)

    await page.getByRole("button", { name: "加入地图册", exact: true }).click()
    await expect(page.locator("#toast-container")).toContainText("已增加，原有图片未改变")
    expect(state.reviewRequests()).toEqual([{ expected_updated_at: candidate.updated_at, confirm_conflicts: false }])
    await expect(page.getByText("地图册已有图片", { exact: true })).toBeVisible()

    await page.locator(".atlas-edit summary").click()
    await expect(page.locator(".atlas-references")).toContainText("沉海湾")
    await expect(page.locator(".atlas-references")).not.toContainText("old-page")
  })

  test("窄屏图片可重试并打开热点，桌面可调整缩放", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const target = atlasPage("north-gate-page", { node_id: "node-north-gate", title: "北门城区" })
    const candidate = atlasPage("square-page", {
      width: 1024,
      height: 1024,
      annotations: [{ id: "hotspot-1", label: "北门", position_x: 0.25, position_y: 0.75, target_node_id: "node-north-gate" }],
    })
    const reviewTree = {
      mode: "review",
      total_pages: 2,
      nodes: [
        { id: "node-harbor", title: "沉海湾", level: "city", pages: [candidate], children: [] },
        { id: "node-north-gate", title: "北门城区", level: "district", pages: [target], children: [] },
      ],
    }
    const state = await mockAtlas(page, { candidate, failFirstImage: true, reviewTree })

    await openWorkbench(page, project, "map")
    await expect(page.getByText("图片读取失败", { exact: true })).toBeVisible()
    await page.locator(".atlas-image-state").getByRole("button", { name: "重试" }).click()
    await expect(page.locator(".atlas-image-canvas img")).toBeVisible()
    expect(state.imageAttempts()).toBe(2)

    await expect(page.getByRole("button", { name: "北门", exact: true })).toBeVisible()
    await page.getByRole("button", { name: "北门", exact: true }).click()
    await expect(page.locator(".atlas-page h2")).toHaveText("北门城区")

    await page.setViewportSize({ width: 1280, height: 900 })
    await page.getByRole("slider", { name: "缩放" }).press("End")
    await expect(page.locator(".atlas-zoom input")).toHaveValue("150")

  })

  test("停止中的写操作会锁定，刷新后可从下一页继续", async ({ page }) => {
    const candidate = atlasPage("completed-page")
    const state = await mockAtlas(page, {
      candidate,
      holdStop: true,
      runOverrides: { status: "generating", planned_page_count: 2, completed_page_count: 1 },
    })

    await openWorkbench(page, project, "map")
    await expect(page.locator(".atlas-page h2")).toHaveText("沉钟港")

    const stopResponse = page.waitForResponse(response => response.url().endsWith("/runs/run-1/stop"))
    await page.getByRole("button", { name: "生成完当前页后停止" }).click()
    await expect(page.locator('[data-action="map-tool-new-map"]')).toHaveAttribute("aria-disabled", "true")
    await expect(page.getByRole("button", { name: "加入地图册", exact: true })).toBeDisabled()

    state.releaseStop()
    await stopResponse
    await page.reload()
    await expect(page.locator(".atlas-page h2")).toHaveText("沉钟港")
    await expect(page.getByRole("button", { name: "继续生成" })).toBeEnabled()

    const resumeRequest = page.waitForRequest(request => request.url().endsWith("/runs/run-1/resume"))
    await page.getByRole("button", { name: "继续生成" }).click()
    expect((await resumeRequest).postDataJSON()).toEqual({ confirm_possible_duplicate_charge: false })
    await expect(page.getByText("正在逐页生成", { exact: true })).toBeVisible()
    expect(state.resumeRequests()).toEqual([{ confirm_possible_duplicate_charge: false }])
  })

  test("可能重复费用的页面需确认后单独重试且旧图不变", async ({ page }) => {
    const candidate = atlasPage("retry-page", {
      generation_status: "retry_requires_confirmation",
      image_url: null,
      error_message: "上次请求结果未知",
    })
    const oldPage = atlasPage("old-page", { review_status: "adopted" })
    const state = await mockAtlas(page, {
      candidate,
      adopted: [oldPage],
      runOverrides: {
        status: "partial",
        error_code: "retry_requires_confirmation",
        planned_page_count: 1,
        completed_page_count: 0,
      },
    })

    await openWorkbench(page, project, "map")
    await expect(page.getByText("上次图片请求可能已产生费用", { exact: false })).toBeVisible()
    await expect(page.getByText("地图册已有图片", { exact: true })).toBeVisible()

    const dialogPromise = page.waitForEvent("dialog")
    const retryRequest = page.waitForRequest(request => request.url().endsWith("/pages/retry-page/retry"))
    const clickPromise = page.getByRole("button", { name: "确认费用并重试本页" }).click()
    const dialog = await dialogPromise
    expect(dialog.message()).toContain("可能已经产生费用")
    await dialog.accept()
    await clickPromise

    expect((await retryRequest).postDataJSON()).toEqual({ confirm_possible_duplicate_charge: true })
    await expect(page.getByText("正在逐页生成", { exact: true })).toBeVisible()
    await expect(page.getByText("地图册已有图片", { exact: true })).toBeVisible()
    expect(state.retryRequests()).toEqual([{ confirm_possible_duplicate_charge: true }])
    expect(state.savedPageIds()).toEqual(["old-page"])
  })
})
