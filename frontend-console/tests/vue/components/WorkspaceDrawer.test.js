import { afterEach, expect, it } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import WorkspaceDrawer from '../../../vue/components/WorkspaceDrawer.vue'

enableAutoUnmount(afterEach)
afterEach(() => { document.body.innerHTML = '' })

it('preserves a child draft across inline, hidden drawer and modal modes and releases background isolation', async () => {
  const Draft = defineComponent({ setup: () => ({ draft: ref('') }), template: '<input aria-label="资料草稿" v-model="draft">' })
  const trigger = document.createElement('button')
  document.body.append(trigger)
  const wrapper = mount(WorkspaceDrawer, { props: { mobile: false, open: true, title: '本章资料' }, slots: { default: Draft }, attachTo: document.body })
  await wrapper.get('input').setValue('尚未保存的资料')
  await wrapper.setProps({ mobile: true, open: false })
  await flushPromises()
  expect(document.querySelector('input').value).toBe('尚未保存的资料')
  trigger.focus()
  await wrapper.setProps({ open: true })
  await flushPromises()
  expect(trigger.hasAttribute('inert')).toBe(true)
  expect(document.querySelector('[role="dialog"]').contains(document.activeElement)).toBe(true)
  await wrapper.setProps({ mobile: false })
  await flushPromises()
  expect(wrapper.get('input').element.value).toBe('尚未保存的资料')
  expect(trigger.hasAttribute('inert')).toBe(false)
  wrapper.unmount()
  expect(document.querySelector('.workspace-drawer-overlay')).toBeNull()
})
