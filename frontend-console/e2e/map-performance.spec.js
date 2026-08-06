import os from "node:os"
import { execFile } from "node:child_process"
import { writeFile } from "node:fs/promises"
import { promisify } from "node:util"
import { test, expect } from "./fixtures.js"
import { cleanupProject } from "./helpers/api-client.js"
import {
  createMapPerformanceFixture,
  databaseFingerprint,
  validateMapPerformanceFixture,
} from "./helpers/map-performance-fixture.js"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"

const execFileAsync = promisify(execFile)

async function gitWorkingTreeIdentity() {
  const [{ stdout: commit }, { stdout: status }] = await Promise.all([
    execFileAsync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }),
    execFileAsync("git", ["status", "--porcelain", "--untracked-files=normal"], {
      encoding: "utf8",
    }),
  ])
  const normalizedCommit = commit.trim()
  if (!/^[0-9a-f]{40}$/i.test(normalizedCommit)) {
    throw new Error("map performance profile could not resolve the repository commit")
  }
  return {
    commit: normalizedCommit,
    dirty: status.trim().length > 0,
  }
}

function nearestRank(values, percentile) {
  const sorted = [...values].sort((left, right) => left - right)
  return sorted[Math.max(0, Math.ceil(sorted.length * percentile) - 1)]
}

async function leafletViewportState(page) {
  return page.evaluate(() => {
    const mapPane = document.querySelector("#map-leaflet .leaflet-map-pane")
    const zoomProxy = document.querySelector("#map-leaflet .leaflet-proxy")
    return {
      mapPaneTransform: mapPane?.style.transform || "",
      zoomProxyTransform: zoomProxy?.style.transform || "",
    }
  })
}

const PERFORMANCE_PROFILES = Object.freeze([
  { profileName: "standard", budgetMs: 2000 },
  { profileName: "stress", budgetMs: 3000 },
])

