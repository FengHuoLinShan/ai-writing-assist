import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RedesignApp from '../../prototypes/redesign/RedesignApp.vue'
import ReaderPreview from '../../prototypes/redesign/ReaderPreview.vue'
import SettingsPreview from '../../prototypes/redesign/SettingsPreview.vue'
let wrapper
function button(text) { return wrapper.findAll('button').find(item => item.text().includes(text)) }
afterEach(() => { wrapper?.unmount(); document.body.replaceChildren(); vi.restoreAllMocks() })
describe('preview task continuity', () => {
  it('retains a writing draft through search, chapter location, and returning to search', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    const editor = wrapper.get('[aria-label="章节正文"]')
    editor.element.innerText = '保留下来的中文草稿。\n第二行。'
    await editor.trigger('input')
    await wrapper.get('[aria-label="预览页面"]').setValue('search')
    await button('雾中的灯塔').trigger('click')
    await button('定位到原章').trigger('click')
    await flushPromises()
    expect(wrapper.get('[aria-label="章节标题"]').text()).toBe('雾中的灯塔')
    await button('返回查找').trigger('click')
    await flushPromises()
    expect(wrapper.get('[aria-label="来源预览"]').text()).toContain('雾中的灯塔')
    expect(wrapper.get('#rd-search-query').element.value).toBe('灯塔')
    await button('返回写作').trigger('click')
    await flushPromises()
    await button('03').trigger('click')
    expect(wrapper.get('[aria-label="章节正文"]').text()).toContain('保留下来的中文草稿')
  })
  it('does not turn an absent reading choice into the first branch', async () => {
    wrapper = mount(ReaderPreview)
    expect(wrapper.get('[aria-label="查看分支反馈示例"]').element.disabled).toBe(true)
    await wrapper.get('input').setValue('我决定先问海图的来处')
    expect(wrapper.get('[aria-label="查看分支反馈示例"]').element.disabled).toBe(false)
    await wrapper.get('[aria-label="查看分支反馈示例"]').trigger('click')
    await button('采用这个发展').trigger('click')
    expect(wrapper.text()).toContain('你写下的发展已选中')
    expect(wrapper.text()).not.toContain('第 1 个发展已选中')
  })
  it('keeps model and image connection outcomes independent', async () => {
    wrapper = mount(SettingsPreview)
    await button('模型连接').trigger('click')
    await button('验证连接示例').trigger('click')
    await button('演示验证通过').trigger('click')
    expect(wrapper.text()).toContain('验证通过 · 演示')
    await button('图片服务').trigger('click')
    expect(wrapper.text()).toContain('未连接 · 演示')
    expect(wrapper.text()).not.toContain('验证通过 · 演示')
    await button('模型连接').trigger('click')
    expect(wrapper.text()).toContain('验证通过 · 演示')
  })
  it('compares the selected world candidate and returns its decision to the same item', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await wrapper.get('[aria-label="预览页面"]').setValue('world')
    await button('需要决定').trigger('click')
    const row = wrapper.findAll('.rd-world-review-row')[0]
    const trigger = row.findAll('button').find(item => item.text().includes('查看差异'))
    trigger.element.focus()
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.get('dialog h1').text()).toBe('沈雁')
    expect(wrapper.get('dialog').text()).not.toContain('落潮时出现的石路')
    await button('拒绝建议').trigger('click')
    await button('返回资料').trigger('click')
    await flushPromises()
    expect(wrapper.get('.rd-world-review').text()).toContain('已拒绝 1 项资料')
    expect(document.activeElement).toBe(wrapper.get('#rd-main').element)
  })
  it('clears both directory and enclosing world errors after rescanning the sample', async () => {
    wrapper = mount(RedesignApp, { attachTo: document.body })
    await wrapper.get('[aria-label="预览页面"]').setValue('world')
    await button('世界书').trigger('click')
    await wrapper.get('[aria-label="页面演示状态"]').setValue('error')
    expect(wrapper.findAll('[role="alert"]').length).toBeGreaterThan(0)
    await button('重新扫描示例').trigger('click')
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('示例目录已准备好')
  })

})
