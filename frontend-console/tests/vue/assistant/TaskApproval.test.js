import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
import TaskApprovalSettings from '../../../vue/components/TaskApprovalSettings.vue'
import TaskApprovalReceipt from '../../../vue/components/TaskApprovalReceipt.vue'

enableAutoUnmount(afterEach)
afterEach(() => { resetBridgeOverrides(); vi.useRealTimers() })

it('keeps uncalibrated or unbounded tasks manual and emits only explicit task requirements', async () => {
  const wrapper = mount(TaskApprovalSettings, { props: { availability: { available: false, reason: '尚未实测' }, scopeLabel: '沈砚' } })
  expect(wrapper.get('select').element.value).toBe('manual')
  expect(wrapper.get('option[value=automatic]').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('尚未实测')
  await wrapper.setProps({ availability: { available: true }, scopeLabel: '' })
  expect(wrapper.get('option[value=automatic]').element.disabled).toBe(true)
  await wrapper.setProps({ scopeLabel: '第 2 章' })
  await wrapper.get('select').setValue('automatic')
  const value = wrapper.emitted('update:modelValue').at(-1)[0]
  expect(value).toEqual({ preserve: [], max_judgments: 5, timeout_seconds: 30 })
  await wrapper.setProps({ modelValue: value })
  await wrapper.get('textarea').setValue('保留结局\n不改姓名')
  expect(wrapper.emitted('update:modelValue').at(-1)[0].preserve).toEqual(['保留结局', '不改姓名'])
  expect(wrapper.text()).toContain('合并、删除、废弃和发布需要本人确认')
})

it('revokes the exact server grant version while the parent task is running', async () => {
  const value = { status: 'active', version: 3, task: { intent: '只修改简介', preserve: ['保留姓名'] }, decisions: [{ id: 'a', decision: 'pending', reason: '等待模型' }] }
  const taskApproval = vi.fn().mockResolvedValue(value)
  const revokeTaskApproval = vi.fn().mockResolvedValue({ ...value, status: 'revoked', version: 4 })
  setBridgeOverrides({ api: { assistant: { taskApproval, revokeTaskApproval } } })
  const wrapper = mount(TaskApprovalReceipt, { props: { projectId: 'p', runId: 'r', live: true } })
  await flushPromises()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(revokeTaskApproval).toHaveBeenCalledExactlyOnceWith('p', 'r', 3)
  expect(wrapper.text()).toContain('自动修改已撤回')
  expect(wrapper.text()).toContain('保留姓名')
  expect(wrapper.text()).not.toContain('本任务自动修改已开启')
})

it('discards another task response and refreshes a final revision received during loading', async () => {
  let oldResolve, finalResolve
  const taskApproval = vi.fn().mockImplementationOnce(() => new Promise(resolve => { oldResolve = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { finalResolve = resolve }))
    .mockResolvedValue({ status: 'finished', task: { intent: '最终回执' }, decisions: [] })
  setBridgeOverrides({ api: { assistant: { taskApproval } } })
  const wrapper = mount(TaskApprovalReceipt, { props: { projectId: 'old', runId: 'one', revision: 1 } })
  await wrapper.setProps({ projectId: 'new', runId: 'two' })
  oldResolve({ status: 'active', task: { intent: '旧作品内容' } }); await flushPromises()
  expect(wrapper.text()).not.toContain('旧作品内容')
  await wrapper.setProps({ revision: 2 })
  finalResolve({ status: 'active', task: { intent: '尚未完成的回执' } }); await flushPromises()
  expect(taskApproval).toHaveBeenCalledTimes(3)
  expect(wrapper.text()).toContain('最终回执')
  expect(wrapper.text()).toContain('授权已结束')
})
