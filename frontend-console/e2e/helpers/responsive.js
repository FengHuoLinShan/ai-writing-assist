// Representative environments, not required breakpoints or layouts.
export const RESPONSIVE_VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 390, height: 844 },
]

export async function runResponsiveMatrix(page, callback, viewports = RESPONSIVE_VIEWPORTS) {
  for (const viewport of viewports) {
    await page.setViewportSize(viewport)
    await callback(viewport)
  }
}
