import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldEvidenceSummary from "../../../vue/views/world/components/WorldEvidenceSummary.vue"
import { setBridgeOverrides, resetBridgeOverrides } from "../../../vue/bridge/index.js"
afterEach(resetBridgeOverrides)
it("回读稳定的作者来源，切换候选后不展示晚到原文", async () => {
  let finish
  const readEvidence = vi.fn(() => new Promise(resolve => { finish = resolve }))
  setBridgeOverrides({ state: { currentProjectId: "p1" }, api: { context: { readEvidence } } })
  const source = { draft_id: "d1", chapter_index: 3, version_number: 1, start_offset: 0, end_offset: 8, range_hash: "r", source_hash: "s", content_mode: "canonical" }
  const wrapper = mount(WorldEvidenceSummary, { props: { showActions: true, item: { alias: "守门者", quote: "他被称为守门者", source_ref: source } } })
  await wrapper.findAll("button").find(button => button.text().includes("打开第 3 章")).trigger("click")
  expect(readEvidence).toHaveBeenCalledWith(expect.objectContaining({ novel_id: "p1", source_ref: source, visibility: { mode: "author" } }))
  await wrapper.setProps({ item: { alias: "另一个名称" } })
  finish({ title: "旧章", text: "旧候选的原文" }); await flushPromises()
  expect(wrapper.text()).not.toContain("旧候选的原文")
  expect(wrapper.text()).toContain("名称归属依据待核对")
  wrapper.unmount()
})
