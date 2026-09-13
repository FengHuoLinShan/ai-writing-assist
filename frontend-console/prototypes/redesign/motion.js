// A small content fade shared by the preview's state-driven regions.
const active = new Map()
let reducedMotion = false

export function cancelPreviewMotion() {
  for (const animation of active.values()) animation.cancel()
  active.clear()
}

export function setPreviewReducedMotion(value) {
  reducedMotion = value
  if (value) cancelPreviewMotion()
}

export function revealContent(element) {
  const previous = active.get(element)
  const currentOpacity = previous?.playState === 'running' ? getComputedStyle(element).opacity : null
  previous?.cancel()
  active.delete(element)
  if (reducedMotion || globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches || !element.animate) return
  const opacity = Number(getComputedStyle(element).opacity || 1)
  const animation = element.animate([{ opacity: currentOpacity ?? opacity * 0.78 }, { opacity }], {
    duration: 160,
    easing: 'ease-out',
  })
  active.set(element, animation)
  void animation.finished.catch(() => {}).finally(() => {
    if (active.get(element) === animation) active.delete(element)
  })
}

export const vReveal = {
  mounted: revealContent,
  updated(element, { value, oldValue }) {
    if (value !== oldValue) revealContent(element)
  },
  beforeUnmount(element) {
    active.get(element)?.cancel()
    active.delete(element)
  },
}
