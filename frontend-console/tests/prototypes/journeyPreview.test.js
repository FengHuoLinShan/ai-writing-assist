import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import JourneyPreview from '../../prototypes/redesign/JourneyPreview.vue'
import JourneySetup from '../../prototypes/redesign/JourneySetup.vue'

describe('journey previews', () => {
  it('keeps the lighthouse journey hero and handles empty or failed lists', async () => {
    const wrapper = mount(JourneyPreview)
    expect(wrapper.text()).toContain('潮汐之间')
    expect(wrapper.text()).toContain('发现故事')
    await wrapper.findAll('button').find(button => button.text().includes('开启新旅程')).trigger('click')
    expect(wrapper.emitted('navigate')).toEqual([['journeys', 'setup']])

    const empty = mount(JourneyPreview, { props: { state: 'empty' } })
    expect(empty.text()).toContain('还没有开始的旅程')
    const failed = mount(JourneyPreview, { props: { state: 'error' } })
    expect(failed.text()).toContain('旅程列表暂时无法打开')
    await failed.findAll('button').find(button => button.text() === '重新加载').trigger('click')
    expect(failed.text()).toContain('发现故事')
  })

  it('prepares a direct journey and returns to the import entry', async () => {
    const wrapper = mount(JourneySetup)
    await wrapper.find('[aria-label="确认角色与开场"]').setValue(true)
    await wrapper.findAll('button').find(button => button.text() === '进入示例故事').trigger('click')
    expect(wrapper.emitted('navigate')).toEqual([['reading']])
    await wrapper.findAll('button').find(button => button.text() === '从作品导入').trigger('click')
    expect(wrapper.emitted('navigate')).toContainEqual(['import'])
  })

  it('does not treat an organizing source as ready', async () => {
    const wrapper = mount(JourneySetup, { props: { initialSection: 'source' } })
    await wrapper.findAll('button').find(button => button.text() === '演示重新整理').trigger('click')
    expect(wrapper.text()).toContain('整理尚未完成')
    expect(wrapper.findAll('button').find(button => button.text() === '进入示例故事').attributes('disabled')).toBeDefined()
    await wrapper.findAll('button').find(button => button.text() === '演示整理完成').trigger('click')
    expect(wrapper.text()).toContain('资料已整理')
  })
})
