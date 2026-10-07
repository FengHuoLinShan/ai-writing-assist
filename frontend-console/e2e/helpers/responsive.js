import { expect } from '@playwright/test'

// Representative environments, not required breakpoints or layouts.
export const RESPONSIVE_VIEWPORTS = [
  { width: 320, height: 740 },
  { width: 390, height: 844 },
  { width: 768, height: 900 },
  { width: 1280, height: 800 },
  { width: 1920, height: 1080 },
]

export const WORKSPACE_VIEWPORTS = [
  ...RESPONSIVE_VIEWPORTS,
  { width: 900, height: 800 },
  { width: 1024, height: 768 },
  { width: 1440, height: 900 },
  { width: 2560, height: 1440 },
  { width: 844, height: 390 },
  { width: 1000, height: 500 },
]

export async function runResponsiveMatrix(page, callback, viewports = RESPONSIVE_VIEWPORTS) {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await callback(viewport)
  }
}

export async function expectResponsiveLayout(page) {
  const clipped = await page.evaluate(() => {
    const host = document.querySelector('#workspace-content')
    const targets = host?.querySelectorAll('button, input, select, textarea, summary, h1, h2, h3') || []
    return Array.from(targets).filter(element => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      if (!rect.width || !rect.height || style.visibility === 'hidden' || element.closest('[inert], [aria-hidden="true"]')) return false
      const closed = element.closest('details:not([open])')
      if (closed && !closed.querySelector(':scope > summary')?.contains(element)) return false
      if (rect.left >= -1 && rect.right <= innerWidth + 1) return false
      for (let parent = element.parentElement; parent && parent !== host; parent = parent.parentElement) {
        if (['auto', 'scroll'].includes(getComputedStyle(parent).overflowX) && parent.scrollWidth > parent.clientWidth + 1) return false
      }
      return true
    }).slice(0, 8).map(element => ({ label: element.getAttribute('aria-label') || element.textContent?.trim().slice(0, 60), tag: element.tagName }))
  })
  expect(clipped, '必要内容或操作被工作区裁切').toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '页面横向溢出').toBe(true)
}

export async function expectActionReachable(locator) {
  await expect(locator).toBeVisible()
  await locator.scrollIntoViewIfNeeded()
  await locator.click({ trial: true })
}
