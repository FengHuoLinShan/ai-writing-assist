import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorldReview from '../../prototypes/redesign/WorldReview.vue'

describe('WorldReview', () => {
  it('keeps expired sources out of confirmation while allowing rejection and compare review', async () => {
    const wrapper = mount(WorldReview, { props: { kind: '需要决定' } })
    const rows = wrapper.findAll('.rd-world-review-row')
    expect(rows).toHaveLength(2)
    expect(rows[1].findAll('button').find(button => button.text() === '确认这项').element.disabled).toBe(true)
    await rows[1].findAll('button').find(button => button.text() === '拒绝这项').trigger('click')
    expect(wrapper.text()).toContain('白沙港')
    expect(wrapper.text()).toContain('已拒绝')

    await rows[0].findAll('button').find(button => button.text().includes('查看差异')).trigger('click')
    expect(wrapper.emitted('open')[0].slice(0,3)).toEqual(['世界资料 · 沈雁', 'compare', true])
    expect(wrapper.emitted('open')[0][3]).toMatchObject({ title: '沈雁', source: '第一部 · 第三章', stale: false })
  })

  it('reports the current batch range and blocks a batch containing expired sources', async () => {
    const wrapper = mount(WorldReview, { props: { kind: '需要决定' } })
    await wrapper.get('[aria-label="全选当前待处理项"]').setValue(true)
    expect(wrapper.text()).toContain('已选 2 项')
    expect(wrapper.findAll('button').find(button => button.text() === '批量确认').element.disabled).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '批量拒绝').trigger('click')
    expect(wrapper.text()).toContain('已拒绝 2 项资料')
  })

  it('keeps relations readable without raw ids and keeps aliases attached to existing objects', async () => {
    const relations = mount(WorldReview, { props: { kind: '关系' } })
    expect(relations.text()).toContain('林舟 与 沈雁')
    expect(relations.text()).not.toMatch(/entity_id|relation_id/)

    const aliases = mount(WorldReview, { props: { kind: '别名' } })
    expect(aliases.text()).toContain('附着到已有对象')
    expect(aliases.text()).toContain('沈雁')
    expect(aliases.text()).not.toContain('建立新对象')
    await aliases.findAll('button').find(button => button.text().includes('查看差异')).trigger('click')
    const context = aliases.emitted('open')[0][3]
    expect(context.title).toBe('守塔人 → 沈雁')
    context.onStatus('rejected')
    await aliases.vm.$nextTick()
    expect(aliases.text()).toContain('已拒绝')
  })
})
