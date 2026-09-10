import { expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import AssistantValue from "../../../vue/components/AssistantValue.vue"

it("world page proposals show author labels and omit carrier metadata", () => {
  const wrapper = mount(AssistantValue, { props: { value: { title: "钟楼", page_type: "background", free_text: "停止报时", page_meta_json: null, linked_asset_refs_json: {}, template_key: null, sort_order: null } } })
  expect(wrapper.text()).toContain("资料类型")
  expect(wrapper.text()).toContain("背景")
  expect(wrapper.text()).toContain("停止报时")
  expect(wrapper.text()).not.toMatch(/page_type|page_meta|linked_asset|sort_order|template_key/)
  wrapper.unmount()
})
