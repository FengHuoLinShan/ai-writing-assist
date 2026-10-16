import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapColdStartPanel from '../../../vue/views/map/MapColdStartPanel.vue'
import ReadingFlow from '../../../vue/components/ReadingFlow.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
enableAutoUnmount(afterEach)
let api
const view = (step, panel = {}) => ({ run_id: 'flow-map', flow_id: 'map_cold_start', title: '建立可用地图', status: step === 'usable' ? 'completed' : 'waiting_approval', steps: [{ step_id: step, title: step, state: 'active' }], stop: step === 'usable' ? null : { step_id: step, reason: '合成停点', actions: [{ action: 'open_map', label: '前往工作台' }] }, panel })
const button = (wrapper, text) => wrapper.findAll('button').find(item => item.text() === text)
async function open(wrapper) { wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle'); await flushPromises() }
beforeEach(() => {
  sessionStorage.clear()
  api = { assistant: { guidedFlowLatest: vi.fn(async () => null), guidedFlowStart: vi.fn(async () => view('scope')), guidedFlowAdvance: vi.fn(), guidedFlowAbandon: vi.fn(async () => ({ status: 'cancelled' })) }, evolution: { status: vi.fn(async () => ({ engine: { engine: 'evolution' }, default_budget_mode: 'confirmed_scope', run: null })), start: vi.fn(), spatialRescanStart: vi.fn() } }
  setBridgeOverrides({ api, router: { navigate: vi.fn() } })
})
afterEach(resetBridgeOverrides)

it('地图入口启动自身流程，准备预览不会授权，作者授权后按原运行绑定', async () => {
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p', disabled: true } })
  await open(wrapper)
  await wrapper.setProps({ disabled: false })
  expect(api.assistant.guidedFlowLatest).toHaveBeenCalledWith('p', 'map_cold_start')
  await button(wrapper, '开始地图引导').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowStart).toHaveBeenCalledWith({ novel_id: 'p', flow_id: 'map_cold_start' })
  api.assistant.guidedFlowAdvance.mockImplementationOnce(async (_id, body) => view('authorization', { capability: body.choice.capability, arguments: body.choice.arguments, preview: { authorization_preview: { fingerprint: 'f'.repeat(64), model: 'synthetic', budget_mode: 'confirmed_scope' } } }))
  await wrapper.get('form').trigger('submit'); await flushPromises()
  const choice = api.assistant.guidedFlowAdvance.mock.calls[0][1].choice
  expect(choice).toMatchObject({ step_id: 'scope', action: 'prepare_preview', capability: 'evolution.prepare_spatial_reading', arguments: { discover_spatial: true, end_chapter: 1, request_limit: null } })
  expect(api.evolution.start).not.toHaveBeenCalled()
  api.evolution.start.mockResolvedValue({})
  api.assistant.guidedFlowAdvance.mockResolvedValueOnce(view('monitor', { progress: { status: 'running' } }))
  await button(wrapper, '确认此范围与费用并启动演化').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith('flow-map', { novel_id: 'p', choice: { step_id: 'authorization', action: 'bind_authorized_run', run_key: 'reading-' + choice.arguments.operation_id } })
  expect(wrapper.text()).toContain('演化正在处理')
  expect(wrapper.findComponent(ReadingFlow).exists()).toBe(false)
})

it('unknown只刷新领域状态，review可进入托盘，locations由作者完成', async () => {
  api.assistant.guidedFlowLatest.mockResolvedValue(view('monitor', { progress: { status: 'needs_reconciliation' } }))
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p' } })
  await open(wrapper)
  expect(wrapper.text()).toContain('不会重发')
  api.assistant.guidedFlowAdvance.mockResolvedValueOnce(view('review', { batch_limit: 20, drafts: { candidate_count: 1, saved_node_count: 0, truncated: true } }))
  await button(wrapper, '刷新地图引导进度').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith('flow-map', { novel_id: 'p', choice: { step_id: 'monitor', action: 'refresh' } })
  await button(wrapper, '前往草图审核').trigger('click')
  expect(wrapper.emitted('review')).toHaveLength(1)
  api.assistant.guidedFlowAdvance.mockResolvedValueOnce(view('locations'))
  await button(wrapper, '刷新地图引导进度').trigger('click'); await flushPromises()
  api.assistant.guidedFlowAdvance.mockResolvedValueOnce(view('usable'))
  await button(wrapper, '完成地图引导').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowAdvance).toHaveBeenLastCalledWith('flow-map', { novel_id: 'p', choice: { step_id: 'locations', action: 'finish' } })
  expect(wrapper.text()).toContain('已完成')
  expect(api.evolution.start).not.toHaveBeenCalled(); expect(api.evolution.spatialRescanStart).not.toHaveBeenCalled()
})

it('旧项目的读取与启动响应不覆盖新项目，未就绪和失败可重试', async () => {
  let resolve
  api.assistant.guidedFlowLatest.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'old' } })
  wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle')
  await wrapper.setProps({ projectId: 'new' })
  resolve(view('authorization', { arguments: { operation_id: 'old' } })); await flushPromises()
  expect(wrapper.findComponent(ReadingFlow).exists()).toBe(false)
  expect(wrapper.get('details').element.open).toBe(false)
  await open(wrapper)
  await button(wrapper, '开始地图引导').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowStart).toHaveBeenLastCalledWith({ novel_id: 'new', flow_id: 'map_cold_start' })
})

