import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import InteractionAuthorPanel from "../../../vue/components/InteractionAuthorPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

const journey = (id, title = "雾港来客") => ({
  id, title, status: "active", selection_epoch: 1, action_options_enabled: true,
  source: { version_number: 1, stale: false },
})

let interactions
beforeEach(() => {
  localStorage.clear()
  interactions = {
    authorJourneys: vi.fn(async ({ author_project_id }) => ({
      preview: { items: [journey(`${author_project_id}-journey`)] },
    })),
    prepareAuthorJourneyTitle: vi.fn(async () => ({
      preview: { effect: "将旅程更名", before: { title: "雾港来客" }, after: { title: "新名字" } },
      preview_hash: "a".repeat(64),
    })),
    confirmAuthorJourneyTitle: vi.fn(async () => ({ result: {} })),
  }
  setBridgeOverrides({ api: { interactions } })
})
afterEach(() => resetBridgeOverrides())

it("reads the author's journeys when the panel first opens and keeps the draft after a 409", async () => {
  const wrapper = mount(InteractionAuthorPanel, { props: { projectId: "author-one", active: true } })
  await flushPromises()
  expect(interactions.authorJourneys).toHaveBeenCalledOnce()
  expect(wrapper.text()).toContain("雾港来客")

  await wrapper.get('input[maxlength="255"]').setValue("新名字")
  await wrapper.findAll("button").find(button => button.text() === "预览新名称").trigger("click")
  await flushPromises()
  expect(wrapper.text()).toContain("核对后确认")

  interactions.confirmAuthorJourneyTitle.mockRejectedValueOnce(Object.assign(new Error("版本已变化"), { status: 409 }))
  const confirm = wrapper.findAll("button").find(button => button.text() === "确认这项变更")
  await confirm.trigger("click")
  await confirm.trigger("click")
  await flushPromises()
  expect(interactions.confirmAuthorJourneyTitle).toHaveBeenCalledOnce()
  expect(wrapper.get('input[maxlength="255"]').element.value).toBe("新名字")
  expect(wrapper.text()).toContain("未保存的设置或名称仍保留")
})

it("discards a late response from the previous author project", async () => {
  let finishOld
  interactions.authorJourneys.mockImplementation(({ author_project_id }) => author_project_id === "old"
    ? new Promise(resolve => { finishOld = resolve })
    : Promise.resolve({ preview: { items: [journey("new-journey", "新作品旅程")] } }))
  const wrapper = mount(InteractionAuthorPanel, { props: { projectId: "old", active: true } })
  await flushPromises()
  await wrapper.setProps({ projectId: "new" })
  await flushPromises()
  finishOld({ preview: { items: [journey("old-journey", "旧作品旅程")] } })
  await flushPromises()
  expect(wrapper.text()).toContain("新作品旅程")
  expect(wrapper.text()).not.toContain("旧作品旅程")
})
