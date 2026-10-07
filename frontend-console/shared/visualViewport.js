function finiteNumber(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

export function readVisualViewportRect(
  visualViewport = globalThis.visualViewport,
  documentElement = globalThis.document?.documentElement,
) {
  const left = finiteNumber(visualViewport?.offsetLeft)
  const top = finiteNumber(visualViewport?.offsetTop)
  const width = Math.max(0, finiteNumber(visualViewport?.width, finiteNumber(documentElement?.clientWidth, globalThis.innerWidth)))
  const height = Math.max(0, finiteNumber(visualViewport?.height, finiteNumber(documentElement?.clientHeight, globalThis.innerHeight)))
  return { left, top, right: left + width, bottom: top + height, width, height }
}

// The shell owns this binding; teleported panels consume the same visible bounds.
export function bindVisualViewport(root = document.documentElement, host = window) {
  const viewport = host.visualViewport
  const names = ['--visible-height', '--visible-width', '--visible-top', '--visible-left', '--visible-bottom', '--app-height', '--app-top']
  const previous = names.map(name => [name, root.style.getPropertyValue(name), root.style.getPropertyPriority(name)])
  function update() {
    const rect = readVisualViewportRect(viewport, root)
    const zoomed = viewport?.scale > 1.01
    const values = [rect.height, rect.width, rect.top, rect.left, Math.max(0, host.innerHeight - rect.bottom), zoomed ? host.innerHeight : rect.height, zoomed ? 0 : rect.top]
    names.forEach((name, index) => root.style.setProperty(name, `${values[index]}px`))
  }
  update()
  host.addEventListener('resize', update)
  viewport?.addEventListener('resize', update)
  viewport?.addEventListener('scroll', update)
  return () => {
    host.removeEventListener('resize', update)
    viewport?.removeEventListener('resize', update)
    viewport?.removeEventListener('scroll', update)
    previous.forEach(([name, value, priority]) => value ? root.style.setProperty(name, value, priority) : root.style.removeProperty(name))
  }
}