it('补扫选择沿用实际旧运行并将作者场次转换为零起始范围', async () => {
  api.evolution.status.mockResolvedValue({ engine: { engine: 'evolution' }, run: { run_key: 'original-run', status: 'completed', completed_scenes: 5, end_chapter: 2, budget_mode: 'bounded' } })
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p' } })
  await open(wrapper)
  await button(wrapper, '开始地图引导').trigger('click'); await flushPromises()
  await wrapper.get('select').setValue('rescan')
  const fields = wrapper.findAll('input')
  await fields[0].setValue('2'); await fields[1].setValue('4')
  api.assistant.guidedFlowAdvance.mockResolvedValue(view('authorization', { capability: 'evolution.prepare_spatial_rescan', arguments: { operation_id: 'rescan', run_key: 'original-run' }, preview: { authorization_preview: {} } }))
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(api.assistant.guidedFlowAdvance.mock.calls[0][1].choice).toMatchObject({ action: 'prepare_preview', capability: 'evolution.prepare_spatial_rescan', arguments: { run_key: 'original-run', from_scene_index: 1, through_scene_index: 3, request_limit: 20 } })
  expect(api.evolution.spatialRescanStart).not.toHaveBeenCalled()
})

it('详情展开事件晚到时入口等待领域状态，读取期间不会吞掉启动点击', async () => {
  let resolve
  api.evolution.status.mockReturnValueOnce(new Promise(done => { resolve = done }))
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p' } })
  expect(button(wrapper, '开始地图引导').element.disabled).toBe(true)
  wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle')
  expect(button(wrapper, '开始地图引导').element.disabled).toBe(true)
  resolve({ engine: { engine: 'evolution' }, run: null }); await flushPromises()
  expect(button(wrapper, '开始地图引导').element.disabled).toBe(false)
  await button(wrapper, '开始地图引导').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowStart).toHaveBeenCalledTimes(1)
})

it('勾选地点后结束引导会释放待处理状态，地图工作台可以继续使用', async () => {
  api.assistant.guidedFlowLatest.mockResolvedValue(view('locations', { candidate_locations: [{ entity_id: 'place', name: '渡口', status: 'candidate' }] }))
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p' } })
  await open(wrapper)
  await wrapper.get('input[type="checkbox"]').setValue(true)
  expect(wrapper.emitted('state').at(-1)[0].dirty).toBe(true)
  await button(wrapper, '结束本次引导').trigger('click'); await flushPromises()
  expect(api.assistant.guidedFlowAbandon).toHaveBeenCalledWith('p', 'flow-map')
  expect(wrapper.emitted('state').at(-1)[0]).toEqual({ dirty: false, busy: false })
  expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
})

// Map-series review regressions (T-20261016-map-series-claude-review). it.fails
// mirrors a strict xfail: once fixed it passes and fails this run, so drop .fails.
async function prepareDefaultScope(run) {
  api.evolution.status.mockResolvedValue({ engine: { engine: 'evolution' }, run })
  api.assistant.guidedFlowAdvance.mockResolvedValue(view('scope'))
  const wrapper = mount(MapColdStartPanel, { props: { projectId: 'p' } })
  await open(wrapper)
  await button(wrapper, '开始地图引导').trigger('click'); await flushPromises()
  const submit = button(wrapper, '预览空间范围与费用')?.element
  if (submit && !submit.disabled && !submit.closest('fieldset')?.disabled) { await wrapper.get('form').trigger('submit'); await flushPromises() }
  return api.assistant.guidedFlowAdvance.mock.calls.map(([, body]) => body.choice.arguments || {})
}

for (const status of ['running', 'needs_reconciliation']) {
  it.fails(`B5-F2: 最新阅读为 ${status} 时，冷启动不另起从第 1 章重读的新阅读`, async () => {
    const prepared = await prepareDefaultScope({ run_key: 'current-run', status, completed_scenes: 2, total_scenes: 5, end_chapter: 3, budget_mode: 'bounded', spatial_discovery_enabled: true })
    // ReadingFlow offers a new reading only for settled runs (canStart) and the
    // backend has no single-active-run gate, so the guide must not bypass it.
    expect(prepared.filter(item => item.mode === 'bootstrap')).toEqual([])
  })
}

it.fails('B5-F3: 未开空间发现的已完成阅读，默认选项不提交必被拒绝的空间追加', async () => {
  const prepared = await prepareDefaultScope({ run_key: 'old-run', status: 'completed', completed_scenes: 5, total_scenes: 5, end_chapter: 2, budget_mode: 'bounded', spatial_discovery_enabled: false })
  // workflow._plan rejects append that switches spatial discovery on
  // (追加章节不能静默启用或关闭空间发现); the read range needs a spatial rescan.
  expect(prepared.filter(item => item.mode === 'append' && item.discover_spatial)).toEqual([])
})
