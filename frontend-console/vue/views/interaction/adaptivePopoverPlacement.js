const DEFAULT_GAP = 8
const DEFAULT_MARGIN = 12
const MIN_ARROW_INSET = 18

function finiteNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function clamp(value, minimum, maximum) {
  if (maximum <= minimum) return minimum
  return Math.min(Math.max(value, minimum), maximum)
}

function normalizeRect(rect = {}) {
  const left = finiteNumber(rect.left ?? rect.x)
  const top = finiteNumber(rect.top ?? rect.y)
  const width = Math.max(0, finiteNumber(
    rect.width,
    finiteNumber(rect.right) - left,
  ))
  const height = Math.max(0, finiteNumber(
    rect.height,
    finiteNumber(rect.bottom) - top,
  ))
  return {
    left,
    top,
    right: finiteNumber(rect.right, left + width),
    bottom: finiteNumber(rect.bottom, top + height),
    width,
    height,
  }
}

export function readVisualViewportRect(
  visualViewport = globalThis.visualViewport,
  documentElement = globalThis.document?.documentElement,
) {
  const left = finiteNumber(visualViewport?.offsetLeft)
  const top = finiteNumber(visualViewport?.offsetTop)
  const width = Math.max(
    0,
    finiteNumber(
      visualViewport?.width,
      finiteNumber(documentElement?.clientWidth, globalThis.innerWidth),
    ),
  )
  const height = Math.max(
    0,
    finiteNumber(
      visualViewport?.height,
      finiteNumber(documentElement?.clientHeight, globalThis.innerHeight),
    ),
  )
  return { left, top, right: left + width, bottom: top + height, width, height }
}

export function calculateAdaptivePopoverPlacement({
  anchorRect,
  popoverRect,
  viewportRect,
  gap = DEFAULT_GAP,
  margin = DEFAULT_MARGIN,
}) {
  const anchor = normalizeRect(anchorRect)
  const popover = normalizeRect(popoverRect)
  const viewport = normalizeRect(viewportRect)
  const safeGap = Math.max(0, finiteNumber(gap, DEFAULT_GAP))
  const requestedMargin = Math.max(0, finiteNumber(margin, DEFAULT_MARGIN))
  const horizontalMargin = Math.min(requestedMargin, viewport.width / 2)
  const verticalMargin = Math.min(requestedMargin, viewport.height / 2)
  const viewportLeft = viewport.left + horizontalMargin
  const viewportRight = viewport.right - horizontalMargin
  const viewportTop = viewport.top + verticalMargin
  const viewportBottom = viewport.bottom - verticalMargin

  // Safari can leave the layout viewport stationary while its visual viewport
  // moves above the address bar or software keyboard. Clamp an off-screen
  // anchor to the currently visible edge so the confirmation remains usable.
  const visibleAnchorTop = clamp(anchor.top, viewportTop, viewportBottom)
  const visibleAnchorBottom = clamp(anchor.bottom, viewportTop, viewportBottom)
  const anchorTop = Math.min(visibleAnchorTop, visibleAnchorBottom)
  const anchorBottom = Math.max(visibleAnchorTop, visibleAnchorBottom)
  const spaceAbove = Math.max(0, anchorTop - viewportTop - safeGap)
  const spaceBelow = Math.max(0, viewportBottom - anchorBottom - safeGap)

  let placement
  if (spaceBelow >= popover.height) placement = "bottom"
  else if (spaceAbove >= popover.height) placement = "top"
  else placement = spaceAbove > spaceBelow ? "top" : "bottom"

  const availableHeight = placement === "top" ? spaceAbove : spaceBelow
  const height = Math.min(popover.height, availableHeight)
  const availableWidth = Math.max(0, viewportRight - viewportLeft)
  const width = Math.min(popover.width, availableWidth)
  const anchorCenter = clamp(
    anchor.left + anchor.width / 2,
    viewportLeft,
    viewportRight,
  )
  const left = clamp(
    anchorCenter - width / 2,
    viewportLeft,
    viewportRight - width,
  )
  const top = placement === "top"
    ? Math.max(viewportTop, anchorTop - safeGap - height)
    : Math.min(anchorBottom + safeGap, viewportBottom - height)
  const arrowInset = Math.min(MIN_ARROW_INSET, width / 2)
  const arrowX = clamp(anchorCenter - left, arrowInset, width - arrowInset)

  return {
    placement,
    left,
    top,
    width,
    maxHeight: availableHeight,
    arrowX,
    spaceAbove,
    spaceBelow,
  }
}
