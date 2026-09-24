import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MapScenePanel from '../../../vue/views/map/MapScenePanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })
const props = { projectId: 'book', nodeId: 'map', revisionId: 'revision' }
const scenes = [{ id: 's1', scene_index: 0, title: '重逢', status: 'draft' }, { id: 's2', scene_index: 1, title: '渡口', status: 'canonical' }]
const context = { map_revision: 'revision', freshness: 'current', presence_items: [
  { character_id: 'lin', character_name: '林舟', presence_kind: 'confirmed_in_scene', location: '渡口', feature_id: 'ferry', source_receipt: { chapter_index: 2 } },
  { character_id: 'qing', character_name: '青竹', presence_kind: 'last_observed', location: '白石城', scene_index: 0, source_receipt: {} },
  { character_id: 'unknown', character_name: '未出场的人', presence_kind: 'unknown', source_receipt: {} },
], history: [{ character_name: '林舟', scene_index: 0, location: '白石城' }], routes: [{ character_id: 'lin', from_location: '白石城', to_location: '渡口', status: 'unknown' }], omissions: [] }
async function open(wrapper) { wrapper.get('details').element.open = true; await wrapper.get('details').trigger('toggle'); await flushPromises() }

it('按场景加载位置，保留最后出现与未知路线语义，并回到实际地图地点和正文', async () => {
  const getMapSceneContext = vi.fn().mockResolvedValue(context)
  const listScenesOrdered = vi.fn().mockResolvedValue(scenes)
  setBridgeOverrides({ api: { world: { getMapSceneContext }, outline: { listScenesOrdered } } })
  const wrapper = mount(MapScenePanel, { props })
  expect(listScenesOrdered).not.toHaveBeenCalled()
  await open(wrapper)
  await wrapper.get('select').setValue('s2'); await flushPromises()
  expect(getMapSceneContext).toHaveBeenCalledExactlyOnceWith('book', 'map', 's2')
  expect(wrapper.text()).toContain('本场出现于渡口')
  expect(wrapper.text()).toContain('最后出现于白石城（场景 1）')
  expect(wrapper.text()).toContain('位置未确定')
  expect(wrapper.text()).toContain('中间路线未知')
  await wrapper.findAll('button').find(button => button.text() === '在地图上查看').trigger('click')
  expect(wrapper.emitted('locate')[0]).toEqual(['ferry'])
  await wrapper.findAll('button').find(button => button.text() === '查看第 2 章依据').trigger('click')
  expect(wrapper.emitted('open-source')[0][0].source_ref.chapter_index).toBe(2)
  wrapper.unmount()
})

it('快速切换场景或项目后拒绝晚到结果，地图版本不符时不展示位置', async () => {
  const pending = []
  setBridgeOverrides({ api: { world: { getMapSceneContext: vi.fn(() => new Promise(resolve => pending.push(resolve))) }, outline: { listScenesOrdered: vi.fn().mockResolvedValue(scenes) } } })
  const wrapper = mount(MapScenePanel, { props })
  await open(wrapper)
  await wrapper.get('select').setValue('s1')
  await wrapper.get('select').setValue('s2')
  pending[0](context); await flushPromises()
  expect(wrapper.text()).not.toContain('林舟')
  pending[1]({ ...context, map_revision: 'new-revision' }); await flushPromises()
  expect(wrapper.text()).toContain('地图已有新版本')
  expect(wrapper.text()).not.toContain('林舟')
  await wrapper.get('select').setValue('s1')
  await wrapper.setProps({ projectId: 'another-book' })
  pending[2](context); await flushPromises()
  expect(wrapper.text()).not.toContain('林舟')
  expect(wrapper.findAll('option')).toHaveLength(3)
  await wrapper.setProps({ revisionId: 'next-map' }); await flushPromises()
  expect(wrapper.findAll('option')).toHaveLength(3)
  wrapper.unmount()
})
