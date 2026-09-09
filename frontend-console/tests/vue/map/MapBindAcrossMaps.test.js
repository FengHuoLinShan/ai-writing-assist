import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MapBindAcrossMaps from '../../../vue/views/map/MapBindAcrossMaps.vue'
import { emptyMap } from '../../../vue/views/map/mapStructureEditor.js'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
afterEach(resetBridgeOverrides)
it('只修改明确选择的图元，版本冲突保留选择并允许重新核对', async () => {
  const document = emptyMap()
  document.features.push({ id: 'home', kind: 'location', label: '住宅', entity_id: null, points: [{ x: 1, y: 1 }], sources: [] })
  const saveMapRevision = vi.fn().mockRejectedValueOnce(new Error('地图版本已更新'))
  setBridgeOverrides({ state: { currentProjectId: 'p1' }, api: { world: {
    getNodeMap: vi.fn(async () => ({ revision: { id: 'revision-1', document } })), saveMapRevision,
  } } })
  const wrapper = mount(MapBindAcrossMaps, { props: { projectId: 'p1', nodeId: 'city', entityId: 'entity-home', entityName: '住宅', nodes: [{ id: 'city', title: '城市' }, { id: 'street', parent_id: 'city', title: '街道' }] } })
  wrapper.get('details').element.open = true
  await wrapper.get('button').trigger('click'); await flushPromises()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('button.btn-primary').trigger('click'); await flushPromises()
  expect(saveMapRevision).toHaveBeenCalledWith('p1', 'street', expect.objectContaining({ base_revision_id: 'revision-1', document: expect.objectContaining({ features: [expect.objectContaining({ entity_id: 'entity-home' })] }) }))
  expect(wrapper.text()).toContain('地图版本已更新')
  expect(wrapper.get('input').element.checked).toBe(true)
  expect(document.features[0].entity_id).toBeNull()
  wrapper.unmount()
})
