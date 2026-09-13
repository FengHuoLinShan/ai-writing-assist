import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ImportPreview from '../../prototypes/redesign/ImportPreview.vue'

describe('ImportPreview', () => {
  it('walks through sample selection, chapter selection, and material preparation', async () => {
    const wrapper = mount(ImportPreview)
    expect(wrapper.text()).toContain('选择示例文稿')
    await wrapper.findAll('button').find(button => button.text().includes('选择《潮汐来信.txt》')).trigger('click')
    expect(wrapper.text()).toContain('检查章节拆分')
    expect(wrapper.text()).toContain('潮汐之间：码头上的初次相遇')
    await wrapper.findAll('input[type="checkbox"]')[3].setValue(false)
    expect(wrapper.text()).toContain('3 / 4 章已选')
    await wrapper.findAll('button').find(button => button.text() === '准备资料').trigger('click')
    expect(wrapper.text()).toContain('准备资料')
    expect(wrapper.text()).toContain('尚未写入作品')
    expect(wrapper.text()).toContain('整理质量与授权范围')
    expect(wrapper.text()).toContain('持续整理后续新增章节')
  })

  it('starts directly on prepared examples for deep links', () => {
    const wrapper = mount(ImportPreview, { props: { initialSection: 'prepare' } })
    expect(wrapper.text()).toContain('已选择 4 个章节')
    expect(wrapper.text()).toContain('质量偏好')
  })

  it('manually advances the organizing workflow and preserves completed items after failure', async () => {
    const wrapper = mount(ImportPreview, { props: { initialSection: 'prepare' } })
    await wrapper.findAll('button').find(button => button.text() === '开始整理示例').trigger('click')
    expect(wrapper.text()).toContain('进行中')
    await wrapper.findAll('button').find(button => button.text() === '演示整理完成').trigger('click')
    expect(wrapper.text()).toContain('待决定')
    expect(wrapper.text()).toContain('地点 1 项')
    await wrapper.findAll('button').find(button => button.text() === '审阅导入世界资料').trigger('click')
    expect(wrapper.emitted('open')).toEqual([['审阅导入世界资料', 'compare', true]])
  })

  it('supports stop, resume, failure and retry without resetting successful items', async () => {
    const wrapper = mount(ImportPreview, { props: { initialSection: 'prepare' } })
    await wrapper.findAll('button').find(button => button.text() === '开始整理示例').trigger('click')
    await wrapper.findAll('button').find(button => button.text() === '演示失败').trigger('click')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('人物 2 项')
    await wrapper.findAll('button').find(button => button.text() === '重试未完成部分').trigger('click')
    expect(wrapper.text()).toContain('进行中')
    await wrapper.findAll('button').find(button => button.text() === '停止').trigger('click')
    expect(wrapper.text()).toContain('已停止')
    await wrapper.findAll('button').find(button => button.text() === '恢复整理').trigger('click')
    expect(wrapper.text()).toContain('进行中')
  })

  it('keeps selection semantics and retries parse failures', async () => {
    const wrapper = mount(ImportPreview, { props: { state: 'error', initialSection: 'chapters' } })
    expect(wrapper.text()).toContain('章节解析暂时没有完成')
    await wrapper.findAll('button').find(button => button.text() === '重试解析').trigger('click')
    expect(wrapper.text()).toContain('检查章节拆分')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(4)
  })

  it('emits navigation and open actions without file access', async () => {
    const wrapper = mount(ImportPreview)
    await wrapper.findAll('button').find(button => button.text() === '返回作品档案').trigger('click')
    expect(wrapper.emitted('navigate')).toEqual([['projects']])
    await wrapper.findAll('button').find(button => button.text().includes('选择《潮汐来信.txt》')).trigger('click')
    await wrapper.findAll('button').find(button => button.text() === '准备资料').trigger('click')
    await wrapper.findAll('button').find(button => button.text().includes('查看整理范围')).trigger('click')
    expect(wrapper.emitted('open')).toEqual([['准备整理资料', 'import', true]])
  })
})
