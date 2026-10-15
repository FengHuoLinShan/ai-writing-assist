import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ProjectVocabularyPanel from '../../../vue/views/map/ProjectVocabularyPanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
const term = (overrides = {}) => ({ id: 'type-1', revision_id: 'revision-1', revision_number: 1, kind: 'feature', name: '星门', aliases: [], description: '', source: 'author', status: 'active', traits: { geometry: ['point'], containment: [], connection: ['cross_space'], orientation: [], other: [] }, ...overrides })
let api, confirmAction
beforeEach(() => {
  api = { world: Object.fromEntries(['listProjectVocabulary', 'createVocabularyTerm', 'updateVocabularyTerm', 'archiveVocabularyTerm', 'restoreVocabularyTerm', 'mergeVocabularyTerms', 'splitVocabularyTerm', 'applyVocabularyPresets'].map(name => [name, vi.fn()])) }
  api.world.listProjectVocabulary.mockResolvedValue({ items: [term()], total_count: 1, omitted_count: 0 })
  confirmAction = vi.fn((message, confirm) => confirm())
  setBridgeOverrides({ api, confirmAction })
})
afterEach(resetBridgeOverrides)
async function open(props = {}) {
  const wrapper = mount(ProjectVocabularyPanel, { props: { projectId: 'novel-1', ...props } })
  wrapper.find('details').element.open = true
  await wrapper.find('details').trigger('toggle')
  await flushPromises()
  return wrapper
}
function button(wrapper, text) { return wrapper.findAll('button').find(item => item.text().includes(text)) }
async function selectFirst(wrapper) { await wrapper.get('.vocabulary-list button').trigger('click'); await flushPromises() }

