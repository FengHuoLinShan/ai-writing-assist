import { afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import WritingEditor from "../../../vue/views/writing/components/WritingEditor.vue"

function state(provenanceJson, overrides = {}) {
  return {
    chapter: 1,
    draftId: "draft-1",
    status: "candidate",
    readonly: true,
    title: "候选",
    content: "正文",
    saving: false,
    provenanceJson,
    candidateAction: null,
    candidateActionError: null,
    ...overrides,
  }
}

describe("WritingEditor semantic review gate", () => {
  afterEach(() => { document.body.innerHTML = "" })

  it("候选决策在正文前聚焦，各状态只保留一个主操作", async () => {
    const wrapper = mount(WritingEditor, {
      attachTo: document.body,
      props: {
        state: state({ source: "writing_generate", review_required: true }),
        attach: vi.fn(),
        detach: vi.fn(),
        candidateComparisonAvailable: true,
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

    const panel = wrapper.get(".writing-candidate-review-panel")
    const sheet = wrapper.get(".writing-sheet")
    expect(panel.element.compareDocumentPosition(sheet.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await vi.waitFor(() => expect(document.activeElement).toBe(panel.element))
    expect(wrapper.find("#btn-publish").exists()).toBe(false)
    expect(wrapper.findAll(".btn-primary")).toHaveLength(1)
    expect(wrapper.text()).toContain("运行独立语义审查")
    const compareButton = wrapper.get(".writing-candidate-comparison .btn")
    expect(compareButton.text()).toBe("与当前工作稿比较")
    await compareButton.trigger("click")
    expect(wrapper.emitted("compare-candidate")).toHaveLength(1)
    expect(wrapper.text()).toContain("<img src=x onerror=alert(1)>")
    expect(wrapper.find("img").exists()).toBe(false)

    await wrapper.setProps({
      state: state({
        source: "writing_generate",
        review_required: true,
        independent_review: { verdict: "pass", blocking_count: 0 },
      }),
    })
    expect(wrapper.findAll(".btn-primary")).toHaveLength(1)
    expect(wrapper.get(".btn-primary").text()).toBe("采用到工作稿")
  })

  it("保存冲突提供导出与明确载入入口，备份失败时不能覆盖本地文字", async () => {
    const draft = state(null, { status: "draft", readonly: false, dirty: true, saveError: "409", saveConflict: true, backupComplete: true })
    const wrapper = mount(WritingEditor, { props: { state: draft, attach: vi.fn(), detach: vi.fn() } })
    expect(wrapper.get('[role="alert"]').text()).toContain("没有覆盖服务器的修改")
    const reload = wrapper.findAll('button').find(button => button.text() === "载入服务器最新版")
    await reload.trigger('click')
    expect(wrapper.emitted('reload-server')).toHaveLength(1)
    await wrapper.findAll('button').find(button => button.text() === "导出当前文字").trigger('click')
    expect(wrapper.emitted('export')).toHaveLength(1)
    await wrapper.setProps({ state: { ...draft, backupComplete: false } })
    expect(reload.attributes('disabled')).toBeDefined()
    expect(wrapper.find('#writing-retry-save').exists()).toBe(false)
  })

  it("审查未完成时明确阻止采用，不显示审查成功", () => {
    const wrapper = mount(WritingEditor, { props: {
      state: state({ review_required: true, independent_review: { verdict: "incomplete", blocking_count: 0 } }),
      attach: vi.fn(), detach: vi.fn(),
    } })
    expect(wrapper.text()).toContain("尚未完成必要检查")
    expect(wrapper.text()).not.toContain("审查已通过")
    expect(wrapper.findAll("button").some(button => button.text() === "采用到工作稿")).toBe(false)
    expect(wrapper.get(".btn-primary").text()).toBe("重新独立审查")
    expect(wrapper.findAll("button").filter(button => button.text().includes("独立审查"))).toHaveLength(1)
  })

  it("候选操作期间禁用决策并就地显示失败", () => {
    const wrapper = mount(WritingEditor, {
      props: {
        state: state(
          { source: "writing_generate", review_required: false },
          { candidateAction: "adopt", candidateActionError: "网络暂时不可用" },
        ),
        attach: vi.fn(),
        detach: vi.fn(),
        candidateComparisonAvailable: true,
      },
    })

    expect(wrapper.get(".writing-candidate-review-panel").attributes("aria-busy")).toBe("true")
    expect(wrapper.get(".btn-primary").text()).toBe("采用中…")
    expect(wrapper.findAll(".writing-candidate-review-actions .btn").every((button) => button.attributes("disabled") !== undefined)).toBe(true)
    expect(wrapper.get(".writing-candidate-comparison .btn").attributes("disabled")).toBeDefined()
    expect(wrapper.get("[role='alert']").text()).toBe("网络暂时不可用")
  })

  it("工具菜单互斥，动作、Escape 和外部点击后都收起", async () => {
    const wrapper = mount(WritingEditor, {
      attachTo: document.body,
      props: {
        state: state(null, { status: "draft", readonly: false, title: "第一章", content: "正文" }),
        hasChapters: true,
        attach: vi.fn(),
        detach: vi.fn(),
      },
    })
    const menus = wrapper.findAll("details.writing-tools-menu")
    const saveSummary = menus[0].get("summary")
    const aiSummary = menus[1].get("summary")

    await saveSummary.trigger("click")
    expect(menus[0].attributes("open")).toBeDefined()
    expect(saveSummary.attributes("aria-expanded")).toBe("true")
    await aiSummary.trigger("click")
    expect(menus[0].attributes("open")).toBeUndefined()
    expect(saveSummary.attributes("aria-expanded")).toBe("false")

    await aiSummary.trigger("keydown", { key: "Escape" })
    expect(menus[1].attributes("open")).toBeUndefined()
    expect(document.activeElement).toBe(aiSummary.element)

    await saveSummary.trigger("click")
    await wrapper.get("#btn-checkpoint-version").trigger("click")
    expect(wrapper.emitted("checkpoint")).toHaveLength(1)
    expect(menus[0].attributes("open")).toBeUndefined()
    expect(document.activeElement).toBe(saveSummary.element)

    await saveSummary.trigger("click")
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }))
    await wrapper.vm.$nextTick()
    expect(menus[0].attributes("open")).toBeUndefined()

    await aiSummary.trigger("click")
    await wrapper.get('[data-action="writing-open-owner-ai"]').trigger("click")
    expect(wrapper.emitted("open-ai-tools")).toHaveLength(1)
    expect(menus[1].attributes("open")).toBeUndefined()
    expect(document.activeElement).toBe(aiSummary.element)
  })
})
