import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorldConnections from '../../prototypes/redesign/WorldConnections.vue'

describe('WorldConnections', () => {
  it('pairs an SVG overview with an accessible selectable node list', async () => {
    const wrapper = mount(WorldConnections)
    expect(wrapper.get('[role="img"]').attributes('aria-label')).toContain('关系示意')
    const nodes = wrapper.findAll('[role="list"] button')
    expect(nodes).toHaveLength(4)
    await nodes[1].trigger('click')
    expect(wrapper.get('[aria-label="选中对象关系详情"]').text()).toContain('沈雁')
    expect(wrapper.get('[aria-label="选中对象关系详情"]').text()).toContain('林舟')
  })

  it('provides keyboard friendly return paths without raw relationship ids', async () => {
    const wrapper = mount(WorldConnections)
    expect(wrapper.text()).not.toMatch(/entity_id|relation_id/)
    await wrapper.get('[aria-label="选中对象关系详情"] .rd-button').trigger('click')
    expect(wrapper.emitted('navigate')[0]).toEqual(['writing', '本章资料'])
    await wrapper.get('[aria-label="选中对象关系详情"] .rd-text-button').trigger('click')
    expect(wrapper.emitted('navigate')[1]).toEqual(['search', '正文'])
  })
})
