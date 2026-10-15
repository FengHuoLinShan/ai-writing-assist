import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapSpatialMetadataPanel from '../../../vue/views/map/MapSpatialMetadataPanel.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
const document = () => ({ schema_version: 2, layout_version: 1, spaces: [{ id: 'main', label: '主空间' }, { id: 'dream', label: '梦境' }], features: [{ id: 'f1', kind: 'location', label: '旧桥', space_id: 'main', points: [{ x: 10, y: 20 }], sources: [], modality: 'event_observed' }], constraints: [], journeys: [], images: [], annotation_bindings: [] })
const terms = [{ id: 'feature-type', revision_id: 'r2', name: '传送阵', kind: 'feature', status: 'active' }, { id: 'inactive-type', revision_id: 'r1', name: '未确认新类型', kind: 'feature', status: 'emerging' }]
let api, confirmAction
beforeEach(() => {
  api = { world: { listProjectVocabulary: vi.fn().mockResolvedValue({ items: terms, omitted_count: 0 }) }, outline: { listScenes: vi.fn().mockResolvedValue({ items: [{ id: 's1', scene_index: 0, title: '入城', status: 'draft' }], total: 1 }) } }
  confirmAction = vi.fn((message, confirm) => confirm())
  setBridgeOverrides({ api, confirmAction })
})
afterEach(resetBridgeOverrides)
async function open(doc = document()) {
  const wrapper = mount(MapSpatialMetadataPanel, { props: { projectId: 'p', document: doc, selectedFeatureId: 'f1' } })
  wrapper.get('details').element.open = true
  await wrapper.get('details').trigger('toggle'); await flushPromises()
  return wrapper
}
const field = (wrapper, label) => wrapper.findAll('label').find(item => item.text().startsWith(label)).find('select')
const changed = wrapper => wrapper.emitted('change').at(-1)[0]
const button = (wrapper, label) => wrapper.findAll('button').find(item => item.text() === label)

describe('地图空间元数据编辑', () => {
  it('懒读取有界场景，明确升级v1且保留原文档', async () => {
    const doc = document(); doc.schema_version = 1; delete doc.spaces; delete doc.journeys
    const wrapper = await open(doc)
    expect(api.outline.listScenes).toHaveBeenCalledWith('p', 0, 50)
    await button(wrapper, '启用空间与时效编辑').trigger('click')
    expect(changed(wrapper).schema_version).toBe(2)
    expect(changed(wrapper).features[0].points).toEqual([{ x: 10, y: 20 }])
    expect(doc.schema_version).toBe(1)
  })
  it('固定类型旧修订保留，只在明确选择后引用新修订', async () => {
    const doc = document(); Object.assign(doc.features[0], { type_ref: 'feature-type', type_revision_id: 'r1' })
    const wrapper = await open(doc)
    expect(field(wrapper, '图元类型').element.value).toBe('feature-type@r1')
    expect(wrapper.emitted('change')).toBeUndefined()
    expect(wrapper.text()).not.toContain('未确认新类型')
    await field(wrapper, '图元类型').setValue('feature-type@r2')
    expect(changed(wrapper).features[0].type_revision_id).toBe('r2')
    await field(wrapper, '图元类型').setValue('')
    expect(changed(wrapper).features[0]).toMatchObject({ type_ref: null, type_revision_id: null })
  })
  it('跨空间移动须确认且清坐标，不修改输入对象', async () => {
    const doc = document(), wrapper = await open(doc)
    await field(wrapper, '所属空间').setValue('dream'); await flushPromises()
    expect(confirmAction).toHaveBeenCalledTimes(1)
    expect(changed(wrapper).features[0]).toMatchObject({ space_id: 'dream', points: [] })
    expect(doc.features[0].points).toHaveLength(1)
  })
  it('校准点与锁定图元不能迁移空间', async () => {
    const doc = document(); doc.images = [{ anchors: [{ feature_id: 'f1' }] }]
    const wrapper = await open(doc)
    await field(wrapper, '所属空间').setValue('dream'); await flushPromises()
    expect(wrapper.text()).toContain('请先解除相关校准')
    expect(wrapper.emitted('change')).toBeUndefined()
    await wrapper.setProps({ document: { ...doc, features: [{ ...doc.features[0], locked: true }] } })
    expect(field(wrapper, '所属空间').attributes('disabled')).toBeDefined()
  })
  it('场景锚点用稳定身份，章节锚点不改写，省略场景保留原值', async () => {
    const doc = document(); doc.features[0].effective = { start: { kind: 'chapter', id: 'chapter-id' }, end: { kind: 'scene', id: 'not-on-page' } }
    const wrapper = await open(doc)
    expect(field(wrapper, '从哪个场景').attributes('disabled')).toBeDefined()
    expect(field(wrapper, '到哪个场景').element.value).toBe('not-on-page')
    await field(wrapper, '到哪个场景').setValue('s1')
    expect(changed(wrapper).features[0].effective).toEqual({ start: { kind: 'chapter', id: 'chapter-id' }, end: { kind: 'scene', id: 's1' } })
  })
  it('新增空间不生成坐标，使用中的空间不能移除', async () => {
    const wrapper = await open()
    await button(wrapper, '新增独立空间').trigger('click')
    expect(changed(wrapper).spaces).toHaveLength(3)
    expect(changed(wrapper).features[0].space_id).toBe('main')
    expect(wrapper.findAll('.space-row button')[0].attributes('disabled')).toBeDefined()
  })
  it('翻页保留当前Scene锚点，单个选项接口失败可重试', async () => {
    api.outline.listScenes.mockResolvedValueOnce({ items: [], total: 55 })
    const wrapper = await open()
    await button(wrapper, '下一页场景').trigger('click'); await flushPromises()
    expect(api.outline.listScenes).toHaveBeenLastCalledWith('p', 50, 50)
    api.world.listProjectVocabulary.mockRejectedValueOnce(new Error('不可用'))
    await wrapper.setProps({ projectId: 'other' })
    await button(wrapper, '重新读取编辑选项').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('部分编辑选项未读取')
    expect(wrapper.emitted('state').at(-1)[0].busy).toBe(false)
  })
})
