import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import WritingRevisionGroups from '../../../vue/views/writing/components/WritingRevisionGroups.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
afterEach(() => { resetBridgeOverrides(); localStorage.clear() })
const preview = { preview_hash: 'a'.repeat(64), groups: [{ id: 'first', changes: [{ before: '甲😀乙', after: '甲🙂乙' }] }, { id: 'second', changes: [{ before: '后文', after: '新后文' }] }] }
async function open(wrapper) { wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle'); await flushPromises() }

it('freezes the selected groups, retains an unknown submission key and recovers its actual result', async () => {
  const selectRevisionGroups = vi.fn().mockRejectedValueOnce(new Error('断线，结果未知')).mockResolvedValueOnce({ task_id: 'task-1', status: 'pending' })
  const revisionGroups = vi.fn().mockResolvedValue(preview)
  const get = vi.fn().mockResolvedValue({ status: 'done', result: { candidate_draft_id: 'new-candidate' } })
  setBridgeOverrides({ currentAccount: { id: 'author' }, api: { writing: { revisionGroups, selectRevisionGroups }, tasks: { get } } })
  let wrapper = mount(WritingRevisionGroups, { props: { projectId: 'p', draftId: 'candidate' } })
  await open(wrapper)
  await wrapper.findAll('input')[0].setValue(false)
  expect(wrapper.emitted('selection-change').at(-1)).toEqual([true])
  await wrapper.findAll('button').find(b => b.text() === '组成新候选并重新审查').trigger('click'); await flushPromises()
  const submitted = JSON.parse(JSON.stringify(selectRevisionGroups.mock.calls[0][1]))
  expect(submitted.group_ids).toEqual(['second'])
  expect(submitted.expected_preview_hash).toBe(preview.preview_hash)
  wrapper.unmount()
  wrapper = mount(WritingRevisionGroups, { props: { projectId: 'p', draftId: 'candidate' } })
  await open(wrapper)
  await wrapper.findAll('button').find(b => b.text().includes('核对上次提交')).trigger('click'); await flushPromises()
  expect(selectRevisionGroups.mock.calls[1][1]).toEqual(submitted)
  expect(get).toHaveBeenCalledWith('task-1', 'p')
  expect(wrapper.text()).toContain('打开后核对实际审查结论')
  await wrapper.findAll('button').find(b => b.text() === '打开新候选比较与采用').trigger('click')
  expect(wrapper.emitted('open-candidate')).toEqual([['new-candidate']])
  expect(Object.values(localStorage).join('')).not.toContain('甲😀乙')
})

it('does not expose a late group response from another project and reports unavailable backups', async () => {
  let resolve
  const revisionGroups = vi.fn().mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValue(preview)
  const brokenStorage = { getItem: () => null, setItem: () => { throw new Error('full') } }
  setBridgeOverrides({ currentAccount: { id: 'author' }, localDraftStorage: brokenStorage, api: { writing: { revisionGroups } } })
  const wrapper = mount(WritingRevisionGroups, { props: { projectId: 'old', draftId: 'old' } })
  wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle')
  await wrapper.setProps({ projectId: 'new', draftId: 'new' })
  resolve({ ...preview, groups: [{ id: 'old', changes: [{ before: '旧作品私稿', after: '旧改动' }] }] }); await flushPromises()
  expect(wrapper.text()).not.toContain('旧作品私稿')
  await open(wrapper)
  await wrapper.findAll('input')[0].setValue(false)
  expect(wrapper.text()).toContain('选择未能备份')
})

it.each(['failed', 'done'])('allows an explicit fresh selection after a verified %s task, including refresh', async status => {
  const revisionGroups = vi.fn().mockResolvedValue(preview)
  const selectRevisionGroups = vi.fn().mockResolvedValueOnce({ task_id: 'first', status: 'pending' }).mockResolvedValueOnce({ task_id: 'second', status: 'pending' })
  const get = vi.fn(async taskId => ({ status: taskId === 'first' ? status : 'running', error_message: status === 'failed' ? '暂时无法连接模型' : null, result: status === 'done' ? { candidate_draft_id: 'derived' } : {} }))
  setBridgeOverrides({ currentAccount: { id: 'author' }, api: { writing: { revisionGroups, selectRevisionGroups }, tasks: { get } } })
  let wrapper = mount(WritingRevisionGroups, { props: { projectId: 'p', draftId: 'candidate' } })
  await open(wrapper)
  await wrapper.findAll('button').find(button => button.text() === '组成新候选并重新审查').trigger('click')
  await flushPromises()
  const firstRequest = selectRevisionGroups.mock.calls[0][1]
  wrapper.unmount()
  wrapper = mount(WritingRevisionGroups, { props: { projectId: 'p', draftId: 'candidate' } })
  await open(wrapper)
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  await wrapper.findAll('button').find(button => button.text() === '重新选择修改组').trigger('click')
  await flushPromises()
  expect(wrapper.get('fieldset').attributes('disabled')).toBeUndefined()
  expect(get).toHaveBeenCalledWith('first', 'p')
  expect(selectRevisionGroups).toHaveBeenCalledTimes(1)
  await wrapper.findAll('input')[0].setValue(false)
  await wrapper.findAll('button').find(button => button.text() === '组成新候选并重新审查').trigger('click')
  await flushPromises()
  const secondRequest = selectRevisionGroups.mock.calls[1][1]
  expect(secondRequest.operation_id).not.toBe(firstRequest.operation_id)
  expect(secondRequest.group_ids).toEqual(['second'])
  expect(revisionGroups).toHaveBeenCalledTimes(3)
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
})

it.each([
  { status: 'running' },
  { status: 'failed', operation: { possible_charge: true } },
  { status: 'failed', lifecycle: { recovery_required: true } },
])('keeps pending or unknown task outcomes locked: %j', async outcome => {
  const selectRevisionGroups = vi.fn().mockResolvedValue({ task_id: 'first', status: 'pending' })
  setBridgeOverrides({ currentAccount: { id: 'author' }, api: { writing: { revisionGroups: vi.fn().mockResolvedValue(preview), selectRevisionGroups }, tasks: { get: vi.fn().mockResolvedValue(outcome) } } })
  const wrapper = mount(WritingRevisionGroups, { props: { projectId: 'p', draftId: 'candidate' } })
  await open(wrapper)
  await wrapper.findAll('button').find(button => button.text() === '组成新候选并重新审查').trigger('click')
  await flushPromises()
  expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
  expect(wrapper.findAll('button').some(button => button.text() === '重新选择修改组')).toBe(false)
  expect(selectRevisionGroups).toHaveBeenCalledTimes(1)
})
