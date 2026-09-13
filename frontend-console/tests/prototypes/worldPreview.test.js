import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorldPreview from '../../prototypes/redesign/WorldPreview.vue'

describe('WorldPreview', () => {
  it('filters long world entries, switches density, and keeps selection tied to detail', async () => {
    const wrapper = mount(WorldPreview, { props: { initialSection: '人物' } })
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(2)

    await wrapper.get('[aria-label="搜索世界资料"]').setValue('沈雁')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(1)
    await wrapper.get('.rd-world-entry').trigger('click')
    expect(wrapper.get('[aria-label="资料详情"]').text()).toContain('沈雁')
    await wrapper.get('[aria-label="卡片视图"]').trigger('click')
    expect(wrapper.find('.rd-world-results.is-cards').exists()).toBe(true)
    expect(wrapper.get('[aria-label="资料详情"]').text()).toContain('灯塔守望者')
  })

  it('shows a useful no-match state and clears it without losing the page', async () => {
    const wrapper = mount(WorldPreview)
    await wrapper.get('[aria-label="搜索世界资料"]').setValue('不存在的资料')
    expect(wrapper.text()).toContain('没有找到匹配的资料')
    await wrapper.get('.rd-world-empty .rd-text-button').trigger('click')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(6)
    expect(wrapper.get('h1').text()).toContain('每一个名字')
  })

  it('keeps loading and empty states explicit with a usable empty-state action', async () => {
    const loading = mount(WorldPreview, { props: { state: 'loading' } })
    expect(loading.get('[role="status"]').text()).toContain('正在整理世界资料')
    expect(loading.findAll('.rd-world-entry')).toHaveLength(0)

    const empty = mount(WorldPreview, { props: { state: 'empty' } })
    expect(empty.text()).toContain('世界还没有留下资料')
    await empty.get('.rd-world-empty .rd-button').trigger('click')
    expect(empty.emitted('open')[0]).toEqual(['添加世界资料', 'new'])
  })

  it('preserves stale content on error and exposes a local retry demonstration', async () => {
    const wrapper = mount(WorldPreview, { props: { state: 'error' } })
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法读取')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(6)
    await wrapper.get('[role="alert"] button').trigger('click')
    expect(wrapper.get('[role="status"]').text()).toContain('示例资料已重新载入')
    expect(wrapper.findAll('.rd-world-entry')).toHaveLength(6)
  })

  it('emits navigation from the selected local detail without opening a static shell person', async () => {
    const wrapper = mount(WorldPreview)
    await wrapper.findAll('.rd-world-entry')[2].trigger('click')
    expect(wrapper.get('[aria-label="资料详情"]').text()).toContain('白沙港')
    await wrapper.get('[aria-label="资料详情"] .rd-button:not(.primary)').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['writing', '本章资料'])
    expect(wrapper.emitted('open')).toBeUndefined()
  })

  it('renders the world review tabs in place and forwards one shared compare action', async () => {
    const wrapper = mount(WorldPreview)
    await wrapper.findAll('[aria-label="世界资料分类"] button').find(button => button.text().includes('需要决定')).trigger('click')
    expect(wrapper.get('[aria-label="需要决定审阅"]').text()).toContain('等待你决定')
    await wrapper.get('[aria-label="需要决定审阅"] .rd-text-button').trigger('click')
    expect(wrapper.emitted('open')[0].slice(0,3)).toEqual(['世界资料 · 沈雁', 'compare', true])
    expect(wrapper.emitted('open')[0][3]).toMatchObject({ title: '沈雁', stale: false })
  })

  it('keeps relationship browsing and relationship review as separate reachable views', async () => {
    const wrapper = mount(WorldPreview, { props: { initialSection: '关系' } })
    expect(wrapper.get('[aria-label="世界关系与知识图谱"]')).toBeTruthy()
    await wrapper.get('[aria-label="关系视图"] button:nth-child(2)').trigger('click')
    expect(wrapper.get('[aria-label="关系审阅"]')).toBeTruthy()
    expect(wrapper.text()).toContain('关系也需要来源与判断')
  })

  it('keeps an edited object draft after closing and reopening its detail', async () => {
    const wrapper = mount(WorldPreview, { props: { initialSection: '人物' } })
    await wrapper.findAll('.rd-world-entry')[0].trigger('click')
    await wrapper.get('[aria-label="资料详情"] .rd-button.primary').trigger('click')
    await wrapper.get('[aria-label="资料说明"]').setValue('跨入口仍可回看的示例说明。')
    await wrapper.findAll('[aria-label="资料详情"] .rd-button').find(button => button.text() === '保存本地示例').trigger('click')
    await wrapper.get('[aria-label="关闭资料详情"]').trigger('click')
    await wrapper.findAll('.rd-world-entry')[0].trigger('click')
    expect(wrapper.get('[aria-label="资料详情"]').text()).toContain('跨入口仍可回看的示例说明。')
  })
})
