import { describe, it, expect, vi, beforeEach } from "vitest"
import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { clearDocument } from "./helpers.js"

await import("../ui/modal.js")

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
    </div>
  `
  const overlay = document.getElementById("modal-overlay")
  document.getElementById("modal-close").addEventListener("click", (event) => closeModal(event))
  overlay.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeModal(event)
  })
}

beforeEach(() => {
  globalThis.closeModal?.({ force: true })
  clearDocument()
  mountModalDom()
  vi.clearAllMocks()
  api.context.listActivationProfiles = vi.fn().mockResolvedValue({ items: [] })
})

describe("aiReferenceModal", () => {
  it("keeps the existing footer classes and button types without duplicate btn tokens", () => {
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    const buttons = Array.from(document.querySelectorAll("#modal-footer button"))
    expect(buttons.map((button) => button.type)).toEqual(["button", "button", "button"])
    expect(buttons.map((button) => button.className)).toEqual(["btn", "btn btn-primary", "btn btn-ghost"])
  })

  it("releases each busy button after interleaved refresh and failed confirm", async () => {
    let resolveRefresh
    api.context.confirm
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
      .mockRejectedValueOnce(new Error("确认失败"))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    const refresh = Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "重新整理")
    const confirm = Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "确认使用")
    refresh.click()
    confirm.click()
    await vi.waitFor(() => expect(confirm.disabled).toBe(false))
    expect(refresh.disabled).toBe(true)
    resolveRefresh({ id: "refresh", selected_asset_ids: {}, warnings: [] })
    await vi.waitFor(() => expect(refresh.disabled).toBe(false))
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("does not enable the shared refresh button before all section exclusions settle", async () => {
    let resolveFirst
    let resolveSecond
    api.context.confirm
      .mockResolvedValueOnce({
        id: "base",
        selected_asset_ids: {},
        warnings: [],
        sections: [
          { key: "one", title: "一", can_exclude: true, status: "canonical", sources: [] },
          { key: "two", title: "二", can_exclude: true, status: "canonical", sources: [] },
        ],
      })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))
    confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch(() => {})
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "重新整理").click()
    await vi.waitFor(() => expect(document.querySelectorAll("[data-ai-ref-exclude-section]")).toHaveLength(2))
    const refresh = Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "重新整理")
    document.querySelectorAll("[data-ai-ref-exclude-section]")[0].click()
    document.querySelectorAll("[data-ai-ref-exclude-section]")[1].click()
    expect(refresh.disabled).toBe(true)
    resolveFirst({ id: "one", selected_asset_ids: {}, warnings: [] })
    await Promise.resolve()
    expect(refresh.disabled).toBe(true)
    resolveSecond({ id: "two", selected_asset_ids: {}, warnings: [] })
    await vi.waitFor(() => expect(refresh.disabled).toBe(false))
  })

  it("rejects unavailable modal seams, missing sessions, and missing footer controls", async () => {
    const originalShow = globalThis.showModalHtml
    globalThis.showModalHtml = vi.fn(() => { throw new Error("不可用") })
    await expect(confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }))
      .rejects.toThrow("AI 参考资料确认弹窗不可用")

    globalThis.showModalHtml = vi.fn()
    await expect(confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }))
      .rejects.toThrow("AI 参考资料确认弹窗不可用")

    globalThis.showModalHtml = vi.fn((_title, html) => {
      document.getElementById("modal-body").innerHTML = html
      document.getElementById("modal-overlay").classList.remove("hidden")
      document.getElementById("modal-footer").innerHTML = ""
    })
    await expect(confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }))
      .rejects.toThrow("AI 参考资料确认弹窗不可用")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)

    globalThis.showModalHtml = vi.fn((_title, html) => {
      document.getElementById("modal-body").innerHTML = html
      document.getElementById("modal-overlay").classList.remove("hidden")
      throw new Error("partial failure")
    })
    await expect(confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }))
      .rejects.toThrow("AI 参考资料确认弹窗不可用")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)

    globalThis.showModalHtml = originalShow
  })

  it.each([
    ["custom cancel", () => Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "取消").click()],
    ["header close", () => document.getElementById("modal-close").click()],
    ["backdrop", () => document.getElementById("modal-overlay").click()],
    ["Escape", () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))],
  ])("%s rejects exactly once and restores the real modal lifecycle", async (_label, close) => {
    const opener = document.getElementById("opener")
    opener.focus()
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    expect(document.getElementById("writing-host").hasAttribute("inert")).toBe(true)
    expect(document.getElementById("modal-content").contains(document.activeElement)).toBe(true)
    close()
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(true)
    expect(document.activeElement).toBe(opener)
  })

  it("rejects a replaced session without affecting the replacement modal", async () => {
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    showModalHtml("后续操作", "新弹窗", [], { protectUnsaved: false })
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    expect(document.getElementById("modal-title").textContent).toBe("后续操作")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("drops a late refresh result after close without toast or modal mutation", async () => {
    let resolveConfirmation
    api.context.confirm.mockImplementation(() => new Promise((resolve) => { resolveConfirmation = resolve }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "重新整理").click()
    document.getElementById("modal-close").click()
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    showModalHtml("新弹窗", "保持不变", [], { protectUnsaved: false })
    resolveConfirmation({ id: "late", selected_asset_ids: {}, warnings: [] })
    await Promise.resolve()
    await Promise.resolve()
    expect(document.getElementById("modal-title").textContent).toBe("新弹窗")
    expect(toast).not.toHaveBeenCalledWith(expect.stringContaining("AI 参考资料"), "success")
  })

  it("rejects a pending confirm on close and does not let its late result affect a successor", async () => {
    let resolveConfirmation
    api.context.confirm.mockImplementation(() => new Promise((resolve) => { resolveConfirmation = resolve }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "确认使用").click()
    document.getElementById("modal-close").click()
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    showModalHtml("后续", "不应污染", [], { protectUnsaved: false })
    resolveConfirmation({ id: "late-confirm", selected_asset_ids: {}, warnings: [] })
    await Promise.resolve()
    await Promise.resolve()
    expect(document.getElementById("modal-title").textContent).toBe("后续")
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
  })

  it("drops a pending section exclusion after replacement and settles cancellation once", async () => {
    let resolveExclude
    api.context.confirm
      .mockResolvedValueOnce({
        id: "base", selected_asset_ids: {}, warnings: [],
        sections: [{ key: "exclude", title: "排除", can_exclude: true, status: "canonical", sources: [] }],
      })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveExclude = resolve }))
    let rejected = 0
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" }).catch((err) => {
      rejected += 1
      throw err
    })
    Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "重新整理").click()
    await vi.waitFor(() => expect(document.querySelector("[data-ai-ref-exclude-section]")).not.toBeNull())
    document.querySelector("[data-ai-ref-exclude-section]").click()
    const oldCancel = Array.from(document.querySelectorAll("#modal-footer button")).find((button) => button.textContent === "取消")
    showModalHtml("后续", "不应污染", [], { protectUnsaved: false })
    oldCancel.click()
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    expect(rejected).toBe(1)
    expect(document.getElementById("modal-overlay").classList.contains("hidden")).toBe(false)
    expect(document.getElementById("modal-title").textContent).toBe("后续")
    expect(document.getElementById("modal-body").textContent).toContain("不应污染")
    resolveExclude({ id: "late-exclude", selected_asset_ids: {}, warnings: [] })
    await Promise.resolve()
    await Promise.resolve()
    expect(document.getElementById("modal-title").textContent).toBe("后续")
  })

  it("drops a late activation-profile load after replacement", async () => {
    let resolveProfiles
    api.context.listActivationProfiles.mockImplementation(() => new Promise((resolve) => { resolveProfiles = resolve }))
    const promise = confirmAiReference({ novel_id: "p1", action: "writing.generate", task: "生成" })
    showModalHtml("新弹窗", "保持不变", [], { protectUnsaved: false })
    await expect(promise).rejects.toThrow("已取消 AI 参考资料确认")
    resolveProfiles({ items: [{ id: "profile-late", name: "晚到", version_number: 1, status: "published" }] })
    await Promise.resolve()
    await Promise.resolve()
    expect(document.getElementById("modal-title").textContent).toBe("新弹窗")
    expect(document.getElementById("modal-body").textContent).not.toContain("晚到")
  })

  it("写作确认只在作者显式选择后提交已发布 Profile", async () => {
    api.context.listActivationProfiles.mockResolvedValue({
      items: [
        { id: "profile-1", name: "场景规则", version_number: 2, status: "published" },
        { id: "draft-1", name: "未发布", version_number: 3, status: "draft" },
      ],
    })
    api.context.confirm.mockResolvedValue({ id: "confirmation-1", selected_asset_ids: {}, warnings: [] })
    confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "生成当前 Scene",
      scope: "chapter",
      chapter_index: 2,
    }).catch(() => {})
    await Promise.resolve()
    await Promise.resolve()

    const select = document.getElementById("ai-ref-activation-profile")
    expect(Array.from(select.options).map((item) => item.value)).toEqual(["", "profile-1"])
    select.value = "profile-1"
    document.querySelector("#modal-footer button")?.click()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      activation_profile_id: "profile-1",
    }))
  })

  it("渲染默认选择且不提供 Markdown textarea", () => {
    confirmAiReference({
      novel_id: "p1",
      action: "outline.generate",
      task: "剧情结构生成",
      scope: "chapter",
      chapter_index: 3,
      include_pending_objects: true,
    }).catch(() => {})

    expect(document.getElementById("modal-title")?.textContent).toBe("AI 参考资料")
    expect(document.getElementById("ai-ref-scope")?.value).toBe("chapter")
    expect(document.getElementById("ai-ref-chapter")?.value).toBe("3")
    expect(document.body.textContent).toContain("待处理内容")
    expect(document.body.textContent).not.toContain("candidate asset")
    expect(document.body.textContent).not.toContain("Markdown")
    expect(document.querySelector("#ai-ref-markdown")).toBeNull()
    expect(document.querySelector("#ai-ref-excluded")).toBeNull()
    expect(document.body.textContent).not.toContain("排除资产 ID")
  })

  it("没有章节上下文时默认使用项目范围，不回退到章节 1", () => {
    confirmAiReference({
      novel_id: "p1",
      action: "outline.generate",
      task: "空项目生成剧情",
    }).catch(() => {})

    expect(document.getElementById("ai-ref-scope")?.value).toBe("project")
    expect(document.getElementById("ai-ref-chapter")?.value).toBe("")
    expect(document.getElementById("ai-ref-include-pending")?.checked).toBe(false)
  })

  it("重新整理会提交当前选择并渲染摘要", async () => {
    api.context.confirm.mockResolvedValue({
      id: "c1",
      context_mode: "working",
      include_pending_objects: true,
      scope: "chapter",
      selected_asset_ids: { project: ["p1"], context_sections: ["project", "world"] },
      sections: [
        {
          key: "writing_objective",
          title: "本次任务",
          status: "system",
          token_count: 8,
          activation_reason: "用户当前发起的 AI 操作",
          can_exclude: false,
          truncated: false,
          sources: [],
        },
        {
          key: "retrieval_evidence_packs",
          title: "RAG 证据包",
          status: "canonical",
          token_count: 42,
          activation_reason: "RAG 命中",
          can_exclude: true,
          truncated: true,
          truncated_reason: "超过预算后按条目裁剪",
          sources: [{ type: "rag", id: "c1", label: "<script>bad</script>", status: "canonical" }],
        },
      ],
      budget_events: [
        {
          section_key: "retrieval_evidence_packs",
          event_type: "truncated",
          reason: "超过预算后按条目裁剪",
          before_tokens: 80,
          after_tokens: 42,
          tier: 2,
        },
      ],
      warnings: ["范围较大"],
      compiled_at: "2026-06-28T00:00:00Z",
    })
    confirmAiReference({
      novel_id: "p1",
      action: "world.alias_relations.extract",
      task: "别名/关系补抽",
      scope: "chapter",
      chapter_index: 1,
      scene_id: "scene-1",
      include_pending_objects: true,
    }).catch(() => {})

    document.getElementById("ai-ref-context-mode").value = "working"
    document.getElementById("ai-ref-user-note").value = "只补抽长期资产"
    document.querySelector("#modal-footer button")?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(api.context.confirm).toHaveBeenCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "world.alias_relations.extract",
      context_mode: "working",
      scene_id: "scene-1",
      include_pending_objects: true,
      user_note: "只补抽长期资产",
    }))
    expect(document.getElementById("ai-ref-summary")?.innerHTML).toContain("context_sections: 2")
    expect(document.getElementById("ai-ref-summary")?.textContent).toContain("RAG 证据包")
    expect(document.getElementById("ai-ref-summary")?.textContent).toContain("已裁剪")
    expect(document.getElementById("ai-ref-summary")?.textContent).toContain("包含待处理内容，结果需要人工检查")
    expect(document.getElementById("ai-ref-summary")?.innerHTML).not.toContain("<script>bad</script>")
    expect(document.getElementById("ai-ref-summary")?.textContent).toContain("范围较大")
  })

  it("整理参考资料期间显示明确的长任务反馈并在完成后恢复", async () => {
    let resolveConfirmation
    api.context.confirm.mockImplementation(() => new Promise((resolve) => {
      resolveConfirmation = resolve
    }))
    confirmAiReference({
      novel_id: "p1",
      action: "outline.generate",
      task: "修订剧情线",
      scope: "full",
    }).catch(() => {})

    const refreshBtn = document.querySelector("#modal-footer button")
    refreshBtn.click()

    expect(refreshBtn.disabled).toBe(true)
    expect(refreshBtn.textContent).toBe("正在整理…")

    resolveConfirmation({
      id: "c-long",
      context_mode: "canonical",
      include_pending_objects: false,
      scope: "full",
      selected_asset_ids: {},
      sections: [],
      warnings: [],
    })
    await vi.waitFor(() => expect(refreshBtn.disabled).toBe(false))
    expect(refreshBtn.textContent).toBe("重新整理")
  })

  it("character reveal 的 POV 字段在重新整理和确认使用时都不会丢失", async () => {
    api.context.confirm.mockResolvedValue({
      id: "confirm-pov",
      context_mode: "canonical",
      include_pending_objects: true,
      scope: "chapter",
      selected_asset_ids: {},
      warnings: [],
    })

    const promise = confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿",
      scope: "chapter",
      chapter_index: 2,
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: true,
      excluded_asset_ids: { manual: ["asset-1"] },
    })

    document.querySelector("#modal-footer button")?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(api.context.confirm).toHaveBeenLastCalledWith(expect.objectContaining({
      novel_id: "p1",
      action: "writing.generate",
      chapter_index: 2,
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: true,
      excluded_asset_ids: { manual: ["asset-1"] },
    }))

    document.querySelectorAll("#modal-footer button")[1].click()
    await promise

    expect(api.context.confirm).toHaveBeenLastCalledWith(expect.objectContaining({
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
      character_ids: ["char-1"],
      include_pending_objects: true,
    }))
  })

  it("显示 character reveal 新 section，且锁定 section 不提供本次排除", async () => {
    api.context.confirm.mockResolvedValue({
      id: "confirm-pov",
      context_mode: "canonical",
      include_pending_objects: true,
      scope: "chapter",
      selected_asset_ids: {
        context_sections: [
          "role_profile",
          "role_visible_knowledge",
          "scene_director_constraints",
        ],
      },
      sections: [
        {
          key: "role_profile",
          title: "POV 角色档案",
          status: "canonical",
          token_count: 10,
          activation_reason: "character reveal 的视角人物资料",
          preview: "秦岚 / 调查员",
          can_exclude: false,
          sources: [{ type: "character", id: "char-1", label: "秦岚", status: "canonical" }],
        },
        {
          key: "role_visible_knowledge",
          title: "角色可见知识",
          status: "canonical",
          token_count: 20,
          activation_reason: "CharacterKnowledge 与默认可见性规则过滤后",
          preview: "公开信息：警报响起",
          can_exclude: true,
          sources: [{ type: "entity", id: "e1", label: "主控室", status: "canonical" }],
        },
        {
          key: "scene_director_constraints",
          title: "Scene 导演约束",
          status: "director_only",
          token_count: 15,
          activation_reason: "作者约束",
          preview: "DIRECTOR_ONLY",
          can_exclude: false,
          sources: [{ type: "scene", id: "scene-1", label: "主控室警报", status: "director_only" }],
        },
      ],
      warnings: [],
    })

    confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "基于当前 Scene 的 POV 角色有限认知，生成正文候选草稿",
      scope: "chapter",
      scene_id: "scene-1",
      reveal_mode: "character",
      viewpoint_character_id: "char-1",
    }).catch(() => {})

    document.querySelector("#modal-footer button")?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    const summary = document.getElementById("ai-ref-summary")
    expect(summary?.textContent).toContain("POV 角色档案")
    expect(summary?.textContent).toContain("角色可见知识")
    expect(summary?.textContent).toContain("Scene 导演约束")
    expect(summary?.textContent).not.toContain("pov_knowledge")
    expect(summary?.textContent).not.toContain("scene_blueprint")
    expect(summary?.textContent).not.toContain("hidden truth")
    expect(document.querySelector('[data-ai-ref-exclude-section="role_profile"]')).toBeNull()
    expect(document.querySelector('[data-ai-ref-exclude-section="scene_director_constraints"]')).toBeNull()
    expect(document.querySelector('[data-ai-ref-exclude-section="role_visible_knowledge"]')).not.toBeNull()
  })

  it("点击 section 本次排除后重新整理并提交 context_sections 排除项", async () => {
    api.context.confirm
      .mockResolvedValueOnce({
        id: "c1",
        context_mode: "canonical",
        include_pending_objects: false,
        scope: "full",
        selected_asset_ids: { context_sections: ["writing_objective", "retrieval_evidence_packs"] },
        sections: [
          {
            key: "writing_objective",
            title: "本次任务",
            status: "system",
            token_count: 8,
            activation_reason: "用户当前发起的 AI 操作",
            can_exclude: false,
            truncated: false,
            sources: [],
          },
          {
            key: "retrieval_evidence_packs",
            title: "RAG 证据包",
            status: "canonical",
            token_count: 42,
            activation_reason: "RAG 命中",
            can_exclude: true,
            truncated: false,
            sources: [],
          },
        ],
        warnings: [],
      })
      .mockResolvedValueOnce({
        id: "c2",
        context_mode: "canonical",
        include_pending_objects: false,
        scope: "full",
        selected_asset_ids: { context_sections: ["writing_objective"] },
        sections: [
          {
            key: "writing_objective",
            title: "本次任务",
            status: "system",
            token_count: 8,
            activation_reason: "用户当前发起的 AI 操作",
            can_exclude: false,
            truncated: false,
            sources: [],
          },
        ],
        warnings: [],
      })

    confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "生成正文候选草稿",
      scope: "full",
    }).catch(() => {})

    document.querySelector("#modal-footer button")?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    document.querySelector('[data-ai-ref-exclude-section="retrieval_evidence_packs"]')?.click()
    await Promise.resolve()
    await Promise.resolve()
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(api.context.confirm).toHaveBeenLastCalledWith(expect.objectContaining({
      excluded_asset_ids: {
        context_sections: ["retrieval_evidence_packs"],
      },
    }))
    expect(document.getElementById("ai-ref-summary")?.textContent).not.toContain("RAG 证据包")
    expect(document.activeElement).toBe(document.getElementById("ai-ref-summary"))
  })

  it("确认使用返回 context_confirmation_id 来源记录", async () => {
    api.context.confirm.mockResolvedValue({
      id: "confirm-1",
      context_mode: "canonical",
      include_pending_objects: false,
      scope: "full",
      selected_asset_ids: {},
      warnings: [],
    })
    const promise = confirmAiReference({
      novel_id: "p1",
      action: "writing.generate",
      task: "生成正文候选草稿",
      scope: "full",
    })

    const buttons = document.querySelectorAll("#modal-footer button")
    buttons[1].click()
    const result = await promise

    expect(result.id).toBe("confirm-1")
    expect(document.getElementById("modal-overlay")?.classList.contains("hidden")).toBe(true)
  })

  it("参考资料确认超时时显示可重试提示而不是后端不可用", async () => {
    api.context.confirm.mockRejectedValue(new Error("请求超时，请检查后端服务是否运行"))
    confirmAiReference({
      novel_id: "p1",
      action: "writing.conflict_check.ai_review",
      task: "writing conflict AI review",
      scope: "project",
    }).catch(() => {})

    document.querySelectorAll("#modal-footer button")[1].click()

    await vi.waitFor(() => {
      expect(document.getElementById("ai-ref-error")?.textContent).toContain("AI 参考资料整理超时")
    })
    expect(document.getElementById("ai-ref-error")?.textContent).not.toContain("检查后端服务")
  })
})
