import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorldImport from '../../prototypes/redesign/WorldImport.vue'

describe('WorldImport', () => {
  it('scans a fictional directory and keeps candidates, drafts, and formal scope distinct', async () => {
    const wrapper = mount(WorldImport)
    expect(wrapper.text()).toContain('扫描后才会显示候选资料')
    await wrapper.get('.rd-import-dropzone .rd-button').trigger('click')
    expect(wrapper.text()).toContain('候选资料')
    expect(wrapper.text()).toContain('23 项')
    expect(wrapper.text()).toContain('正式世界资料')
    await wrapper.get('.rd-world-import-actions .rd-button:nth-child(2)').trigger('click')
    await wrapper.get('.rd-import-scope')
  })

  it('exposes source and conflict reasons before creating a local draft example', async () => {
    const wrapper = mount(WorldImport)
    await wrapper.get('.rd-import-dropzone .rd-button').trigger('click')
    const files = wrapper.findAll('.rd-import-file')
    expect(files).toHaveLength(3)
    await files[2].trigger('click')
    expect(wrapper.get('[aria-label="导入文件说明"]').text()).toContain('存在冲突')
    await wrapper.get('.rd-world-import-actions .rd-button.primary').trigger('click')
    expect(wrapper.text()).toContain('工作稿示例已建立')
    await wrapper.get('.rd-world-import-actions .rd-button:nth-child(2)').trigger('click')
    expect(wrapper.get('[aria-label="采用范围"]').text()).toContain('23 项候选资料')
  })

  it('reuses the shared compare surface for imported material review', async () => {
    const wrapper = mount(WorldImport)
    await wrapper.get('.rd-import-dropzone .rd-button').trigger('click')
    await wrapper.findAll('.rd-world-import-actions .rd-text-button').find(button => button.text().includes('进入资料审阅')).trigger('click')
    expect(wrapper.emitted('open')[0]).toEqual(['审阅世界资料', 'compare', true])
  })

  it('keeps health checks separate from review approval and exposes recoverable history steps', async () => {
    const health = mount(WorldImport, { props: { initialSection: '资料健康' } })
    expect(health.get('[aria-label="资料健康检查"]').text()).toContain('不等于候选审阅通过')
    await health.get('[aria-label="资料健康检查"] .rd-button').trigger('click')
    expect(health.text()).toContain('仍有 2 项需要处理')

    const history = mount(WorldImport, { props: { initialSection: '处理历史' } })
    expect(history.get('[aria-label="处理历史"]').text()).toContain('失败可恢复')
    const recover = history.findAll('.rd-world-history-view-row').find(row => row.text().includes('失败可恢复'))
    await recover.find('.rd-button').trigger('click')
    expect(history.get('[role="status"]').text()).toContain('已恢复失败步骤示例')
  })
})
