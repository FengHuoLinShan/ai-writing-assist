import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import WorldEntityImage from '../../../vue/views/world/components/WorldEntityImage.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })
it('只在上传成功后报告保存，替换失败保留已有图片', async () => {
  URL.createObjectURL = vi.fn(() => 'blob:house')
  URL.revokeObjectURL = vi.fn()
  const uploadEntityImage = vi.fn(async () => ({ has_image: true }))
  const fetchEntityImage = vi.fn(async () => new Blob(['image']))
  setBridgeOverrides({ api: { world: { uploadEntityImage, fetchEntityImage } } })
  const wrapper = mount(WorldEntityImage, { props: { projectId: 'p1', entity: { id: 'house', name: '住宅', has_image: false } } })
  const input = wrapper.get('input')
  Object.defineProperty(input.element, 'files', { value: [new File(['png'], 'house.png', { type: 'image/png' })], configurable: true })
  await input.trigger('change'); await flushPromises()
  expect(wrapper.text()).toContain('图片已保存')
  expect(wrapper.get('img').attributes('src')).toBe('blob:house')
  uploadEntityImage.mockRejectedValueOnce(new Error('保存失败'))
  await input.trigger('change'); await flushPromises()
  expect(wrapper.text()).toContain('保存失败')
  expect(wrapper.text()).not.toContain('图片已保存')
  expect(wrapper.get('img').attributes('src')).toBe('blob:house')
  wrapper.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:house')
})
