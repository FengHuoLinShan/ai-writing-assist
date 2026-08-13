import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WritingEditor from "../../../vue/views/writing/components/WritingEditor.vue"

function state(provenanceJson) {
  return {
    chapter: 1,
    draftId: "draft-1",
    status: "candidate",
    readonly: true,
    title: "候选",
    content: "正文",
    saving: false,
    provenanceJson,
  }
}

describe("WritingEditor semantic review gate", () => {
  it("审查前禁止采用，通过后开放，finding 以文本渲染", async () => {
    const wrapper = mount(WritingEditor, {
      props: {
        state: state({ source: "writing_generate", review_required: true }),
        attach: vi.fn(),
        detach: vi.fn(),
        reviewResult: {
          findings: [{
            finding_id: "finding-1",
            severity: "major",
            message: "<img src=x onerror=alert(1)>",
            location: { draft_id: "draft-1", excerpt: "正文" },
          }],
        },
      },
    })

    const adopt = wrapper.findAll("button").find((button) => button.text() === "采用到工作稿")
    expect(adopt.attributes("disabled")).toBeDefined()
    expect(wrapper.text()).toContain("运行独立语义审查")
    expect(wrapper.text()).toContain("<img src=x onerror=alert(1)>")
    expect(wrapper.find("img").exists()).toBe(false)

    await wrapper.setProps({
      state: state({
        source: "writing_generate",
        review_required: true,
        independent_review: { verdict: "pass", blocking_count: 0 },
      }),
    })
    expect(adopt.attributes("disabled")).toBeUndefined()
  })
})
