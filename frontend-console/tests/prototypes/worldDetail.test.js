import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import WorldDetail from '../../prototypes/redesign/WorldDetail.vue'
import { people } from '../../prototypes/redesign/data.js'

const entry = { ...people[0], id: people[0].name, source: '第一部 · 第三章' }

afterEach(() => vi.unstubAllGlobals())

describe('WorldDetail', () => {
  it('keeps the original values when local editing is cancelled and shows saved preview text', async () => {
    const wrapper = mount(WorldDetail, { props: { entry } })
    await wrapper.findAll('button').find(button => button.text() === '编辑资料').trigger('click')
    await wrapper.get('[aria-label="资料说明"]').setValue('这段修改应该被取消。')
    await wrapper.findAll('button').find(button => button.text() === '取消编辑').trigger('click')
    expect(wrapper.text()).toContain(entry.note)
    expect(wrapper.text()).not.toContain('这段修改应该被取消。')

    await wrapper.findAll('button').find(button => button.text() === '编辑资料').trigger('click')
    await wrapper.get('[aria-label="资料说明"]').setValue('本次预览保留的资料说明。')
    await wrapper.findAll('button').find(button => button.text() === '保存本地示例').trigger('click')
    expect(wrapper.text()).toContain('本次预览保留的资料说明。')
    expect(wrapper.text()).toContain('资料调整已保存在本次预览')
  })

  it('demonstrates no-image, failed, reload, and replacement states locally', async () => {
    const wrapper = mount(WorldDetail, { props: { entry } })
    expect(wrapper.get('[aria-label="图片状态演示"]').element.value).toBe('无图片')
    await wrapper.get('[aria-label="图片状态演示"]').setValue('加载失败')
    expect(wrapper.get('[role="alert"]').text()).toContain('图片暂时无法显示')
    await wrapper.get('.rd-world-image .rd-text-button').trigger('click')
    expect(wrapper.get('[aria-label="图片状态演示"]').element.value).toBe('可用')
    expect(wrapper.text()).toContain('已替换示例图片')
    await wrapper.get('[aria-label="图片状态演示"]').setValue('加载中')
    expect(wrapper.get('[role="status"]').text()).toContain('正在载入示例图片')
  })

  it('keeps source history connected and requires confirmation for archive', async () => {
    const wrapper = mount(WorldDetail, { props: { entry } })
    await wrapper.get('.rd-world-history-source .rd-text-button').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['search', '正文'])

    const confirm = vi.fn().mockReturnValue(false)
    vi.stubGlobal('confirm', confirm)
    await wrapper.get('.rd-world-danger summary').trigger('click')
    await wrapper.get('.rd-world-danger .rd-button').trigger('click')
    expect(confirm).toHaveBeenCalledWith('确定要归档「林舟」吗？')
    expect(wrapper.text()).toContain('已取消归档')
    confirm.mockReturnValue(true)
    await wrapper.get('.rd-world-danger .rd-button').trigger('click')
    expect(wrapper.text()).toContain('归档已确认')
  })
})
