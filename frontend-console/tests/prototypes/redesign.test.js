import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RedesignApp from '../../prototypes/redesign/RedesignApp.vue'
import { navigation } from '../../prototypes/redesign/data.js'

let wrapper
function button(text) {
  const target = wrapper.findAll('button').find(item => item.text().includes(text))
  expect(target, `Button: ${text}`).toBeTruthy()
  return target
}
async function navigate(label) {
  const menu = wrapper.find('.rd-document-menu')
  if (menu.exists()) {
    await menu.get('[aria-label="浏览作品与工作区"]').trigger('click')
    const target = menu.findAll('[role="menuitem"]').find(item => item.text() === label)
    expect(target, `Workspace menu: ${label}`).toBeTruthy()
    await target.trigger('click')
  } else {
    const target = wrapper.find('.rd-navigation').findAll('button').find(item => item.text().startsWith(label))
    expect(target, `Navigation: ${label}`).toBeTruthy()
    await target.trigger('click')
  }
}
afterEach(() => { wrapper?.unmount(); document.body.replaceChildren(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('independent design preview', () => {
  it('navigates all preview surfaces without API or persistence access and resets on remount', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => { throw Error('Preview must not fetch') })
    const read = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw Error('Preview must not read storage') })
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw Error('Preview must not write storage') })
    const db = vi.fn(() => { throw Error('Preview must not open databases') })
    vi.stubGlobal('indexedDB', { open: db })
    wrapper = mount(RedesignApp, { attachTo: document.body })
    expect(wrapper.get('h1').text()).toBe('潮汐之间')
    await wrapper.get('[aria-label="切换到深色"]').trigger('click')
    for (const item of navigation) {
      await navigate(item.title)
      expect(wrapper.find('h1').exists()).toBe(true)
      expect(wrapper.find('.rd-app').attributes('data-theme')).toBe('dark')
    }
    await button('林间').trigger('click')
    await button('作者与故事探索者').trigger('click')
    expect(wrapper.get('h1').text()).toBe('故事，因你而发生。')
    await button('我是探索者').trigger('click')
    await button('以演示身份继续').trigger('click')
    await button('回到白沙港').trigger('click')
    expect(wrapper.get('h1').text()).toBe('最后一班渡船')
    await wrapper.get('.rd-preview-tools>summary').trigger('click')
    await button('组件与动效').trigger('click')
    expect(wrapper.get('h1').text()).toBe('组件与状态')
    expect(fetchSpy).not.toHaveBeenCalled(); expect(read).not.toHaveBeenCalled(); expect(write).not.toHaveBeenCalled(); expect(db).not.toHaveBeenCalled()
    wrapper.unmount(); wrapper = mount(RedesignApp, { attachTo: document.body })
    expect(wrapper.get('h1').text()).toBe('潮汐之间')
    expect(wrapper.get('.rd-app').attributes('data-theme')).toBe('light')
  })

  it('keeps the selected chapter and demo manuscript across theme and focus changes', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await button('一封迟到的信').trigger('click')
    const prose = wrapper.get('.rd-prose').text()
    await wrapper.get('[aria-label="切换专注模式"]').trigger('click')
    await wrapper.get('[aria-label="切换到深色"]').trigger('click')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('一封迟到的信')
    expect(wrapper.get('.rd-prose').text()).toBe(prose)
    expect(wrapper.get('[aria-label="切换专注模式"]').attributes('aria-pressed')).toBe('false')
  })

  it('shows reversible error and conflict demonstrations without replacing manuscript', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    const prose = wrapper.get('.rd-prose').text()
    const state = wrapper.get('[aria-label="页面演示状态"]')
    await state.setValue('conflict')
    expect(wrapper.get('[role="status"]').text()).toContain('发现另一个更新版本')
    await state.setValue('error')
    expect(wrapper.get('[role="status"]').text()).toContain('这次保存没有完成')
    await state.setValue('normal')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.get('.rd-prose').text()).toBe(prose)
  })

  it('filters sample world content and opens a person without affecting other profiles', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await navigate('人物与世界')
    await wrapper.get('[aria-label="搜索世界资料"]').setValue('沈雁')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(1)
    expect(wrapper.get('.rd-world-entry').text()).toContain('灯塔守望者')
    await wrapper.get('[aria-label="搜索世界资料"]').setValue('不存在的资料')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(0)
    expect(wrapper.text()).toContain('没有找到匹配的资料')
  })

  it('uses a nonmodal context panel and lets document navigation replace it', async () => {
    const modal = vi.spyOn(HTMLDialogElement.prototype, 'showModal')
    const panel = vi.spyOn(HTMLDialogElement.prototype, 'show')
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await wrapper.get('[aria-label="写作伙伴"]').trigger('click')
    await flushPromises()
    expect(panel).toHaveBeenCalledOnce()
    expect(modal).not.toHaveBeenCalled()
    expect(wrapper.get('dialog').element.open).toBe(true)
    expect(wrapper.get('.rd-prose').text()).toContain('林舟抵达白沙港')
    await wrapper.get('[aria-label="切换章节目录"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog').element.open).toBe(false)
    expect(wrapper.get('[aria-label="切换章节目录"]').attributes('aria-pressed')).toBe('true')
  })

  it('returns focus on Escape and exposes only applicable focus-mode controls', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    const focusButton = wrapper.get('[aria-label="切换专注模式"]')
    await focusButton.trigger('click')
    expect(wrapper.find('[aria-label="切换章节目录"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="切换资料栏"]').exists()).toBe(false)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(document.activeElement).toBe(focusButton.element)
    expect(wrapper.get('[aria-label="切换专注模式"]').attributes('aria-pressed')).toBe('false')
  })

  it('keeps reader controls separate from author suggestions', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await navigate('互动故事')
    await button('回到白沙港').trigger('click')
    expect(wrapper.get('h1').text()).toBe('最后一班渡船')
    expect(wrapper.find('[aria-label="写作伙伴"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="阅读设置"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="旅程回顾"]').exists()).toBe(true)
  })


  it('restores the actual external trigger when a context panel is replaced by a modal', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await wrapper.get('.rd-preview-tools>summary').trigger('click')
    await button('组件与动效').trigger('click')
    const drawer = button('打开侧边抽屉')
    drawer.element.focus()
    await drawer.trigger('click')
    await flushPromises()
    const create = button('打开对话框')
    create.element.focus()
    await create.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(wrapper.get('dialog input').element)
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(document.activeElement).toBe(create.element)
  })

})
