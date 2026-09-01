import { beforeEach, describe, expect, it, vi } from "vitest"

import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { renderContextSummary } from "../shared/contextSummaryRenderer.js"
import { clearDocument } from "./helpers.js"

await import("../ui/modal.js")

const FINGERPRINT = "a".repeat(64)

function preview(overrides = {}) {
  return {
    context_fingerprint: FINGERPRINT,
    context_mode: "canonical",
    include_pending_objects: false,
    scope: "chapter",
    selected_asset_ids: { project: ["p1"], context_sections: ["writing_objective"] },
    selection_state: { counts: { required: 1, automatic: 0, author_pinned: 0, excluded: 0, omitted: 0 }, excluded_items: [], omitted_items: [] },
    sections: [{
      key: "writing_objective",
      title: "本次任务",
      status: "system",
      can_exclude: false,
      items: [{ key: "writing_objective:section", title: "本次任务", preview: "生成", status: "system", selection_state: "required", can_exclude: false }],
      sources: [],
    }],
    warnings: [],
    blockers: [],
    ...overrides,
  }
}

function mountModalDom() {
  document.body.innerHTML = `
    <div class="vue-shell-root">
      <button id="opener" type="button">打开</button>
      <main id="writing-host"><button type="button">写作操作</button></main>
      <div id="toast-container" data-imperative-service-host="toast"></div>
      <div id="modal-overlay" class="hidden" data-imperative-service-host="modal">
        <div id="modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-title">
          <div id="modal-header"><span id="modal-title"></span><button id="modal-close" type="button" aria-label="关闭对话框">×</button></div>
          <div id="modal-body"></div><div id="modal-footer"></div>
        </div>
      </div>
    </div>`
  const overlay = document.getElementById("modal-overlay")
  document.getElementById("modal-close").addEventListener("click", (event) => closeModal(event))
  overlay.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeModal(event)
  })
}

function footerButton(name) {
  return Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === name)
}

async function waitForPreview() {
  await vi.waitFor(() => expect(document.getElementById("ai-ref-status")?.textContent).toContain("资料已整理"))
}

beforeEach(() => {
  globalThis.closeModal?.({ force: true })
  clearDocument()
  mountModalDom()
  vi.clearAllMocks()
  api.context.compile = vi.fn().mockResolvedValue(preview())
  api.context.confirm = vi.fn().mockResolvedValue({ id: "confirmation-1", context_fingerprint: FINGERPRINT })
  api.context.proposeSelection = vi.fn()
  api.context.searchEvidence = vi.fn()
  api.context.listActivationProfiles = vi.fn().mockResolvedValue({ items: [] })
})

