import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { installLeafletStub } from "./helpers/leaflet-stub.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"
import {
  cleanupProject,
  createMap,
  createProject,
  getMapPaths,
  waitForBackend,
} from "./helpers/api-client.js"

const MOBILE_VIEWPORT = { width: 390, height: 844 }
const LEAFLET_ORIGIN = 60

function hexPosition(q, r, size = 30) {
  return {
    x: LEAFLET_ORIGIN + size * 1.5 * q,
    y: LEAFLET_ORIGIN + size * Math.sqrt(3) * (r + q / 2),
  }
}

async function openMapWorkspace(page, project, map) {
  await openWorkbench(page, project, "map")
  await page.goto(`/#workbench/${project.id}/map?map_id=${map.id}&mode=map`)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("地图", { timeout: 10000 })
  await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 10000 })
}

async function expectMobileWorkspaceFits(page) {
  expect(await page.evaluate(() => ({ width: innerWidth, height: innerHeight })))
    .toEqual(MOBILE_VIEWPORT)
  await expectNoPageOverflow(page)
}

async function setRangeValue(locator, value) {
  await locator.evaluate((input, nextValue) => {
    input.value = nextValue
    input.dispatchEvent(new Event("change", { bubbles: true }))
  }, String(value))
}

async function clickCentered(locator) {
  await locator.evaluate((element) => element.scrollIntoView({ block: "center" }))
  await expectWithinViewport(locator)
  await locator.click()
}

test.use({ viewport: MOBILE_VIEWPORT })

test.describe("390px 地图线路编辑", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await installLeafletStub(page.context())
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("creates, refines, persists, archives, and restores a path without page overflow", async ({ page }) => {
    const project = await createProject({
      title: "移动端线路 E2E",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id
    const map = await createMap(testProjectId, {
      name: "移动端道路图",
      map_type: "world",
      grid_width: 8,
      grid_height: 8,
      template: "blank",
    })

    await openMapWorkspace(page, project, map)
    await expectMobileWorkspaceFits(page)

    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "线路", exact: true }).click()
    await expectMobileWorkspaceFits(page)

    await page.getByRole("button", { name: "+ 线路图层" }).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建线路图层")
    await page.locator("#map-path-layer-name").fill("移动端王国公路")
    await page.locator("#map-path-layer-category").selectOption("transport")
    await expectNoPageOverflow(page)
    await page.locator(SEL.modalFooter).getByRole("button", { name: "创建" }).click()
    await expect(page.locator("#map-path-layer")).not.toHaveValue("")

    const canvas = page.locator(SEL.mapCanvas)
    await canvas.scrollIntoViewIfNeeded()
    await expectWithinViewport(canvas)
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()
    const start = hexPosition(1, 1)
    const bend = hexPosition(2, 3)
    const end = hexPosition(4, 2)
    await page.mouse.move(box.x + start.x, box.y + start.y)
    await page.mouse.down()
    await page.mouse.move(box.x + bend.x, box.y + bend.y, { steps: 8 })
    await page.mouse.move(box.x + end.x, box.y + end.y, { steps: 8 })
    await page.mouse.up()

    await expect(page.locator(".map-path-list-row.active")).toContainText("主干道")
    await page.getByRole("button", { name: "节点精修", exact: true }).click()
    await page.waitForTimeout(300)
    await canvas.click({ position: start })
    await expect(page.locator(".map-path-node-editor")).toContainText(/节点 1 \/ \d+/)

    await setRangeValue(page.locator("#map-path-node-width"), 1.75)
    await setRangeValue(page.locator("#map-path-node-tension"), 0.25)
    await page.locator("#map-path-node-segment").selectOption("dirt_trail")
    await expectMobileWorkspaceFits(page)

    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已原子应用 2 个编辑命令", {
      timeout: 10000,
    })

    const activeAfterSave = await getMapPaths(testProjectId, map.id, "active")
    expect(activeAfterSave.layers).toHaveLength(1)
    expect(activeAfterSave.paths).toHaveLength(1)
    expect(activeAfterSave.paths[0].nodes.length).toBeGreaterThanOrEqual(2)
    expect(activeAfterSave.paths[0].nodes).toEqual(expect.arrayContaining([
      expect.objectContaining({
        width_scale: 1.75,
        tension: 0.25,
        segment_type: "dirt_trail",
      }),
    ]))

    const pathArchiveButton = page.locator(
      '.map-path-selection-summary [data-action="map-path-archive"]',
    )
    await expect(pathArchiveButton).toHaveText("归档")
    await clickCentered(pathArchiveButton)
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await expectNoPageOverflow(page)
    await page.locator(SEL.modalFooter).getByRole("button", { name: "归档线路" }).click()
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect.poll(async () => (await getMapPaths(testProjectId, map.id, "active")).paths.length)
      .toBe(0)
    expect((await getMapPaths(testProjectId, map.id, "archived")).paths).toHaveLength(1)
    await expect(page.locator(".map-path-list-row.active")).toContainText("已归档")

    await expect(pathArchiveButton).toHaveText("恢复")
    await clickCentered(pathArchiveButton)
    await page.getByRole("button", { name: "应用当前图层", exact: true }).click()
    await expect.poll(async () => (await getMapPaths(testProjectId, map.id, "active")).paths.length)
      .toBe(1)
    expect((await getMapPaths(testProjectId, map.id, "archived")).paths).toHaveLength(0)

    await openMapWorkspace(page, project, map)
    await page.getByRole("button", { name: "编辑" }).click()
    await page.getByRole("button", { name: "线路", exact: true }).click()
    const restoredPath = page.locator(".map-path-list-row").filter({ hasText: "主干道" }).first()
    await expect(restoredPath).toBeVisible()
    await expect(restoredPath).not.toContainText("已归档")
    await expectMobileWorkspaceFits(page)
  })
})
