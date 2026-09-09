import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MapSourcePicker from '../../../vue/views/map/MapSourcePicker.vue'
import { mapSourceRangeKey } from '../../../vue/views/map/mapStructureEditor.js'
import { resetBridgeOverrides, setBridgeOverrides } from '../../../vue/bridge/index.js'

enableAutoUnmount(afterEach)
const ref = (extra = {}) => ({ draft_id: '10000000-0000-0000-0000-000000000001', chapter_index: 4, version_number: 1, content_mode: 'canonical', start_offset: 10, end_offset: 50, source_hash: 'a'.repeat(64), range_hash: 'b'.repeat(64), ...extra })
const hit = (extra = {}) => ({ kind: 'manuscript', title: '第4章 城中', snippet: '旅馆……位于桥边', source_ref: ref(), index_fresh: true, ...extra })
const read = (text, extra = {}) => ({ source_ref: ref(), text, highlight_start: 0, highlight_end: Array.from(text).length, ...extra })
const button = (wrapper, name) => wrapper.findAll('button').find(item => item.text() === name)
describe('MapSourcePicker', () => {
  let api, state
  const render = (props = {}) => mount(MapSourcePicker, { global: { stubs: { teleport: true } }, props: { open: true, projectId: 'p1', feature: { id: 'mark', label: '旅馆', sources: [] }, ...props }, attachTo: document.body })
  beforeEach(() => {
    api = { context: { searchEvidence: vi.fn(async () => ({ hits: [hit()], total: 1 })), readEvidence: vi.fn(async () => read('旅馆位于桥边，正门朝向广场。', { title: '城中', index_fresh: true })) } }
    state = { currentProjectId: 'p1' }
    setBridgeOverrides({ api, state })
  })
  afterEach(resetBridgeOverrides)

  it('预填地点但不自动搜索，只查已采用正文；实际回读后才能明确关联', async () => {
    const wrapper = render()
    expect(wrapper.get('input').element.value).toBe('旅馆')
    expect(api.context.searchEvidence).not.toHaveBeenCalled()
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.context.searchEvidence).toHaveBeenCalledWith({ novel_id: 'p1', query: '旅馆', content_mode: 'canonical', visibility: { mode: 'author' }, scopes: ['manuscript'], include_pending_objects: false, top_k: 20 })
    expect(wrapper.text()).toContain('旅馆……位于桥边')
    expect(wrapper.emitted('add')).toBeUndefined()
    await button(wrapper, '查看原文').trigger('click'); await flushPromises()
    expect(api.context.readEvidence).toHaveBeenCalledWith({ novel_id: 'p1', content_mode: 'canonical', visibility: { mode: 'author' }, source_ref: ref(), before: 0, after: 0 })
    expect(wrapper.get('blockquote').text()).toBe('旅馆位于桥边，正门朝向广场。')
    await button(wrapper, '关联到“旅馆”').trigger('click')
    expect(wrapper.emitted('add')[0]).toEqual([{ kind: 'source_range', id: ref().draft_id, source_hash: ref().source_hash, source_ref: ref(), quote: '旅馆位于桥边，正门朝向广场。' }])
    expect(wrapper.text()).not.toContain(ref().draft_id)
  })

  it('排除工作稿和对象结果，缺失版本的正文不能选择，降级空态不声称查完全部', async () => {
    api.context.searchEvidence.mockResolvedValue({ hits: [hit({ kind: 'world_object' }), hit({ source_ref: ref({ content_mode: 'working' }) }), hit({ source_ref: null })], degraded: true })
    const wrapper = render(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.findAll('.map-source-hits li')).toHaveLength(1)
    expect(button(wrapper, '查看原文').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正文版本引用不完整')
    expect(wrapper.text()).toContain('只返回部分资料')
    api.context.searchEvidence.mockResolvedValue({ hits: [], degraded: true })
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('本次结果中暂未匹配')
  })

  it('搜索失败保持输入并可重试，失效版本不会变成新依据', async () => {
    api.context.searchEvidence.mockRejectedValueOnce(new Error('private backend detail'))
    const wrapper = render(); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(wrapper.text()).toContain('地图编辑仍保留')
    expect(wrapper.text()).not.toContain('private backend detail')
    await button(wrapper, '重试查找').trigger('click'); await flushPromises()
    api.context.readEvidence.mockRejectedValueOnce(Object.assign(new Error('old revision'), { status: 400 }))
    await button(wrapper, '查看原文').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('版本已变化或不可用')
    expect(wrapper.emitted('add')).toBeUndefined()
    await button(wrapper, '重试读取').trigger('click'); await flushPromises()
    expect(wrapper.find('blockquote').exists()).toBe(true)
  })

  it('原文回读不能悄悄改用另一个版本或工作稿', async () => {
    const wrapper = render({ initialSource: { source_ref: ref() } })
    api.context.readEvidence.mockResolvedValue(read('替换后的内容', { source_ref: ref({ version_number: 2 }) }))
    await flushPromises()
    await button(wrapper, '← 返回查找').trigger('click')
    await wrapper.get('form').trigger('submit'); await flushPromises()
    await button(wrapper, '查看原文').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('未自动替换')
    expect(wrapper.emitted('add')).toBeUndefined()
  })

  it('精确引用去重不依赖字段顺序，并保留最多8条的边界', async () => {
    const reordered = Object.fromEntries(Object.entries(ref()).reverse())
    const wrapper = render({ initialSource: { source_ref: ref() }, feature: { id: 'mark', label: '旅馆', sources: [{ kind: 'source_range', source_ref: reordered }] } })
    await flushPromises()
    expect(wrapper.text()).toContain('已关联当前标记')
    expect(button(wrapper, '关联到“旅馆”')).toBeUndefined()
    await wrapper.setProps({ feature: { id: 'mark', label: '旅馆', sources: Array.from({ length: 8 }, (_, i) => ({ kind: 'entity', id: String(i) })) } })
    expect(wrapper.text()).toContain('已有 8 条依据')
    expect(button(wrapper, '关联到“旅馆”')).toBeUndefined()
    expect(mapSourceRangeKey(ref({ range_hash: '' }))).toBe('')
  })

  it('取消、切换标记和切换项目隔离旧搜索与原文响应', async () => {
    let resolveSearch, resolveRead
    api.context.searchEvidence.mockReturnValueOnce(new Promise(resolve => { resolveSearch = resolve }))
    const wrapper = render(); await wrapper.get('form').trigger('submit')
    await wrapper.setProps({ feature: { id: 'bridge', label: '桥', sources: [] } })
    resolveSearch({ hits: [hit()], total: 1 }); await flushPromises()
    expect(wrapper.get('input').element.value).toBe('桥')
    expect(wrapper.find('.map-source-hits').exists()).toBe(false)
    api.context.readEvidence.mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve }))
    await wrapper.get('form').trigger('submit'); await flushPromises()
    await button(wrapper, '查看原文').trigger('click')
    state.currentProjectId = 'p2'
    resolveRead({ source_ref: ref(), text: '不该串项目的正文' }); await flushPromises()
    expect(wrapper.text()).not.toContain('不该串项目的正文')
    await wrapper.setProps({ open: false })
    expect(wrapper.find('[role=dialog]').exists()).toBe(false)
    expect(wrapper.emitted('add')).toBeUndefined()
  })

  it('Escape 可取消且恢复入口焦点，正文长片段引用按字符限制为真实子串', async () => {
    const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
    api.context.readEvidence.mockResolvedValue(read('𠮷'.repeat(1001)))
    const wrapper = render({ open: false, initialSource: { source_ref: ref() } })
    await wrapper.setProps({ open: true }); await flushPromises()
    await button(wrapper, '关联到“旅馆”').trigger('click')
    expect(wrapper.emitted('add')[0][0].quote).toBe('𠮷'.repeat(1000))
    await wrapper.get('[role=dialog]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ open: false }); await flushPromises()
    expect(document.activeElement).toBe(trigger)
    trigger.remove()
  })

  it('只引用段落中高亮的精确范围，Python 字符偏移不会被 Unicode 代理对错位', async () => {
    const before = '𠮷'.repeat(1002), selected = '旅馆在桥旁𠮷。', after = '无关的后文'
    api.context.readEvidence.mockResolvedValue(read(before + selected + after, { highlight_start: Array.from(before).length, highlight_end: Array.from(before + selected).length }))
    const wrapper = render({ initialSource: { source_ref: ref() } }); await flushPromises()
    expect(wrapper.get('blockquote mark').text()).toBe(selected)
    expect(wrapper.text()).toContain('所选正文版本 1')
    await button(wrapper, '关联到“旅馆”').trigger('click')
    expect(wrapper.emitted('add')[0][0].quote).toBe(selected)
    expect(wrapper.emitted('add')[0][0].source_ref).toEqual(ref())
  })

  it('没有精确高亮范围的回读结果不能关联', async () => {
    api.context.readEvidence.mockResolvedValue({ source_ref: ref(), text: '没有边界的上下文' })
    const wrapper = render({ initialSource: { source_ref: ref() } }); await flushPromises()
    expect(wrapper.text()).toContain('版本已变化或不可用')
    expect(wrapper.emitted('add')).toBeUndefined()
    expect(button(wrapper, '关联到“旅馆”')).toBeUndefined()
  })
})
