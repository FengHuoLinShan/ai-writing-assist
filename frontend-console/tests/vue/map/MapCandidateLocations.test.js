import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapCandidateLocations from '../../../vue/views/map/MapCandidateLocations.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
const confirmAsync = vi.hoisted(() => vi.fn(async () => true))
vi.mock('../../../shared/confirmAsync.js', () => ({ confirmAsync }))
enableAutoUnmount(afterEach)
const locations = [{ entity_id: 'a', name: '北堡', status: 'candidate', source_hash: 'a'.repeat(64) }, { entity_id: 'b', name: '渡口', status: 'candidate', source_hash: 'b'.repeat(64) }]
let promoteEntity
beforeEach(() => { confirmAsync.mockReset().mockResolvedValue(true); promoteEntity = vi.fn(async () => ({})); setBridgeOverrides({ api: { world: { promoteEntity } } }) })
afterEach(resetBridgeOverrides)

it('候选地点默认不选，不绕世界原采用接口；部分失败保留已成功并阻止地图继续', async () => {
  const wrapper = mount(MapCandidateLocations, { props: { projectId: 'p', locations } })
  expect(wrapper.find('button').exists()).toBe(false)
  for (const input of wrapper.findAll('input')) await input.setValue(true)
  promoteEntity.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('原文前缀已变化'))
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(promoteEntity.mock.calls).toEqual([['a', 'p', { expected_source_hash: 'a'.repeat(64) }], ['b', 'p', { expected_source_hash: 'b'.repeat(64) }]])
  expect(wrapper.text()).toContain('地点“北堡”已采用')
  expect(wrapper.text()).toContain('原文前缀已变化')
  expect(wrapper.emitted('adopted')).toBeUndefined()
  expect(wrapper.emitted('state').at(-1)).toEqual([{ selected: true, busy: false }])
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(promoteEntity.mock.calls).toEqual([['a', 'p', { expected_source_hash: 'a'.repeat(64) }], ['b', 'p', { expected_source_hash: 'b'.repeat(64) }], ['b', 'p', { expected_source_hash: 'b'.repeat(64) }]])
  expect(wrapper.emitted('adopted')).toHaveLength(1)
})

it('作者取消不提交；确认期间换项目不继续提交其余地点或报告成功', async () => {
  const wrapper = mount(MapCandidateLocations, { props: { projectId: 'old', locations } })
  for (const input of wrapper.findAll('input')) await input.setValue(true)
  confirmAsync.mockResolvedValueOnce(false)
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(promoteEntity).not.toHaveBeenCalled()
  let resolve
  promoteEntity.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  await wrapper.get('button').trigger('click'); await flushPromises()
  await wrapper.setProps({ projectId: 'new' })
  resolve({}); await flushPromises()
  expect(promoteEntity).toHaveBeenCalledTimes(1)
  expect(wrapper.emitted('adopted')).toBeUndefined()
})

it('前缀或原World政策阻止采用时保留原因与候选，不提交', () => {
  const wrapper = mount(MapCandidateLocations, { props: { projectId: 'p', locations: [{ ...locations[0], can_adopt: false, block_reason: '旧理解前缀尚未核对' }], truncated: true } })
  expect(wrapper.get('input').element.disabled).toBe(true)
  expect(wrapper.text()).toContain('旧理解前缀尚未核对')
  expect(wrapper.text()).toContain('另有候选地点未列出')
  expect(promoteEntity).not.toHaveBeenCalled()
})

it('内容CAS冲突停止本批，通知宿主重新读取预览而不报告采用成功', async () => {
  const wrapper = mount(MapCandidateLocations, { props: { projectId: 'p', locations } })
  await wrapper.findAll('input')[0].setValue(true)
  promoteEntity.mockRejectedValueOnce(Object.assign(new Error('地点内容已变化'), { status: 409 }))
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(promoteEntity).toHaveBeenCalledExactlyOnceWith('a', 'p', { expected_source_hash: 'a'.repeat(64) })
  expect(wrapper.emitted('adopted')).toBeUndefined()
  expect(wrapper.emitted('stale')[0][0]).toContain('地点内容已变化')
})
