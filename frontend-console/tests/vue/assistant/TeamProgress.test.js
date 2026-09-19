import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import TeamProgress from "../../../vue/components/TeamProgress.vue"

describe("deep review coverage", () => {
  it("keeps partial coverage and source drift distinct from a passing report", async () => {
    const report = { phase: "completed", completion: "partial", freshness: "fresh", completed_count: 2, total_count: 3,
      work_items: [{ key: "facts", label: "事实与规则", status: "succeeded" }, { key: "characters", label: "人物知识", status: "failed" }],
      coverage: [{ label: "事实与规则", checked_dimensions: ["时序"], omissions: ["未读后文"] }],
      remaining_work: ["人物知识"], domain_results: [{ id: "review", type: "writing_review", task_id: "review" }] }
    const wrapper = mount(TeamProgress, { props: { collaboration: report } })
    expect(wrapper.text()).toContain("仅完成部分检查")
    expect(wrapper.text()).toContain("未读后文")
    await wrapper.get("button").trigger("click")
    expect(wrapper.emitted("locate")[0][0]).toEqual(report.domain_results[0])
    await wrapper.setProps({ collaboration: { ...report, freshness: "stale" } })
    expect(wrapper.get('[role="alert"]').text()).toContain("依据已变化")
    expect(wrapper.text()).not.toContain("已通过")
  })
})
