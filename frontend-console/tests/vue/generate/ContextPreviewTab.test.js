import { afterEach, describe, expect, it } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

import ContextBundleView from "../../../vue/views/generate/components/ContextBundleView.vue"
import ContextPreviewTab from "../../../vue/views/generate/components/ContextPreviewTab.vue"

const bundle = {
  scope: "arc",
  reveal_mode: "author_safe",
  total_tokens: 3680,
  budget_tokens: 4000,
  sections: [
    {
      key: "scene_blueprint", tier: 0, token_count: 420, title: "当前场景",
      preview: "林舟需要判断是否把发现告诉同行者。", status: "canonical",
      activation_reason: "当前 scene_id/章节范围",
      sources: [{ type: "scene", id: "scene-secret-id", label: "退潮后的石门" }],
    },
    {
      key: "retrieval_evidence_packs", tier: 2, token_count: 2320, title: "正文与导入资料",
      preview: '<img src=x onerror="boom">', status: "mixed",
      sources: [{ type: "chapter", id: "chapter-secret-id", label: "第一章 潮门初启" }],
      truncated: true,
    },
  ],
  evicted: ["style_assets"],
  truncated: ["retrieval_evidence_packs"],
  warnings: ["RAG 未找到更早章节"],
  budget_events: [{ section_key: "style_assets", event_type: "evicted", reason: "超过 token 预算", before_tokens: 480, after_tokens: 0, tier: 3 }],
}

afterEach(() => { document.body.innerHTML = "" })

describe("author-facing context review", () => {
  it("uses author titles and sources while keeping raw compiler fields collapsed", () => {
    const wrapper = mount(ContextBundleView, { props: { bundle }, attachTo: document.body })

    const overview = wrapper.get(".generate-context-overview")
    expect(overview.text()).toContain("已准备 2 类参考资料")
    expect(overview.text()).toContain("来自 2 项可核对来源")
    expect(overview.text()).toContain("文风参考未加入本次资料")
    expect(overview.text()).not.toContain("author_safe")
    expect(wrapper.get(".generate-context-sections").text()).toContain("当前场景")
    expect(wrapper.get(".generate-context-sections").text()).toContain("退潮后的石门")
    expect(wrapper.get(".generate-context-sections").text()).toContain("当前场景/章节范围")
    expect(wrapper.find("img").exists()).toBe(false)
    expect(wrapper.text()).not.toContain("scene-secret-id")
    expect(wrapper.get(".generate-context-diagnostics").element.open).toBe(false)
    expect(wrapper.get(".generate-context-diagnostics").text()).toContain("scene_blueprint")
  })

  it("keeps the author summary visible beside generated copyable text", () => {
    const wrapper = mount(ContextPreviewTab, {
      props: { bundle, markdown: "# 完整资料\n\n正文", sourceText: "任务：检查潮门规则", busy: false, error: "" },
    })

    expect(wrapper.text()).toContain("完整参考资料")
    expect(wrapper.text()).toContain("已准备 2 类参考资料")
    expect(wrapper.get(".generate-context-markdown").element.open).toBe(true)
    expect(wrapper.get(".generate-markdown-pre").text()).toContain("# 完整资料")
    expect(wrapper.get('[data-action="copy-task-md"]').text()).toBe("复制完整文本")
  })

  it("offers an empty-state action and focuses a retryable render failure", async () => {
    const empty = mount(ContextPreviewTab, { props: { bundle: null, markdown: "", sourceText: "", busy: false, error: "" } })
    await empty.get('[data-action="start-context-preview"]').trigger("click")
    expect(empty.emitted("return")).toHaveLength(1)

    const failed = mount(ContextPreviewTab, {
      props: { bundle, markdown: "", sourceText: "任务：检查潮门规则", busy: false, error: "" },
      attachTo: document.body,
    })
    await failed.setProps({ error: "当前摘要仍保留，请重试。" })
    await flushPromises()
    expect(document.activeElement).toBe(failed.get(".generate-task-error").element)
    await failed.get('[data-action="retry-context-preview"]').trigger("click")
    expect(failed.emitted("render-markdown")).toHaveLength(1)
  })
})
