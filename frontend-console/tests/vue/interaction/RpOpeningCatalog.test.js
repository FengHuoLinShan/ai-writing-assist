import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RpOpeningCatalog from '../../../vue/views/interaction/RpOpeningCatalog.vue'
import { setBridgeOverrides, resetBridgeOverrides } from '../../../vue/bridge/index.js'

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })
it('真实开局卡加载图片并用同一幂等键重试不确定的创建', async () => {
  const navigate = vi.fn()
  const startOpening = vi.fn().mockRejectedValueOnce(new Error('请求超时')).mockResolvedValue({ journey: { id: 'journey' } })
  const fetchOpeningImage = vi.fn().mockResolvedValue(new Blob(['image']))
  setBridgeOverrides({ router: { navigate }, api: { interactions: {
    listOpenings: vi.fn().mockResolvedValue({ items: [{ id: 'opening', title: '旧屋的清晨', description: '从原作角色出发', source_title: '小说', experience_kind: 'source_character', has_image: true, curation: '代理整理' }] }),
    fetchOpeningImage, startOpening,
  } } })
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:portrait')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  let wrapper = mount(RpOpeningCatalog)
  await flushPromises()
  expect(wrapper.get('img').attributes('src')).toBe('blob:portrait')
  expect(fetchOpeningImage).toHaveBeenCalledWith('opening')
  await wrapper.get('.rp-entry-copy button').trigger('click'); await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('请求超时')
  wrapper.unmount()
  wrapper = mount(RpOpeningCatalog)
  await flushPromises()
  await wrapper.get('.rp-entry-copy button').trigger('click'); await flushPromises()
  expect(startOpening.mock.calls[0]).toEqual(startOpening.mock.calls[1])
  expect(navigate).toHaveBeenCalledWith('interaction', 'journey')
  wrapper.unmount(); expect(revoke).toHaveBeenCalledWith('blob:portrait')
})

it('配图版本失效不回退到当前对象图片，模型未连接时禁止进入', async () => {
  const startOpening = vi.fn()
  setBridgeOverrides({ api: { interactions: {
    listOpenings: vi.fn().mockResolvedValue({ items: [{ id: 'opening', title: '地点', description: '探索', source_title: '作品', has_image: true }] }),
    fetchOpeningImage: vi.fn().mockRejectedValue(new Error('图片版本失效')), startOpening,
  } } })
  const wrapper = mount(RpOpeningCatalog, { props: { disabled: true } })
  await flushPromises()
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.text()).toContain('配图版本暂不可用')
  expect(wrapper.get('.rp-entry-copy button').element.disabled).toBe(true)
  expect(startOpening).not.toHaveBeenCalled()
  wrapper.unmount()
})
