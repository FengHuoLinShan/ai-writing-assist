import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CandidateReview from '../../prototypes/redesign/CandidateReview.vue'

describe('CandidateReview', () => {
  it('shows pending candidate comparison and emits decisions without mutating props', async () => {
    const candidate = { status: 'pending', source: '第三章 · 潮汐之间', review: '通过', stale: false }
    const wrapper = mount(CandidateReview, { props: { candidate } })
    expect(wrapper.text()).toContain('待采用')
    expect(wrapper.text()).toContain('第三章 · 潮汐之间')
    expect(wrapper.text()).toContain('局部段落改写 · 示例')
    await wrapper.findAll('button').find(button => button.text().includes('采用到工作稿')).trigger('click')
    expect(wrapper.emitted('update:status')).toEqual([['adopted']])
    expect(candidate.status).toBe('pending')
  })

  it('blocks adoption when source is stale and can request source recheck', async () => {
    const wrapper = mount(CandidateReview, {
      props: { candidate: { status: 'pending', source: '第三章 · 潮汐之间', review: '通过', stale: true } },
    })
    expect(wrapper.text()).toContain('来源已过期')
    expect(wrapper.text()).toContain('暂不能采用')
    expect(wrapper.findAll('button').find(button => button.text().includes('采用到工作稿')).attributes('disabled')).toBeDefined()
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('update:stale')).toEqual([[false]])
  })

  it('keeps adopted and rejected identities distinct from formal正文', async () => {
    const wrapper = mount(CandidateReview, {
      props: { candidate: { status: 'adopted', source: '第三章 · 潮汐之间', review: '已审查', stale: false } },
    })
    expect(wrapper.text()).toContain('已采用到工作稿')
    expect(wrapper.text()).toContain('尚未成为正式正文')
    await wrapper.setProps({ candidate: { status: 'rejected', source: '第三章 · 潮汐之间', review: '已审查', stale: false } })
    expect(wrapper.text()).toContain('已拒绝')
    expect(wrapper.text()).toContain('原工作稿保持不变')
  })

  it('does not allow adoption before review and exposes manual revision states', async () => {
    const wrapper = mount(CandidateReview, {
      props: { candidate: { status: 'pending', source: '人物资料', review: '有阻断项', stale: false } },
    })
    expect(wrapper.text()).toContain('需要先处理阻断项')
    expect(wrapper.findAll('button').find(button => button.text().includes('采用到工作稿')).attributes('disabled')).toBeDefined()
    await wrapper.get('.rd-candidate-state-controls summary').trigger('click')
    await wrapper.find('.rd-candidate-state-controls').findAll('button').find(button => button.text() === '审查通过').trigger('click')
    expect(wrapper.emitted('update:review')).toEqual([['通过']])
    await wrapper.setProps({ candidate: { status: 'pending', source: '人物资料', review: '有阻断项', revision: '进行中', stale: false } })
    await wrapper.find('.rd-candidate-revision').findAll('button').find(button => button.text() === '演示返修完成').trigger('click')
    expect(wrapper.emitted('update:revision')).toEqual([['完成']])
  })
})
