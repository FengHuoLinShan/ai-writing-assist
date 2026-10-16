import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"

import EditorialIssueCard from "../../../vue/components/EditorialIssueCard.vue"

describe("EditorialIssueCard", () => {
  it("单条修订建议以单数方向显示并保留证据说明", () => {
    const wrapper = mount(EditorialIssueCard, {
      props: {
        busy: false,
        selected: false,
        issue: {
          source_may_be_stale: false,
          disposition: "open",
          finding: {
            category: "scene",
            severity: "medium",
            judgment: "转场缺少可见的行动线索",
            reader_impact: "读者可能无法判断角色何时进入房间",
            why_now: "这个缺口影响后续人物位置理解",
            evidence: [{ chapter_index: 1, draft_id: "draft-1", quote: "门在身后合上" }],
            context_evidence: [],
            counterevidence: "",
            intent_relation: "",
            intent_quote: "",
            unchecked: "",
            directions: [
              {
                approach: "补出角色进入房间的动作",
                affected_chapters: [1],
                tradeoff: "会多一句过渡",
              },
            ],
          },
          decisions: [],
          rechecks: [],
          history: [],
        },
      },
    })

    expect(wrapper.get(".editorial-issue__directions strong").text()).toBe("建议方向")
    expect(wrapper.findAll(".editorial-issue__directions li")).toHaveLength(1)
    expect(wrapper.get(".editorial-issue__directions").text()).toContain("会多一句过渡")
  })
})
