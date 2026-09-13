import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cancelPreviewMotion, revealContent, setPreviewReducedMotion, vReveal } from '../../prototypes/redesign/motion.js'
import SearchPreview from '../../prototypes/redesign/SearchPreview.vue'

let wrapper
const originalAnimate = Object.getOwnPropertyDescriptor(Element.prototype, 'animate')
function animation() {
  let finish
  let reject
  const result = {
    playState: 'running',
    finished: new Promise((resolve, rejectPromise) => { finish = resolve; reject = rejectPromise }),
    cancel: vi.fn(() => { result.playState = 'idle'; reject(new Error('Cancelled')) }),
    finish: () => { result.playState = 'finished'; finish() },
  }
  return result
}
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  cancelPreviewMotion()
  setPreviewReducedMotion(false)
  vi.restoreAllMocks()
  if (originalAnimate) Object.defineProperty(Element.prototype, 'animate', originalAnimate)
  else delete Element.prototype.animate
})

describe('preview motion lifecycle', () => {
  it('preserves the content state opacity instead of overriding a loading presentation', () => {
    const element = document.createElement('div')
    element.style.opacity = '0.32'
    element.animate = vi.fn(() => animation())
    document.body.append(element)
    revealContent(element)
    const [frames] = element.animate.mock.calls[0]
    element.remove()
    expect(frames.at(-1).opacity).toBe(0.32)
    expect(frames[0].opacity).toBeLessThanOrEqual(0.32)
  })

  it('cancels a superseded fade and keeps its late completion from losing the replacement', async () => {
    const element = document.createElement('div')
    const first = animation(), second = animation()
    element.animate = vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second)
    revealContent(element)
    revealContent(element)
    expect(first.cancel).toHaveBeenCalledOnce()
    await flushPromises()
    setPreviewReducedMotion(true)
    expect(second.cancel).toHaveBeenCalledOnce()
  })

  it('stops in-flight motion on removal and does not start new motion in reduced mode', () => {
    const element = document.createElement('div'), current = animation()
    element.animate = vi.fn(() => current)
    vReveal.mounted(element)
    vReveal.beforeUnmount(element)
    expect(current.cancel).toHaveBeenCalledOnce()
    setPreviewReducedMotion(true)
    vReveal.updated(element, { value: 'new', oldValue: 'old' })
    expect(element.animate).toHaveBeenCalledOnce()
  })

  it('keeps search typing static and preserves the query through category changes', async () => {
    const animate = vi.fn(() => animation())
    Object.defineProperty(Element.prototype, 'animate', { configurable: true, value: animate })
    wrapper = mount(SearchPreview)
    animate.mockClear()
    for (const query of ['灯', '灯塔', '不存在']) await wrapper.get('#rd-search-query').setValue(query)
    expect(animate).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('还没有找到这条线索')
    await wrapper.findAll('button').find(button => button.text() === '正文').trigger('click')
    expect(wrapper.get('#rd-search-query').element.value).toBe('不存在')
    expect(wrapper.text()).toContain('还没有找到这条线索')
  })

  it('leaves content available when Web Animations is unavailable', () => {
    const element = document.createElement('div')
    element.textContent = '原文始终可读'
    element.animate = undefined
    expect(() => revealContent(element)).not.toThrow()
    expect(element.textContent).toBe('原文始终可读')
    expect(element.style.opacity).toBe('')
  })
})