describe("aiReferenceModal", () => {
  it("普通摘要使用作者语言，仅诊断视图显示内部信息", () => {
    const summary = {
      scope: "chapter",
      selected_asset_ids: { context_sections: ["world"] },
      sections: [{ key: "retrieval_evidence_packs", title: "检索到的设定", status: "canonical", token_count: 42, sources: [{ type: "rag", id: "internal-1" }] }],
      budget_events: [{ section_key: "retrieval_evidence_packs", event_type: "truncated", before_tokens: 80, after_tokens: 42, reason: "超出预算" }],
      result_refs: [{ type: "confirmation", id: "internal-result" }],
    }
    const ordinary = renderContextSummary(summary)
    expect(ordinary).toContain("当前章节")
    expect(ordinary).not.toContain("tokens")
    expect(ordinary).not.toContain("internal-1")
    const diagnostic = renderContextSummary(summary, { diagnostic: true })
    expect(diagnostic).toContain("Token")
    expect(diagnostic).toContain("internal-result")
  })

  it("打开后自动预览，完成前不能开始任务", async () => {
    let resolvePreview
    api.context.compile.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成", scope: "chapter" }).catch(() => {})
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(1))
    expect(footerButton("按这份资料开始").disabled).toBe(true)
    resolvePreview(preview())
    await waitForPreview()
    expect(footerButton("按这份资料开始").disabled).toBe(false)
    expect(api.context.confirm).not.toHaveBeenCalled()
  })

  it("最终确认只落一条记录并绑定刚审查的指纹", async () => {
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成", scope: "chapter" })
    await waitForPreview()
    footerButton("按这份资料开始").click()
    await expect(promise).resolves.toMatchObject({ id: "confirmation-1" })
    expect(api.context.compile).toHaveBeenCalledTimes(1)
    expect(api.context.confirm).toHaveBeenCalledTimes(1)
    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({ expected_context_fingerprint: FINGERPRINT }))
  })

  it("确认请求期间冻结全部资料操作", async () => {
    let resolveConfirm
    api.context.confirm.mockImplementation(() => new Promise((resolve) => { resolveConfirm = resolve }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成", scope: "chapter" })
    await waitForPreview()

    footerButton("按这份资料开始").click()
    await vi.waitFor(() => expect(api.context.confirm).toHaveBeenCalledTimes(1))

    expect(document.getElementById("ai-ref-user-note").disabled).toBe(true)
    expect(document.getElementById("ai-ref-scope").disabled).toBe(true)
    expect(document.getElementById("ai-ref-selection-submit").disabled).toBe(true)
    expect(document.getElementById("ai-ref-search-submit").disabled).toBe(true)
    expect(footerButton("重新整理").disabled).toBe(true)
    expect(document.getElementById("ai-ref-status").textContent).toContain("正在确认")

    resolveConfirm({ id: "confirmation-1", context_fingerprint: FINGERPRINT })
    await expect(promise).resolves.toMatchObject({ id: "confirmation-1" })
  })

  it("确认发生 409 时恢复控件并重新整理", async () => {
    api.context.confirm.mockRejectedValue(Object.assign(new Error("资料已变化"), { status: 409 }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成", scope: "chapter" }).catch(() => null)
    await waitForPreview()

    footerButton("按这份资料开始").click()

    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    await waitForPreview()
    expect(document.getElementById("ai-ref-user-note").disabled).toBe(false)
    expect(footerButton("重新整理").disabled).toBe(false)
    expect(footerButton("按这份资料开始").disabled).toBe(false)

    footerButton("取消").click()
    await promise
  })

  it("页脚保持统一按钮样式和作者语言", () => {
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    const buttons = Array.from(document.querySelectorAll("#modal-footer button"))
    expect(buttons.map((button) => button.textContent)).toEqual(["重新整理", "按这份资料开始", "取消"])
    expect(buttons.map((button) => button.className)).toEqual(["btn", "btn btn-primary", "btn btn-ghost"])
    expect(document.getElementById("modal-content")?.classList.contains("modal-content--large")).toBe(true)
  })

  it("修改任务要求后标脏，重新整理时参与检索", async () => {
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    const note = document.getElementById("ai-ref-user-note")
    note.value = "只使用第 3 章前的证据"
    note.dispatchEvent(new Event("input", { bubbles: true }))
    expect(footerButton("按这份资料开始").disabled).toBe(true)
    footerButton("重新整理").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ user_note: "只使用第 3 章前的证据" }))
  })

  it("逐项移除与恢复使用结构化 selection ref", async () => {
    const ref = { kind: "target", target_ref: { target_type: "world_entity", target_id: "entity-1", target_path: "" } }
    api.context.compile
      .mockResolvedValueOnce(preview({ sections: [{ key: "world_entities", title: "相关世界对象", items: [{ key: "world:item-1", title: "北港", preview: "港口", status: "canonical", selection_ref: ref, selection_state: "automatic", can_exclude: true }], sources: [] }] }))
      .mockResolvedValueOnce(preview({ sections: [], selection_state: { excluded_items: [{ key: "world:item-1", title: "北港", preview: "港口", status: "canonical", selection_ref: ref, selection_state: "excluded", can_exclude: true }], omitted_items: [] } }))
      .mockResolvedValueOnce(preview({ sections: [{ key: "world_entities", title: "相关世界对象", items: [{ key: "world:item-1", title: "北港", preview: "港口", status: "canonical", selection_ref: ref, selection_state: "automatic", can_exclude: true }], sources: [] }] }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-exclude-item]")).not.toBeNull())
    document.querySelector("[data-ai-ref-exclude-item]").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ excluded_refs: [ref] }))
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-restore-item]")).not.toBeNull())
    document.querySelector("[data-ai-ref-restore-item]").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(3))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ excluded_refs: [] }))
  })

  it("预算遗漏项可显式加入并升级为作者选择", async () => {
    const ref = { kind: "target", target_ref: { target_type: "world_entity", target_id: "entity-2", target_path: "" } }
    api.context.compile.mockResolvedValueOnce(preview({
      sections: [],
      selection_state: {
        excluded_items: [],
        omitted_items: [{ key: "omitted-1", title: "南城", preview: "港道", selection_ref: ref, selection_state: "omitted", can_exclude: true }],
      },
    }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-restore-item]")?.textContent).toContain("加入本次资料"))
    document.querySelector("[data-ai-ref-restore-item]").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ pinned_refs: [ref] }))
  })

  it("Scene 范围与工作稿模式在预览中保持可见且一致", async () => {
    confirmAiReference({ novel_id: "p1", action: "story.scene.one_click", task: "推演", scope: "scene", context_mode: "working" }).catch(() => {})
    await waitForPreview()
    expect(document.getElementById("ai-ref-scope").value).toBe("scene")
    expect(api.context.compile).toHaveBeenCalledWith(expect.objectContaining({ scope: "scene", context_mode: "working", content_mode: "working" }))
  })

  it("自然语言调整先展示提议，应用后才修改资料", async () => {
    const ref = { kind: "target", target_ref: { target_type: "world_entity", target_id: "entity-2", target_path: "" } }
    api.context.proposeSelection.mockResolvedValue({
      summary: "建议加入人物设定",
      operations: [{ operation: "include", selection_ref: ref, label: "沈岚", reason: "与任务直接相关" }],
      unresolved: [],
      warnings: [],
    })
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    document.getElementById("ai-ref-selection-command").value = "加入沈岚的人物设定"
    document.getElementById("ai-ref-selection-submit").click()
    await vi.waitFor(() => expect(document.body.textContent).toContain("建议加入人物设定"))
    expect(api.context.compile).toHaveBeenCalledTimes(1)
    expect(footerButton("按这份资料开始").disabled).toBe(true)
    document.querySelector("[data-ai-ref-apply-proposal]").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ pinned_refs: [ref] }))
  })

  it("放弃自然语言提议不会改变资料", async () => {
    api.context.proposeSelection.mockResolvedValue({ summary: "建议调整", operations: [{ operation: "exclude", selection_ref: { kind: "target", target_ref: { target_type: "world_entity", target_id: "e1", target_path: "" } }, label: "旧城", reason: "无关" }], unresolved: [], warnings: [] })
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    document.getElementById("ai-ref-selection-command").value = "去掉旧城"
    document.getElementById("ai-ref-selection-submit").click()
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-dismiss-proposal]")).not.toBeNull())
    document.querySelector("[data-ai-ref-dismiss-proposal]").click()
    expect(api.context.compile).toHaveBeenCalledTimes(1)
    expect(footerButton("按这份资料开始").disabled).toBe(false)
  })

  it("手动搜索可把安全引用加入本次资料", async () => {
    const targetRef = { target_type: "outline_scene", target_id: "scene-2", target_path: "" }
    api.context.searchEvidence.mockResolvedValue({ hits: [{ title: "雨夜追逐", snippet: "沈岚抵达北港", target_ref: targetRef }] })
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    document.querySelector(".ai-ref-tools details").open = true
    document.getElementById("ai-ref-search-input").value = "雨夜追逐"
    document.getElementById("ai-ref-search-submit").click()
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-add-result]")).not.toBeNull())
    document.querySelector("[data-ai-ref-add-result]").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ pinned_refs: [{ kind: "target", target_ref: targetRef }] }))
  })

  it("blocker 会阻止开始任务", async () => {
    api.context.compile.mockResolvedValue(preview({ blockers: ["作者添加资料超过容量"] }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await vi.waitFor(() => expect(document.body.textContent).toContain("作者添加资料超过容量"))
    expect(footerButton("按这份资料开始").disabled).toBe(true)
  })

  it("保留 Scene、POV 与未来可见截止字段", async () => {
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成", scope: "chapter", chapter_index: 2, scene_id: "scene-1", visible_until_scene_id: "scene-1", reveal_mode: "character", viewpoint_character_id: "char-1", character_ids: ["char-1"] }).catch(() => {})
    await waitForPreview()
    expect(api.context.compile).toHaveBeenCalledWith(expect.objectContaining({ scene_id: "scene-1", visible_until_scene_id: "scene-1", reveal_mode: "character", viewpoint_character_id: "char-1", character_ids: ["char-1"] }))
  })

  it("已发布 Profile 只有作者选择后才进入新预览", async () => {
    api.context.listActivationProfiles.mockResolvedValue({ items: [{ id: "profile-1", name: "北境规则", status: "published", version_number: 2 }] })
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.not.objectContaining({ activation_profile_id: "profile-1" }))
    const select = document.getElementById("ai-ref-activation-profile")
    select.value = "profile-1"
    select.dispatchEvent(new Event("change", { bubbles: true }))
    footerButton("重新整理").click()
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalledTimes(2))
    expect(api.context.compile).toHaveBeenLastCalledWith(expect.objectContaining({ activation_profile_id: "profile-1" }))
  })

  it("关闭时丢弃迟到预览且恢复打开按钮焦点", async () => {
    let resolvePreview
    api.context.compile.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve }))
    const opener = document.getElementById("opener")
    opener.focus()
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalled())
    document.getElementById("modal-close").click()
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    resolvePreview(preview({ sections: [{ key: "late", title: "迟到", items: [] }] }))
    await Promise.resolve()
    expect(document.body.textContent).not.toContain("迟到")
    expect(document.activeElement).toBe(opener)
  })

  it("替换弹窗不会被旧请求修改", async () => {
    let resolvePreview
    api.context.compile.mockImplementation(() => new Promise((resolve) => { resolvePreview = resolve }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    await vi.waitFor(() => expect(api.context.compile).toHaveBeenCalled())
    showModalHtml("新弹窗", "保持不变", [], { protectUnsaved: false })
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    resolvePreview(preview())
    await Promise.resolve()
    expect(document.getElementById("modal-body").textContent).toBe("保持不变")
  })

  it("整理超时显示可重试提示且保留调整", async () => {
    api.context.compile.mockRejectedValue(new Error("请求超时，请检查后端服务是否运行"))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await vi.waitFor(() => expect(document.getElementById("ai-ref-error")?.textContent).toContain("AI 参考资料整理超时"))
    expect(document.getElementById("ai-ref-error")?.textContent).not.toContain("检查后端服务")
    expect(footerButton("按这份资料开始").disabled).toBe(true)
  })

  it("动态来源、提议和搜索结果均转义", async () => {
    const bad = '<img src=x onerror="alert(1)">'
    api.context.compile.mockResolvedValue(preview({ sections: [{ key: "world", title: "资料", items: [{ key: "bad", title: bad, preview: bad, status: "canonical", selection_state: "automatic", can_exclude: false }], sources: [] }] }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    await waitForPreview()
    expect(document.querySelector("#ai-ref-summary img")).toBeNull()
    expect(document.getElementById("ai-ref-summary").textContent).toContain(bad)
  })
})