test.describe("地图真实性能采样", () => {
  let projectId = null

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.__mapPerformanceEvents = { interactive: [], samples: [] }
      window.addEventListener("map:interactive", (event) => {
        window.__mapPerformanceEvents.interactive.push(event.detail)
      })
      window.addEventListener("map:performance-sample", (event) => {
        window.__mapPerformanceEvents.samples.push(event.detail)
      })
    })
  })

  test.afterEach(async () => {
    if (projectId) {
      try { await cleanupProject(projectId) } catch {}
      projectId = null
    }
  })

  for (const { profileName, budgetMs } of PERFORMANCE_PROFILES) {
    test(`collects and enforces the ${profileName} reference profile`, async ({ page, browser }, testInfo) => {
      test.setTimeout(180000)
      expect(testInfo.retry).toBe(0)
      const fixture = await createMapPerformanceFixture(profileName)
      projectId = fixture.project.id

    await openWorkbench(page, fixture.project, "map")
    await page.goto(`/#workbench/${fixture.project.id}/map?map_id=${fixture.map.id}&mode=live`)
    await expect(page.locator(SEL.mapCanvas)).toBeVisible({ timeout: 30000 })
    await expect.poll(async () => page.evaluate(() => (
      window.__mapPerformanceEvents.interactive.at(-1) || null
    )), { timeout: 30000 }).not.toBeNull()
    await expect.poll(async () => page.evaluate(() => window.L?.version || null), {
      timeout: 30000,
    }).toBe("1.9.4")

    const coldInteractive = await page.evaluate(() => (
      window.__mapPerformanceEvents.interactive.at(-1)
    ))
    const fixtureValidation = await validateMapPerformanceFixture(fixture)
    const hotInteractive = []
    let warmupInteractive = null
    for (let navigation = 0; navigation < 11; navigation += 1) {
      const previousCount = await page.evaluate(() => (
        window.__mapPerformanceEvents.interactive.length
      ))
      await page.getByRole("button", { name: "← 返回总览", exact: true }).click()
      await page.getByRole("button", { name: "继续最近地图", exact: true }).click()
      await expect.poll(async () => page.evaluate(() => (
        window.__mapPerformanceEvents.interactive.length
      )), { timeout: 30000 }).toBe(previousCount + 1)
      const interactive = await page.evaluate(() => (
        window.__mapPerformanceEvents.interactive.at(-1)
      ))
      if (navigation === 0) warmupInteractive = interactive
      else hotInteractive.push(interactive)
    }
    expect(new Set([
      coldInteractive.telemetry_id,
      warmupInteractive.telemetry_id,
      ...hotInteractive.map((item) => item.telemetry_id),
    ]).size).toBe(12)

    const canvas = page.locator(SEL.mapCanvas)
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()
    const initialViewport = await leafletViewportState(page)
    await canvas.click({
      position: { x: box.width / 2, y: box.height / 2 },
    })
    await page.mouse.wheel(0, -240)
    await page.waitForTimeout(350)
    const zoomedViewport = await leafletViewportState(page)
    expect(zoomedViewport).not.toEqual(initialViewport)

    const cdp = await page.context().newCDPSession(page)
    await cdp.send("Input.dispatchTouchEvent", {
      type: "touchStart",
      touchPoints: [{ x: box.x + 240, y: box.y + 200 }],
    })
    for (let step = 0; step < 12; step += 1) {
      await cdp.send("Input.dispatchTouchEvent", {
        type: "touchMove",
        touchPoints: [{ x: box.x + 240 + step * 3, y: box.y + 200 + step * 2 }],
      })
      await page.waitForTimeout(18)
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] })

    const touchViewport = await leafletViewportState(page)
    await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.45)
    await page.mouse.down()
    for (let index = 0; index < 125; index += 1) {
      const x = box.x + box.width * 0.45 + ((index % 20) - 10) * 2
      const y = box.y + box.height * 0.45 + ((index % 16) - 8) * 2
      await page.mouse.move(x, y)
      await page.waitForTimeout(18)
    }
    await page.mouse.up()
    const draggedViewport = await leafletViewportState(page)
    expect(draggedViewport.mapPaneTransform).not.toBe(touchViewport.mapPaneTransform)

    await expect.poll(async () => page.evaluate(() => (
      window.__mapPerformanceEvents.samples.at(-1) || null
    )), { timeout: 30000 }).not.toBeNull()
    const sample = await page.evaluate(() => (
      window.__mapPerformanceEvents.samples.at(-1)
    ))

    expect(sample.frames.sampled).toBe(100)
    expect(sample.input.sampled).toBeGreaterThanOrEqual(100)
    expect(sample.frames.raw_redraw_cpu_ms).toHaveLength(100)
    expect(sample.input.raw_to_paint_ms).toHaveLength(100)
    expect(nearestRank(sample.frames.raw_redraw_cpu_ms, 0.95)).toBe(
      sample.frames.p95_redraw_cpu_ms,
    )
    expect(nearestRank(sample.input.raw_to_paint_ms, 0.95)).toBe(
      sample.input.p95_to_paint_ms,
    )
    expect(sample.input.clicked_hex).toBe(true)
    expect(sample.input.types).toEqual(expect.objectContaining({
      click: expect.any(Number),
      drag: expect.any(Number),
      touch: expect.any(Number),
      wheel: expect.any(Number),
    }))
    for (const inputType of ["click", "drag", "touch", "wheel"]) {
      expect(sample.input.types[inputType]).toBeGreaterThan(0)
    }
    expect(sample.telemetry_id).toBe(hotInteractive.at(-1).telemetry_id)
    expect(sample.frames.p95_redraw_cpu_ms).not.toBeNull()
    expect(sample.input.p95_to_paint_ms).not.toBeNull()

      const hotDurations = hotInteractive.map((item) => item.interactive_ms)
      const hotSummary = {
        median: nearestRank(hotDurations, 0.5),
        p75: nearestRank(hotDurations, 0.75),
        max: Math.max(...hotDurations),
      }
      expect(hotInteractive).toHaveLength(10)
      expect(hotDurations.every((duration) => Number.isFinite(duration))).toBe(true)
      expect(hotSummary.p75).toBeLessThanOrEqual(budgetMs)
      expect(hotSummary.max).toBeLessThanOrEqual(budgetMs * 2)
      expect(sample.input.p95_to_paint_ms).toBeLessThanOrEqual(33)
      const workingTree = await gitWorkingTreeIdentity()

      const report = {
        fixture: {
          profile: fixture.profileName,
          manifest_version: fixture.manifestVersion,
          checksum: fixture.checksum,
          expected_payload_checksum: fixture.expectedPayloadChecksum,
          actual_payload_checksum: fixtureValidation.actualPayloadChecksum,
          semantic_payload: fixture.semanticPayload,
          actual_counts: fixtureValidation.actualCounts,
          terrain_counts: fixtureValidation.terrainCounts,
        },
        budget: {
          interactive_p75_ms: budgetMs,
          interactive_single_sample_max_ms: budgetMs * 2,
          input_to_paint_p95_ms: 33,
        },
        environment: {
          ...workingTree,
          browser: browser.version(),
          platform: `${os.platform()} ${os.release()} ${os.arch()}`,
          cpu_count: os.cpus().length,
          total_memory_bytes: os.totalmem(),
          free_memory_bytes: os.freemem(),
          load_average: os.loadavg(),
          power: process.env.PERF_POWER_PROFILE || "unknown",
          database_fingerprint: databaseFingerprint(),
          cold_map_navigation: true,
          application_cold_start: false,
          leaflet_version: "1.9.4",
        },
        telemetry: sample,
        navigation_samples: {
          cold: coldInteractive,
          warmup: warmupInteractive,
          hot: hotInteractive,
          hot_summary_ms: hotSummary,
        },
      }
      const reportName = `map-performance-${profileName}.json`
      const reportPath = testInfo.outputPath(reportName)
      await writeFile(reportPath, JSON.stringify(report, null, 2), "utf8")
      await testInfo.attach(reportName, {
        path: reportPath,
        contentType: "application/json",
      })
    })
  }
})
