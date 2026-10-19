import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
import WorldRelationMaintenance from '../../../vue/views/world/library/WorldRelationMaintenance.vue'

enableAutoUnmount(afterEach)
afterEach(() => { resetBridgeOverrides(); localStorage.clear() })
const current = { source_id: 'a', target_id: 'b', description: '原描述', status: 'canonical', strength: .5, validity: null }
const record = { id: 'record', action: 'remove', before: current, created_at: '2026-10-18T00:00:00Z' }
const response = { current, current_version: 'original', items: [], has_more: false }
async function open(wrapper) { wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle'); await flushPromises() }

it('previews a removal, requires an explicit confirmation and replays the same unknown execution', async () => {
  const relationChangeHistory = vi.fn().mockResolvedValue(response)
  const previewRelationChange = vi.fn().mockResolvedValue({ preview_hash: 'f'.repeat(64), preview: { title: '沈砚 → 船医', before: current, after: { ...current, status: 'deprecated' }, action: 'remove' } })
  const confirmRelationChange = vi.fn().mockRejectedValueOnce(new Error('断线，结果待核对')).mockResolvedValue({ action: 'remove', label: '已移除关系，历史仍保留' })
  setBridgeOverrides({ currentAccount: { id: 'author' }, api: { world: { relationChangeHistory, previewRelationChange, confirmRelationChange }, outline: { listScenesOrdered: vi.fn().mockResolvedValue([]) } } })
  let wrapper = mount(WorldRelationMaintenance, { props: { projectId: 'p', relation: { id: 'r' } } })
  await open(wrapper)
  await wrapper.get('select').setValue('remove')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(confirmRelationChange).not.toHaveBeenCalled()
  await wrapper.findAll('button').find(button => button.text() === '本人确认移除').trigger('click'); await flushPromises()
  const original = JSON.parse(JSON.stringify(confirmRelationChange.mock.calls[0][2]))
  expect(original).toMatchObject({ relation_id: 'r', action: 'remove', confirmed: true, expected_preview_hash: 'f'.repeat(64) })
  wrapper.unmount()
  wrapper = mount(WorldRelationMaintenance, { props: { projectId: 'p', relation: { id: 'r' } } })
  await wrapper.findAll('button').find(button => button.text() === '核对上次执行结果').trigger('click'); await flushPromises()
  expect(confirmRelationChange.mock.calls[1][2]).toEqual(original)
  expect(wrapper.emitted('changed').at(-1)[0].action).toBe('remove')
  expect(wrapper.text()).toContain('原回执已保留')
})

it('restores only the chosen server record and discards another project response', async () => {
  const relationChangeHistory = vi.fn().mockResolvedValue({ ...response, items: [record] })
  let resolve
  const previewRelationChange = vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done }))
  setBridgeOverrides({ api: { world: { relationChangeHistory, previewRelationChange }, outline: { listScenesOrdered: vi.fn().mockResolvedValue([]) } } })
  const wrapper = mount(WorldRelationMaintenance, { props: { projectId: 'p', relation: { id: 'r' } } })
  await open(wrapper)
  await wrapper.findAll('button').find(button => button.text() === '比较并恢复到这次修改前').trigger('click')
  expect(previewRelationChange).toHaveBeenCalledWith('r', 'p', { relation_id: 'r', action: 'restore', history_id: 'record' })
  await wrapper.setProps({ projectId: 'other', relation: { id: 'other' } })
  resolve({ preview_hash: 'old', preview: { title: '旧作品关系' } }); await flushPromises()
  expect(wrapper.text()).not.toContain('旧作品关系')
  expect(wrapper.find('[aria-label="关系修改预览"]').exists()).toBe(false)
})
