import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import WorldDesignPanel from '../../../vue/views/generate/components/WorldDesignPanel.vue'
import CocreationHistory from '../../../vue/views/generate/components/CocreationHistory.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
afterEach(resetBridgeOverrides)

describe('persistent world continuation', () => {
  it('edits a typed change without changing its saved parent or showing internal identities', async () => {
    const checkpoint = { depth: 'candidate', decisions: [], world_state: { rules: [{ id: 'rule:private-id', name: '潮门', status: 'proposed', capability: '运货', impossibility: '不能运人', costs: ['耗盐'] }] } }
    const original = JSON.stringify(checkpoint)
    const wrapper = mount(WorldDesignPanel, { props: { checkpoint } })
    const edit = wrapper.findAll('button').find(button => button.text() === '局部修改')
    await edit.trigger('click')
    const draft = wrapper.emitted('update:proposal')[0][0]
    expect(draft.changes.rules[0].id).toBe('rule:private-id')
    await wrapper.setProps({ proposal: draft })
    const costs = wrapper.findAll('label').find(label => label.text().startsWith('代价（'))
    await costs.get('textarea').setValue('耗盐两袋')
    expect(wrapper.emitted('update:proposal').at(-1)[0].changes.rules[0].costs).toEqual(['耗盐两袋'])
    expect(JSON.stringify(checkpoint)).toBe(original)
    expect(wrapper.text()).not.toContain('rule:private-id')
    await wrapper.setProps({ busy: true })
    expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  })

  it('preserves an existing author decision identity while changing its disposition', async () => {
    const decision = { item_key: 'no-revival', disposition: 'rejected', text: '不得复活', source_keys: [] }
    const wrapper = mount(WorldDesignPanel, { props: { checkpoint: { depth: 'seed', decisions: [decision], world_state: {} } } })
    await wrapper.findAll('button').find(button => button.text() === '修改决定').trigger('click')
    await wrapper.setProps({ proposal: wrapper.emitted('update:proposal')[0][0] })
    await wrapper.findAll('select')[0].setValue('open')
    expect(wrapper.emitted('update:proposal').at(-1)[0].decisions[0]).toMatchObject({ item_key: 'no-revival', disposition: 'open' })
    expect(decision.disposition).toBe('rejected')
  })

  it('paginates all sessions, reads historical context and only explicitly selects a reference', async () => {
    const api = { world: {
      listCocreationSessions: vi.fn(async () => ({ total: 101, items: [{ id: 'session-1', title: '盐商历史', status: 'active' }] })),
      listCocreationMessages: vi.fn(async (_id, _novel, query) => ({ total: 1000, offset: query.around_message_id ? 485 : query.skip, items: [{ id: 'message-500', role: 'author', kind: 'message', content: '既有维护决定' }] })),
    } }
    setBridgeOverrides({ api })
    const wrapper = mount(CocreationHistory, { props: { open: true, projectId: 'p1', sessionId: 'session-1', source: { kind: 'project' }, preset: 'world_core', targetKind: 'core_entity' }, attachTo: document.body })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '下一页').trigger('click')
    expect(api.world.listCocreationSessions).toHaveBeenLastCalledWith('p1', expect.objectContaining({ skip: 30 }))
    await wrapper.findAll('button').find(button => button.text() === '阅读历史').trigger('click')
    await flushPromises()
    await wrapper.get('input[type="search"]').setValue('维护')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.emitted('update:selectedIds')).toBeUndefined()
    await wrapper.findAll('button').find(button => button.text() === '查看前后文').trigger('click'); await flushPromises()
    expect(api.world.listCocreationMessages).toHaveBeenLastCalledWith('session-1', 'p1', expect.objectContaining({ around_message_id: 'message-500' }))
    await wrapper.get('input[type="checkbox"]').setValue(true)
    expect(wrapper.emitted('update:selectedIds').at(-1)[0]).toEqual(['message-500'])
  })
})
