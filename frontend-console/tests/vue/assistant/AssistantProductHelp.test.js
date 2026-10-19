import { afterEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
import AssistantProductHelp from '../../../vue/components/AssistantProductHelp.vue'

enableAutoUnmount(afterEach)
afterEach(resetBridgeOverrides)
it('shows the actual unavailable reason and navigates through a registered destination without a model', async () => {
  const navigate = vi.fn()
  setBridgeOverrides({ router: { navigate } })
  const wrapper = mount(AssistantProductHelp, { props: { guide: { version: 'v1', items: [{ id: 'automatic', title: '当前任务的自动修改', destination: 'world_relations', steps: ['先比较'], condition: '本人确认移除' }] }, automaticAvailability: { available: false, reason: '轻量模型尚未通过实测' } } })
  expect(wrapper.text()).toContain('轻量模型尚未通过实测')
  expect(wrapper.text()).toContain('说明版本：v1')
  await wrapper.get('button').trigger('click')
  expect(navigate).toHaveBeenCalledWith('world', 'relations', true, new URLSearchParams())
})
