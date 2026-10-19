import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
import WorldReviewScope from '../../../vue/views/world/components/WorldReviewScope.vue'

enableAutoUnmount(afterEach)
afterEach(() => { resetBridgeOverrides(); localStorage.clear() })
const page = { id: 'scope', revision: 1, total: 21, checked: 0, deferred: 0, stale: 0, remaining: 21, skip: 0, limit: 20, has_more: true,
  items: [{ entity_id: 'a', name: '沈砚', updated_at: 'v1', disposition: 'pending', stale: false }] }
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text() === text)
async function open(wrapper) { wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle'); await flushPromises() }

it('freezes all matching objects, recovers the same lost request and saves explicit human progress', async () => {
  const freezeEntityReviewScope = vi.fn().mockRejectedValueOnce(new Error('结果未知')).mockResolvedValue(page)
  const recentEntityReviewScopes = vi.fn().mockResolvedValue([])
  const entityReviewScope = vi.fn().mockResolvedValue({ ...page, revision: 2, checked: 1, remaining: 20 })
  const decideEntityReviewScope = vi.fn().mockResolvedValue({ revision: 2 })
  const navigate = vi.fn()
  setBridgeOverrides({ currentAccount: { id: 'author' }, router: { navigate }, api: { world: { freezeEntityReviewScope, recentEntityReviewScopes, entityReviewScope, decideEntityReviewScope } } })
  let wrapper = mount(WorldReviewScope, { props: { projectId: 'p', filters: { q: '沈', display_state: 'active', skip: 20, limit: 20 } } })
  await open(wrapper); await button(wrapper, '冻结当前筛选结果').trigger('click'); await flushPromises()
  const request = freezeEntityReviewScope.mock.calls[0][1]
  expect(request.filters).toEqual({ q: '沈', display_state: 'active' })
  wrapper.unmount()
  wrapper = mount(WorldReviewScope, { props: { projectId: 'p', filters: { q: '另一个筛选' } } })
  await open(wrapper); await button(wrapper, '核对上次冻结结果').trigger('click'); await flushPromises()
  expect(freezeEntityReviewScope.mock.calls[1][1]).toEqual(request)
  expect(wrapper.text()).toContain('冻结 21 项')
  expect(decideEntityReviewScope).not.toHaveBeenCalled()
  await button(wrapper, '我已核对本页').trigger('click'); await flushPromises()
  expect(decideEntityReviewScope).toHaveBeenCalledWith('p', 'scope', { expected_revision: 1, entity_ids: ['a'], disposition: 'checked' })
  expect(wrapper.text()).toContain('人工已核对 1')
  await button(wrapper, '沈砚 · 打开核对').trigger('click')
  expect(navigate).toHaveBeenCalledWith('world', 'bible', true, new URLSearchParams({ entity_id: 'a' }))
  await button(wrapper, '下一页').trigger('click'); await flushPromises()
  expect(entityReviewScope).toHaveBeenLastCalledWith('p', 'scope', 20)
})

it('cannot silently freeze a changing hot category, mark stale objects or show late data from another project', async () => {
  let resolve
  const freezeEntityReviewScope = vi.fn().mockImplementation(() => new Promise(done => { resolve = done }))
  setBridgeOverrides({ currentAccount: { id: 'author' }, api: { world: {
    freezeEntityReviewScope, recentEntityReviewScopes: vi.fn().mockResolvedValue([]),
    entityReviewScope: vi.fn().mockResolvedValue({ ...page, stale: 1, items: [{ ...page.items[0], stale: true }] }),
  } } })
  const wrapper = mount(WorldReviewScope, { props: { projectId: 'p', filters: { focus: 'hot' } } })
  await open(wrapper); await button(wrapper, '冻结当前筛选结果').trigger('click'); await flushPromises()
  expect(freezeEntityReviewScope).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('清除热点分类')
  await wrapper.setProps({ filters: {} }); await button(wrapper, '冻结当前筛选结果').trigger('click')
  await wrapper.setProps({ projectId: 'another' })
  resolve(page); await flushPromises()
  expect(wrapper.find('[aria-label="冻结范围与核对进度"]').exists()).toBe(false)
})
