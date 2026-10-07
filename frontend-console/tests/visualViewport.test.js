import { expect, it } from 'vitest'
import { bindVisualViewport, readVisualViewportRect } from '../shared/visualViewport.js'

it('tracks keyboard contraction and offsets, preserves pinch zoom layout and releases listeners/styles', () => {
  const viewport = Object.assign(new EventTarget(), { width: 390, height: 844, offsetLeft: 0, offsetTop: 0, scale: 1 })
  const host = Object.assign(new EventTarget(), { visualViewport: viewport, innerHeight: 844 })
  const root = document.createElement('html')
  root.style.setProperty('--app-height', '70vh', 'important')
  const stop = bindVisualViewport(root, host)
  Object.assign(viewport, { height: 320, offsetTop: 30 })
  viewport.dispatchEvent(new Event('resize'))
  expect(root.style.getPropertyValue('--app-height')).toBe('320px')
  expect(root.style.getPropertyValue('--visible-bottom')).toBe('494px')
  viewport.offsetTop = 50
  viewport.dispatchEvent(new Event('scroll'))
  expect(root.style.getPropertyValue('--app-top')).toBe('50px')
  viewport.scale = 2
  viewport.dispatchEvent(new Event('resize'))
  expect(root.style.getPropertyValue('--app-height')).toBe('844px')
  expect(root.style.getPropertyValue('--app-top')).toBe('0px')
  stop()
  viewport.dispatchEvent(new Event('resize'))
  host.dispatchEvent(new Event('resize'))
  expect(root.style.getPropertyValue('--app-height')).toBe('70vh')
  expect(root.style.getPropertyPriority('--app-height')).toBe('important')
  expect(root.style.getPropertyValue('--visible-height')).toBe('')
  expect(readVisualViewportRect(undefined, { clientWidth: 320, clientHeight: 500 })).toEqual({ left: 0, top: 0, right: 320, bottom: 500, width: 320, height: 500 })
})
