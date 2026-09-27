import { afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WritingEditor from "../../../vue/views/writing/components/WritingEditor.vue"
import WritingCommentsPanel from "../../../vue/views/writing/components/WritingCommentsPanel.vue"

const draft = {
  chapter: 1, draftId: "draft-1", contentHash: "a".repeat(64), status: "draft",
  readonly: false, title: "章", content: "甲😀乙丙", dirty: false, saving: false,
}

afterEach(() => { document.body.innerHTML = "" })

describe("正文批注", () => {
  it("保留 textarea 输入，并按码点选区提交批注和常驻高亮", async () => {
    const wrapper = mount(WritingEditor, {
      attachTo: document.body,
      props: {
        state: { ...draft }, attach: vi.fn(), detach: vi.fn(),
        comments: [{ id: "c1", draft_id: "draft-1", start_offset: 1, end_offset: 3, excerpt: "😀乙", status: "open" }],
      },
    })
    const editor = wrapper.get("#writing-editor").element
    expect(editor.tagName).toBe("TEXTAREA")
    expect(wrapper.get(".writing-comment-mirror .is-highlighted").text()).toContain("😀乙")
    editor.setSelectionRange(1, 4)
    await wrapper.get("#writing-editor").trigger("pointerup")
    await wrapper.get(".writing-editor-buttons > button:nth-child(2)").trigger("click")
    expect(wrapper.emitted("add-comment")[0][0]).toMatchObject({
      selection: "😀乙", selection_start: 1, selection_end: 3,
    })
    editor.scrollTop = 24
    await wrapper.get("#writing-editor").trigger("scroll")
    expect(wrapper.get(".writing-comment-mirror").element.scrollTop).toBe(24)
    editor.setSelectionRange(4, 5)
    await wrapper.get("#writing-editor").trigger("keyup", { key: "ArrowRight" })
    await wrapper.get(".writing-editor-buttons > button:nth-child(2)").trigger("click")
    expect(wrapper.emitted("add-comment")[1][0].selection).toBe("丙")
    await wrapper.setProps({ state: { ...draft, dirty: true } })
    expect(wrapper.find(".writing-comment-mirror .is-highlighted").exists()).toBe(false)
    wrapper.unmount()
  })

  it("展示失效问题、批量执行入口与候选结果，不执行未选择项", async () => {
    const wrapper = mount(WritingCommentsPanel, {
      props: {
        canRun: true,
        comments: [
          { id: "c1", status: "open", origin: "author", excerpt: "原句", body: "改语气", last_run_task_id: null },
          { id: "c2", status: "stale", origin: "ai", excerpt: "重复", body: "定位失败", severity: "major" },
          { id: "c3", status: "open", origin: "ai", excerpt: "轻微建议", body: "可调整", severity: "minor" },
        ],
      },
    })
    expect(wrapper.get(".writing-comments__list").text()).toContain("定位失效")
    await wrapper.get(".writing-comments__focus").trigger("click")
    expect(wrapper.emitted("locate")[0][0].id).toBe("c1")
    await wrapper.get(".writing-comments__focus").trigger("keydown", { key: "Enter" })
    expect(wrapper.emitted("locate")).toHaveLength(2)
    await wrapper.findAll(".writing-comments__actions .btn")[1].trigger("click")
    expect(wrapper.emitted("run-comments")[0][0]).toEqual(["c1"])
    await wrapper.get("#comment-select-c3").setValue(true)
    await wrapper.findAll(".writing-comments__actions .btn")[1].trigger("click")
    expect(wrapper.emitted("run-comments")[1][0]).toEqual(["c1", "c3"])
    await wrapper.setProps({ task: { status: "done", result: { candidate_draft_id: "candidate-1" } } })
    expect(wrapper.text()).toContain("正文尚未改变")
    await wrapper.get(".writing-comments__result .btn-primary").trigger("click")
    expect(wrapper.emitted("open-candidate")[0][0]).toBe("candidate-1")
  })

  it("复核未过的批注候选只展示，不显示采用入口", () => {
    const wrapper = mount(WritingEditor, {
      props: {
        state: { ...draft, status: "candidate", readonly: true, provenanceJson: {
          source: "writing_comment_revision", review_required: true,
          knowledge_review: { status: "blocked" },
          independent_review: { verdict: "pass", blocking_count: 0 },
        } },
        attach: vi.fn(), detach: vi.fn(),
      },
    })
    expect(wrapper.text()).toContain("当前候选只能查看")
    expect(wrapper.text()).not.toContain("采用到工作稿")
    wrapper.unmount()
  })
})
