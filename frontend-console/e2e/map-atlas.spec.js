import { test, expect } from "./fixtures.js"
import { cleanupProject, createProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { openWorkbench } from "./helpers/workbench.js"

const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2nWQAAAAASUVORK5CYII=",
  "base64",
)

function atlasPage(id, overrides = {}) {
  return {
    id,
    node_id: "node-harbor",
    run_id: "run-1",
    title: "沉钟港",
    generation_status: "review_ready",
    review_status: "candidate",
    updated_at: "2026-08-12T00:00:00Z",
    created_at: "2026-08-12T00:00:00Z",
    evidence: { supported: ["正式设定中的港口"], visual_fill: ["码头间距"], conflicts: [] },
    source_manifest: [],
    annotations: [],
    image_url: `/api/world/map-atlas/project/pages/${id}/image`,
    width: 2048,
    height: 1152,
    ...overrides,
  }
}

function atlasTree(pages, mode) {
  return {
    mode,
    total_pages: pages.length,
    nodes: pages.length ? [{
      id: "node-harbor",
      title: "沉海湾",
      level: "city",
      pages,
      children: [],
    }] : [],
  }
}

async function mockAtlas(page, {
  candidate,
  adopted = [],
  history = [],
  failFirstImage = false,
  holdStop = false,
  reviewTree = null,
  runOverrides = {},
}) {
  const run = {
    id: "run-1",
    status: "review_ready",
    stop_requested: false,
    planned_page_count: 1,
    completed_page_count: 1,
    ...runOverrides,
  }
  let imageAttempts = 0
  let reviewRequests = []
  let resumeRequests = []
  let retryRequests = []
  let savedPages = [...adopted]
  let releaseStop = () => {}
  const stopGate = holdStop ? new Promise(resolve => { releaseStop = resolve }) : Promise.resolve()

  await page.route("**/api/world/map-atlas/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (method === "GET" && path.endsWith("/atlas")) {
      return route.fulfill({ json: atlasTree(savedPages, "atlas") })
    }
    if (method === "GET" && path.endsWith("/pages/history")) {
      return route.fulfill({ json: history })
    }
    if (method === "GET" && path.endsWith("/runs/latest")) {
      return route.fulfill({ json: run })
    }
    if (method === "GET" && path.endsWith("/runs/run-1/results")) {
      return route.fulfill({ json: { ...(reviewTree || atlasTree(candidate ? [candidate] : [], "review")), run } })
    }
    if (method === "GET" && path.endsWith("/runs/run-1")) {
      return route.fulfill({ json: run })
    }
    if (method === "GET" && path.endsWith("/image")) {
      imageAttempts += 1
      if (failFirstImage && imageAttempts === 1) {
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "temporary image read failure" }) })
      }
      return route.fulfill({ status: 200, contentType: "image/png", body: PNG })
    }
    if (method === "POST" && path.endsWith("/adopt")) {
      reviewRequests.push(request.postDataJSON())
      candidate.review_status = "adopted"
      if (!savedPages.some(item => item.id === candidate.id)) savedPages = [...savedPages, candidate]
      return route.fulfill({ json: candidate })
    }
    if (method === "POST" && path.endsWith("/runs/run-1/stop")) {
      await stopGate
      Object.assign(run, { status: "paused", stop_requested: true })
      return route.fulfill({ json: run })
    }
    if (method === "POST" && path.endsWith("/runs/run-1/resume")) {
      resumeRequests.push(request.postDataJSON())
      Object.assign(run, { status: "generating", stop_requested: false })
      return route.fulfill({ json: run })
    }
    if (method === "POST" && path.endsWith(`/${candidate?.id}/retry`)) {
      retryRequests.push(request.postDataJSON())
      Object.assign(candidate, { generation_status: "prepared", error_message: null })
      Object.assign(run, { status: "generating", stop_requested: false, error_code: null })
      return route.fulfill({ json: candidate })
    }
    return route.fulfill({ status: 404, json: { detail: "unexpected atlas test request" } })
  })

  return {
    imageAttempts: () => imageAttempts,
    reviewRequests: () => reviewRequests,
    releaseStop,
    resumeRequests: () => resumeRequests,
    retryRequests: () => retryRequests,
    savedPageIds: () => savedPages.map(item => item.id),
  }
}

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

  test("候选、旧图、历史和采用保持独立", async ({ page }) => {
    const candidate = atlasPage("candidate-page")
    const oldPage = atlasPage("old-page", { review_status: "adopted" })
    const rejected = atlasPage("rejected-page", { run_id: "run-0", title: "旧候选", review_status: "rejected" })
    const removed = atlasPage("removed-page", { run_id: "run-0", title: "旧地图", review_status: "deprecated" })
    const state = await mockAtlas(page, { candidate, adopted: [oldPage], history: [rejected, removed] })

    await openWorkbench(page, project, "map")
    await expect(page.getByRole("heading", { name: "AI 地图册" })).toBeVisible()
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

  test("窄屏方图可重试读取、缩放和打开热点", async ({ page }) => {
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

    const square = await page.locator(".atlas-image-canvas").boundingBox()
    expect(Math.abs(square.width - square.height)).toBeLessThanOrEqual(2)
    await expect(page.getByRole("button", { name: "北门", exact: true })).toBeVisible()
    expect(await page.getByRole("button", { name: "北门", exact: true }).evaluate(element => getComputedStyle(element).pointerEvents)).not.toBe("none")
    await page.getByRole("button", { name: "北门", exact: true }).click()
    await expect(page.locator(".atlas-page h2")).toHaveText("北门城区")

    await page.locator(".atlas-zoom input").fill("150")
    await expect.poll(() => page.locator(".atlas-image-viewport").evaluate(element => element.scrollWidth > element.clientWidth)).toBe(true)
    await expectNoPageOverflow(page)
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
    await expect(page.locator(".atlas-primary-actions .btn-primary")).toBeDisabled()
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
