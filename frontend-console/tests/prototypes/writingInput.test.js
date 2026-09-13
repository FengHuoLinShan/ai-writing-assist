import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import WritingPreview from '../../prototypes/redesign/WritingPreview.vue'

describe('WritingPreview local manuscript input', () => {
  it('keeps each chapter draft and makes non-working identities read-only', async () => {
    const wrapper = mount(WritingPreview, { props: { state: 'normal' } })
    const title = wrapper.get('#rd-manuscript-title')
    const editor = wrapper.get('#rd-manuscript-editor')
    const editorNode = editor.element
    const titleNode = title.element
    title.element.textContent = '改过的标题'
    await title.trigger('input')
    editor.element.textContent += '\n\n新增的一段。'
    await editor.trigger('input')
    expect(wrapper.get('#rd-manuscript-editor').element).toBe(editorNode)
    expect(wrapper.get('#rd-manuscript-title').element).toBe(titleNode)

    await wrapper.findAll('.rd-chapter')[0].trigger('click')
    expect(wrapper.get('#rd-manuscript-title').text()).toBe('雾中的灯塔')
    await wrapper.findAll('.rd-chapter')[2].trigger('click')
    expect(wrapper.get('#rd-manuscript-title').text()).toBe('改过的标题')
    expect(wrapper.get('#rd-manuscript-editor').text()).toContain('新增的一段。')

    await wrapper.get('[aria-label="选择稿件身份"]').setValue('history')
    expect(wrapper.get('#rd-manuscript-title').attributes('aria-readonly')).toBe('true')
    expect(wrapper.get('#rd-manuscript-editor').attributes('contenteditable')).toBe('false')
    expect(wrapper.vm.locateChapter(1)).toBe(true)
    expect(wrapper.vm.locateChapter(99)).toBe(false)
  })

  it('starts an empty manuscript without reusing another chapter draft', async () => {
    const wrapper = mount(WritingPreview, { props: { state: 'empty' } })
    expect(wrapper.find('#rd-manuscript-editor').exists()).toBe(false)
    await wrapper.get('.rd-writing-empty button').trigger('click')
    expect(wrapper.get('#rd-manuscript-editor').text()).toBe('')
    expect(wrapper.get('#rd-manuscript-title').text()).toBe('')
  })

  it('keeps input on demo save failures and requires confirmation to discard it', async () => {
    const wrapper = mount(WritingPreview, { props: { state: 'normal' } })
    const editor = wrapper.get('#rd-manuscript-editor')
    editor.element.textContent += '\n保留这段文字。'
    await editor.trigger('input')
    await wrapper.findAll('button').find(button => button.text() === '保存工作稿').trigger('click')
    expect(wrapper.text()).toContain('保存工作稿')
    await wrapper.get('.rd-save-state-menu summary').trigger('click')
    await wrapper.find('.rd-save-state-menu').findAll('button').find(button => button.text() === '服务失败').trigger('click')
    expect(wrapper.text()).toContain('服务暂时没有保存成功')
    expect(wrapper.get('#rd-manuscript-editor').text()).toContain('保留这段文字。')

    const confirm = vi.fn().mockReturnValue(false)
    vi.stubGlobal('confirm', confirm)
    await wrapper.findAll('button').find(button => button.text() === '放弃修改').trigger('click')
    expect(confirm).toHaveBeenCalledOnce()
    expect(wrapper.get('#rd-manuscript-editor').text()).toContain('保留这段文字。')
    confirm.mockReturnValue(true)
    await wrapper.findAll('button').find(button => button.text() === '放弃修改').trigger('click')
    expect(wrapper.get('#rd-manuscript-editor').text()).not.toContain('保留这段文字。')
  })
})
