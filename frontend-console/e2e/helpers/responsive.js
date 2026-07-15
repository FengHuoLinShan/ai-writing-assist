import { expect } from "@playwright/test"

export const RESPONSIVE_VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 900, height: 800 },
  { width: 760, height: 844 },
  { width: 600, height: 800 },
  { width: 390, height: 844 },
]

export async function expectNoPageOverflow(page, tolerance = 2) {
  const metrics = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body?.scrollWidth || 0,
  }))
  const maxScrollWidth = Math.max(metrics.scrollWidth, metrics.bodyScrollWidth)
  expect(
    maxScrollWidth,
    `page overflow: scrollWidth ${maxScrollWidth}, viewport ${metrics.innerWidth}`,
  ).toBeLessThanOrEqual(metrics.innerWidth + tolerance)
}

export async function expectWithinViewport(locator) {
  await expect(locator).toBeVisible()
  const box = await locator.boundingBox()
  if (!box) throw new Error("locator has no bounding box")
  const viewport = await locator.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }))

  expect(box.x, `left edge outside viewport: ${JSON.stringify(box)}`).toBeGreaterThanOrEqual(0)
  expect(box.y, `top edge outside viewport: ${JSON.stringify(box)}`).toBeGreaterThanOrEqual(0)
  expect(
    box.x + box.width,
    `right edge outside viewport: ${JSON.stringify(box)} > ${viewport.width}`,
  ).toBeLessThanOrEqual(viewport.width + 2)
  expect(
    box.y + box.height,
    `bottom edge outside viewport: ${JSON.stringify(box)} > ${viewport.height}`,
  ).toBeLessThanOrEqual(viewport.height + 2)
}

export async function expectWithinViewportWidth(locator) {
  await expect(locator).toBeVisible()
  const box = await locator.boundingBox()
  if (!box) throw new Error("locator has no bounding box")
  const viewportWidth = await locator.evaluate(() => window.innerWidth)

  expect(box.x, `left edge outside viewport: ${JSON.stringify(box)}`).toBeGreaterThanOrEqual(0)
  expect(
    box.x + box.width,
    `right edge outside viewport: ${JSON.stringify(box)} > ${viewportWidth}`,
  ).toBeLessThanOrEqual(viewportWidth + 2)
}

export async function runResponsiveMatrix(page, callback, viewports = RESPONSIVE_VIEWPORTS) {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await callback(viewport)
  }
}