describe('项目类型管理', () => {
  it('默认折叠时不加载；空态和上限省略如实显示', async () => {
    const wrapper = mount(ProjectVocabularyPanel, { props: { projectId: 'novel-1' } })
    expect(api.world.listProjectVocabulary).not.toHaveBeenCalled()
    api.world.listProjectVocabulary.mockResolvedValue({ items: [], total_count: 501, omitted_count: 501 })
    wrapper.find('details').element.open = true
    await wrapper.find('details').trigger('toggle'); await flushPromises()
    expect(wrapper.text()).toContain('501 项未显示')
    expect(wrapper.text()).toContain('没有匹配的已读取类型')
  })

  it('保存自定义名称和特性，收到回执后才显示成功', async () => {
    const wrapper = await open()
    await button(wrapper, '新增类型').trigger('click'); await flushPromises()
    await wrapper.get('input[maxlength="120"]').setValue('灵脉锚点')
    const point = wrapper.findAll('input[type="checkbox"]').find(item => item.element.value === 'point')
    await point.setValue(true)
    let resolve
    api.world.createVocabularyTerm.mockImplementation(() => new Promise(done => { resolve = done }))
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).not.toContain('类型已保存。')
    expect(api.world.createVocabularyTerm).toHaveBeenCalledWith('novel-1', expect.objectContaining({ name: '灵脉锚点', kind: 'feature', traits: expect.objectContaining({ geometry: ['point'] }) }))
    resolve(term({ name: '灵脉锚点' })); await flushPromises()
    expect(wrapper.text()).toContain('类型已保存。')
    expect(wrapper.emitted('state').at(-1)[0]).toEqual({ dirty: false, busy: false })
  })

  it('CAS冲突保留作者输入，重新读取不会偷偷覆盖编辑', async () => {
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.get('input[maxlength="120"]').setValue('作者新名称')
    api.world.updateVocabularyTerm.mockRejectedValue(Object.assign(new Error('conflict'), { status: 409 }))
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.world.updateVocabularyTerm).toHaveBeenCalledWith('novel-1', 'type-1', expect.objectContaining({ expected_revision_id: 'revision-1', name: '作者新名称' }))
    expect(wrapper.get('[role="alert"]').text()).toContain('编辑内容已保留')
    api.world.listProjectVocabulary.mockResolvedValue({ items: [term({ name: '另一设备的名称', revision_id: 'revision-2' })], total_count: 1, omitted_count: 0 })
    await button(wrapper, '重新读取').trigger('click'); await flushPromises()
    expect(wrapper.get('input[maxlength="120"]').element.value).toBe('作者新名称')
    expect(wrapper.text()).not.toContain('类型已保存。')
  })

  it('归档明确二次确认，发送原修订和confirmed=true', async () => {
    const wrapper = await open(); await selectFirst(wrapper)
    api.world.archiveVocabularyTerm.mockResolvedValue(term({ status: 'archived', revision_id: 'revision-2' }))
    await button(wrapper, '归档类型').trigger('click'); await flushPromises()
    expect(confirmAction).toHaveBeenCalled()
    expect(api.world.archiveVocabularyTerm).toHaveBeenCalledWith('novel-1', 'type-1', { expected_revision_id: 'revision-1', confirmed: true })
    expect(wrapper.text()).toContain('类型已归档，可以恢复。')
    expect(button(wrapper, '恢复类型')).toBeTruthy()
  })

  it('卸载后迟到确认不会提交旧项目操作', async () => {
    let approve
    confirmAction.mockImplementation((message, callback) => { approve = callback })
    const wrapper = await open(); await selectFirst(wrapper)
    await button(wrapper, '归档类型').trigger('click')
    wrapper.unmount(); approve(); await flushPromises()
    expect(api.world.archiveVocabularyTerm).not.toHaveBeenCalled()
  })

  it('合并预览绑定来源和目标两份版本，确认后才提交', async () => {
    api.world.listProjectVocabulary.mockResolvedValue({ items: [term(), term({ id: 'type-2', revision_id: 'revision-2', name: '传送门' })], total_count: 2, omitted_count: 0 })
    const wrapper = await open(); await selectFirst(wrapper)
    const selects = wrapper.findAll('select')
    await selects.at(-1).setValue('type-2')
    api.world.mergeVocabularyTerms.mockResolvedValue(term({ id: 'type-2', revision_id: 'revision-3', name: '传送门' }))
    await button(wrapper, '预览并确认合并').trigger('click'); await flushPromises()
    expect(confirmAction).toHaveBeenCalledWith(expect.stringContaining('星门'), expect.any(Function), '确认合并')
    expect(api.world.mergeVocabularyTerms).toHaveBeenCalledWith('novel-1', { target_id: 'type-2', source_ids: ['type-1'], expected_revision_ids: { 'type-2': 'revision-2', 'type-1': 'revision-1' }, confirmed: true })
  })

  it('拆分保留原类型并独立创建新名称，不复制重名别名', async () => {
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.findAll('input[maxlength="120"]').at(-1).setValue('城市星门')
    api.world.splitVocabularyTerm.mockResolvedValue({ retained: term(), split_off: term({ id: 'new-type', name: '城市星门' }) })
    await button(wrapper, '保留当前类型并拆出新类型').trigger('click'); await flushPromises()
    expect(confirmAction).toHaveBeenCalledWith(expect.stringContaining('城市星门'), expect.any(Function), '确认拆分')
    expect(api.world.splitVocabularyTerm).toHaveBeenCalledWith('novel-1', 'type-1', expect.objectContaining({ expected_revision_id: 'revision-1', retained: expect.objectContaining({ name: '星门' }), split_off: expect.objectContaining({ name: '城市星门', aliases: [] }) }))
    expect(wrapper.get('input[maxlength="120"]').element.value).toBe('城市星门')
  })

  it('拆分确认前不提交，确认期间锁定编辑和重复操作', async () => {
    let approve
    confirmAction.mockImplementation((message, callback) => { approve = callback })
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.findAll('input[maxlength="120"]').at(-1).setValue('城市星门')
    api.world.splitVocabularyTerm.mockResolvedValue({ split_off: term({ id: 'new-type', name: '城市星门' }) })
    await button(wrapper, '保留当前类型并拆出新类型').trigger('click'); await flushPromises()
    expect(api.world.splitVocabularyTerm).not.toHaveBeenCalled()
    expect(wrapper.get('form fieldset').element.disabled).toBe(true)
    expect(button(wrapper, '保留当前类型并拆出新类型').element.disabled).toBe(true)
    expect(wrapper.emitted('state').at(-1)[0].busy).toBe(true)
    approve(); await flushPromises()
    expect(api.world.splitVocabularyTerm).toHaveBeenCalledTimes(1)
  })

  it('切项目后忽略迟到保存回执，也不向新项目提交旧确认', async () => {
    let resolve, approve
    const wrapper = await open(); await selectFirst(wrapper)
    await wrapper.get('input[maxlength="120"]').setValue('旧项目改名')
    api.world.updateVocabularyTerm.mockImplementation(() => new Promise(done => { resolve = done }))
    await wrapper.get('form').trigger('submit')
    api.world.listProjectVocabulary.mockResolvedValue({ items: [term({ name: '新项目类型' })], total_count: 1, omitted_count: 0 })
    await wrapper.setProps({ projectId: 'novel-2' }); await flushPromises()
    resolve(term({ name: '旧项目改名' })); await flushPromises()
    expect(wrapper.text()).not.toContain('旧项目改名')
    expect(wrapper.text()).not.toContain('类型已保存。')
    await selectFirst(wrapper)
    confirmAction.mockImplementation((message, callback) => { approve = callback })
    await button(wrapper, '归档类型').trigger('click')
    await wrapper.setProps({ projectId: 'novel-3' }); await flushPromises()
    approve(); await flushPromises()
    expect(api.world.archiveVocabularyTerm).not.toHaveBeenCalled()
  })

  it('预设可以混搭并报告真实新增/重复计数', async () => {
    const wrapper = await open()
    await wrapper.get('input[value="xianxia"]').setValue(true)
    await wrapper.get('input[value="urban"]').setValue(true)
    api.world.applyVocabularyPresets.mockResolvedValue({ applied: 3, already_applied: 2, duplicate_skipped: 1, items: [] })
    await button(wrapper, '添加预设').trigger('click'); await flushPromises()
    expect(api.world.applyVocabularyPresets).toHaveBeenCalledWith('novel-1', { preset_ids: ['xianxia', 'urban'] })
    expect(wrapper.text()).toContain('新增 3 项，已添加 2 项，重名跳过 1 项')
  })
})
