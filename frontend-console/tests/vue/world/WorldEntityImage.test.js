import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import WorldEntityImage from '../../../vue/views/world/components/WorldEntityImage.vue'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'
import { projectSettingsSession } from '../../../vue/views/settings/projectSettingsSession.js'

enableAutoUnmount(afterEach)

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

describe('本机 CLI 生图', () => {
  let world, localAgent, router

  beforeEach(() => {
    vi.useFakeTimers()
    let blobCounter = 0
    URL.createObjectURL = vi.fn(() => `blob:candidate-${++blobCounter}`)
    URL.revokeObjectURL = vi.fn()
    world = {
      fetchEntityImage: vi.fn(async () => new Blob(['image'])),
      uploadEntityImage: vi.fn(),
      imageGeneration: vi.fn(async () => ({
        available: true, reason: null, executor_kind: 'codex', default_prompt: '一位身穿铠甲的骑士', candidates: [],
      })),
      createImageCandidate: vi.fn(async () => ({
        id: 'cand-1', entity_id: 'house', status: 'queued', prompt: '一位身穿铠甲的骑士', error: null,
        width: null, height: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
        task_id: 'task-1', awaiting_approval: true,
      })),
      imageCandidate: vi.fn(),
      fetchImageCandidateImage: vi.fn(async () => new Blob(['candidate-image'])),
      adoptImageCandidate: vi.fn(async () => ({ candidate: {}, image_version: 'v2' })),
      discardImageCandidate: vi.fn(async () => ({ status: 'discarded' })),
    }
    localAgent = { pending: vi.fn(async () => ({ items: [] })), approve: vi.fn(async () => ({})) }
    router = { navigate: vi.fn() }
    setBridgeOverrides({ api: { world, localAgent }, router })
    projectSettingsSession.tab = 'author'
  })

  afterEach(() => { vi.useRealTimers() })

  function mountWidget(entity = { id: 'house', name: '骑士堡', has_image: false }) {
    return mount(WorldEntityImage, { props: { projectId: 'p1', entity } })
  }

  it('不可用时展示原因并可前往作品设置', async () => {
    world.imageGeneration.mockResolvedValue({ available: false, reason: '本机 CLI 尚未配对', executor_kind: null, default_prompt: '', candidates: [] })
    const wrapper = mountWidget()
    await wrapper.get('button.btn-ghost').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('本机 CLI 尚未配对')
    await wrapper.findAll('button').find((btn) => btn.text() === '去作品设置配置').trigger('click')
    expect(projectSettingsSession.tab).toBe('ai')
    expect(router.navigate).toHaveBeenCalledWith('project-settings')
  })

  it('完整流程：生成候选、等待授权、轮询到可查看、采用后刷新图片', async () => {
    localAgent.pending.mockResolvedValue({ items: [{ task_id: 'task-1', label: '对象图片生成' }] })
    world.imageCandidate.mockResolvedValueOnce({
      id: 'cand-1', entity_id: 'house', status: 'generating', prompt: '一位身穿铠甲的骑士', error: null,
      width: null, height: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
      task_id: 'task-1', awaiting_approval: false,
    }).mockResolvedValueOnce({
      id: 'cand-1', entity_id: 'house', status: 'review_ready', prompt: '一位身穿铠甲的骑士', error: null,
      width: 512, height: 512, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:02Z',
      task_id: 'task-1', awaiting_approval: false,
    })

    const wrapper = mountWidget()
    await wrapper.get('button.btn-ghost').trigger('click')
    await flushPromises()
    expect(wrapper.get('textarea').element.value).toBe('一位身穿铠甲的骑士')

    await wrapper.findAll('button').find((btn) => btn.text() === '开始生成').trigger('click')
    await flushPromises()
    expect(world.createImageCandidate).toHaveBeenCalledWith('house', 'p1', '一位身穿铠甲的骑士', false)
    expect(wrapper.text()).toContain('请确认本机伴随程序正在运行')

    await wrapper.get('input[type="checkbox"]').setValue(true)
    await wrapper.findAll('button').find((btn) => btn.text() === '允许本次生成').trigger('click')
    await flushPromises()
    expect(localAgent.approve).toHaveBeenCalledWith('p1', 'task-1')

    vi.advanceTimersByTime(3000); await flushPromises()
    expect(wrapper.text()).toContain('正在生成')

    vi.advanceTimersByTime(3000); await flushPromises()
    expect(world.fetchImageCandidateImage).toHaveBeenCalledWith('cand-1', 'p1')
    const previewImg = wrapper.findAll('img').find((img) => img.attributes('alt') === '生成的候选图片')
    expect(previewImg).toBeTruthy()

    await wrapper.findAll('button').find((btn) => btn.text() === '采用这张').trigger('click')
    await flushPromises()
    expect(world.adoptImageCandidate).toHaveBeenCalledWith('cand-1', 'p1')
    expect(wrapper.text()).toContain('图片已保存')
    expect(world.fetchEntityImage).toHaveBeenCalled()
  })

  it('生成中收到 409 时展示提示', async () => {
    const err = new Error('冲突')
    err.status = 409
    err.body = { error: 'image_generation_in_progress', detail: '已有图片正在生成', message: '已有图片正在生成' }
    world.createImageCandidate.mockRejectedValue(err)
    const wrapper = mountWidget()
    await wrapper.get('button.btn-ghost').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((btn) => btn.text() === '开始生成').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已有一张图片正在生成')
  })

  it('生成失败后展示错误并允许重新生成', async () => {
    world.imageCandidate.mockResolvedValue({
      id: 'cand-1', entity_id: 'house', status: 'failed', prompt: '一位身穿铠甲的骑士', error: '生成服务暂时不可用',
      width: null, height: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:01Z',
      task_id: 'task-1', awaiting_approval: false,
    })
    const wrapper = mountWidget()
    await wrapper.get('button.btn-ghost').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((btn) => btn.text() === '开始生成').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(3000); await flushPromises()
    expect(wrapper.text()).toContain('生成服务暂时不可用')
    const retry = wrapper.findAll('button').find((btn) => btn.text() === '重新生成')
    expect(retry).toBeTruthy()
  })

  it('放弃候选后清空预览', async () => {
    world.imageCandidate.mockResolvedValue({
      id: 'cand-1', entity_id: 'house', status: 'review_ready', prompt: '一位身穿铠甲的骑士', error: null,
      width: 512, height: 512, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:02Z',
      task_id: 'task-1', awaiting_approval: false,
    })
    const wrapper = mountWidget()
    await wrapper.get('button.btn-ghost').trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((btn) => btn.text() === '开始生成').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(3000); await flushPromises()
    await wrapper.findAll('button').find((btn) => btn.text() === '放弃').trigger('click')
    await flushPromises()
    expect(world.discardImageCandidate).toHaveBeenCalledWith('cand-1', 'p1')
    expect(wrapper.findAll('img').find((img) => img.attributes('alt') === '生成的候选图片')).toBeFalsy()
  })
})
