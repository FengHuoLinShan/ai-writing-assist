import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import WorldDesignPanel from '../../../vue/views/generate/components/WorldDesignPanel.vue'
import CocreationHistory from '../../../vue/views/generate/components/CocreationHistory.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
afterEach(resetBridgeOverrides)

describe('persistent world continuation', () => {
  it('keeps fixed test names read-only while allowing result edits', async () => {
    const entry = { id: 'T12', name: '十年后', status: 'not-run', result: '待推演' }
    const wrapper = mount(WorldDesignPanel, { props: { checkpoint: { depth: 'seed', decisions: [], world_state: { pressure_tests: [entry] } }, proposal: { summary: '观察反馈', changes: { pressure_tests: [entry] }, decisions: [] } } })
    const name = wrapper.findAll('label').find(label => label.text().startsWith('名称'))
    expect(name.find('textarea').exists()).toBe(false)
    const result = wrapper.findAll('label').find(label => label.text().startsWith('推演结果'))
    await result.get('textarea').setValue('十年后的资源变化')
    expect(wrapper.emitted('update:proposal').at(-1)[0].changes.pressure_tests[0]).toMatchObject({ name: '十年后', result: '十年后的资源变化' })
  })

  it.each(['candidate', 'instance'])('invalidates a passed review when saving at %s depth', async depth => {
    const proposal = { summary: '潮门维护', changes: {}, decisions: [], depth: 'seed', review_summary: { status: 'passed' } }
    const wrapper = mount(WorldDesignPanel, { props: { checkpoint: { depth: 'seed', decisions: [], world_state: {} }, proposal } })
    const stage = wrapper.findAll('select').find(select => select.find('option[value="instance"]').exists())
    await stage.setValue(depth)
    const edited = wrapper.emitted('update:proposal').at(-1)[0]
    expect(edited).toMatchObject({ depth, reviewInvalidated: true })
    await wrapper.setProps({ proposal: edited })
    expect(wrapper.text()).toContain('保存未复核阶段成果')
    expect(proposal.depth).toBe('seed')
  })

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

  it('shows author-facing review conclusions and requires an edit before saving a blocked result', async () => {
    const proposal = {
      summary: '潮门依赖每日盐料', changes: {}, decisions: [],
      task_brief: {
        current_author_goal: '补足潮门维护闭环',
        working_assumptions: ['盐料可储存七日'],
        checkable_commitments: ['说明资源、维护和故障反馈'],
      },
      review_summary: {
        status: 'blocked', checked_aspects: ['作者目标', '资源与维护'],
        addressed_issues: ['已补降级路径'], insufficient_evidence: ['盐矿产量待补证据'],
        author_decisions: ['效率与自治需要作者决定', '维护职责仍悬空'],
        internal_issue_id: 'world-design:private', role_name: 'causal_reviewer', prompt: 'hidden prompt',
      },
    }
    const wrapper = mount(WorldDesignPanel, { props: { checkpoint: { depth: 'seed', decisions: [], world_state: {} }, proposal } })
    expect(wrapper.get('[data-section="world-design-task-brief"]').text()).toContain('补足潮门维护闭环')
    const review = wrapper.get('[data-section="world-design-review-summary"]')
    expect(review.text()).toContain('盐矿产量待补证据')
    expect(review.text()).toContain('效率与自治需要作者决定')
    expect(review.text()).toContain('维护职责仍悬空')
    expect(wrapper.text()).not.toContain('world-design:private')
    expect(wrapper.text()).not.toContain('causal_reviewer')
    expect(wrapper.text()).not.toContain('hidden prompt')
    const save = wrapper.findAll('button').find(button => button.text() === '先修改或重新推演')
    expect(save.element.disabled).toBe(true)
    await wrapper.get('textarea').setValue('作者修改后的说明')
    const edited = wrapper.emitted('update:proposal').at(-1)[0]
    expect(edited.reviewInvalidated).toBe(true)
    await wrapper.setProps({ proposal: edited })
    const editedSave = wrapper.findAll('button').find(button => button.text() === '保存未复核阶段成果')
    expect(editedSave.element.disabled).toBe(false)
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
