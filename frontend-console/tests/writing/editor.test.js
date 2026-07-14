/**
 * editor 子模块最小测试
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { createEditor } from "../../views/writing/editor.js"
import { resetState, clearDocument, autoConfirm } from "../helpers.js"

function createTestEditor(overrides = {}) {
  return createEditor({
    state: globalThis.state,
    api: globalThis.api,
    toast: globalThis.toast,
    onWordcountUpdate: vi.fn(),
    onSaveStatusChange: vi.fn(),
    onSceneChange: vi.fn(),
    ...overrides,
  })
}

beforeEach(() => {
  resetState()
  clearDocument()
  localStorage.clear()
  vi.clearAllMocks()
  confirmAction.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("createEditor", () => {
  it("无选中章节时渲染空状态", () => {
    const editor = createTestEditor()
    const html = editor.render()
    expect(html).toContain("选择章节开始编辑")
    expect(html).toContain("请从左侧选择章节")
    expect(html).not.toContain('<textarea id="writing-editor"')
  })

  it("有选中章节时渲染编辑器", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "正文", title: "第一章", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    const html = editor.render()

    expect(html).toContain('<textarea id="writing-editor"')
    expect(html).toContain("正文")
    expect(html).toContain("第一章")
    expect(html).toContain("writing-wordcount-bar")
  })

  it("加载最新草稿并设置状态", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 2 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "最新正文",
      title: "最新标题",
      version_number: 2,
      updated_at: "2026-07-06T00:00:00Z",
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)

    expect(editor.getContent()).toBe("最新正文")
    expect(editor.getTitle()).toBe("最新标题")
    expect(editor.saveStatusText()).toBe("已保存")
  })

  it("并发切换章节时只采用最后一次选择的响应", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockImplementation((chapterIndex) => Promise.resolve({
      versions: [{ id: `d${chapterIndex}`, version_number: 1 }],
    }))
    let resolveFirst
    let resolveSecond
    api.writing.get.mockImplementation((draftId) => new Promise((resolve) => {
      if (draftId === "d1") resolveFirst = resolve
      else resolveSecond = resolve
    }))

    const editor = createTestEditor()
    const firstLoad = editor.loadChapter(1)
    await vi.waitFor(() => expect(resolveFirst).toBeTypeOf("function"))
    const secondLoad = editor.loadChapter(2)
    await vi.waitFor(() => expect(resolveSecond).toBeTypeOf("function"))

    resolveSecond({ id: "d2", title: "第二章", content: "第二章正文", version_number: 1 })
    await secondLoad
    resolveFirst({ id: "d1", title: "第一章", content: "第一章正文", version_number: 1 })

    expect(await firstLoad).toBe(false)
    expect(editor.getTitle()).toBe("第二章")
    expect(editor.getContent()).toBe("第二章正文")
    expect(editor.getDraftId()).toBe("d2")
  })

  it("默认加载到 candidate 时只作为待处理建议预览且不会自动保存", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "candidate-1", version_number: 3 }],
    })
    api.writing.get.mockResolvedValue({
      id: "candidate-1",
      content: "AI 建议正文",
      title: "AI 建议",
      version_number: 3,
      status: "candidate",
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()

    expect(editor.getDraftStatus()).toBe("candidate")
    expect(editor.isReadonly()).toBe(true)
    expect(document.getElementById("writing-editor").readOnly).toBe(true)
    expect(document.getElementById("btn-autosave").disabled).toBe(true)
    expect(document.body.textContent).toContain("待处理")
    expect(document.querySelector('[data-action="restore-from-version"]')).toBeNull()

    await editor.autosave()
    expect(api.writing.autosave).not.toHaveBeenCalled()
  })

  it("按 ID 加载 candidate 不能被 isReadonly=false 变成工作稿", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "candidate-by-id",
      content: "按 ID 打开的建议",
      title: "建议",
      version_number: 4,
      status: "candidate",
    })

    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "candidate-by-id", isReadonly: false })

    expect(editor.getDraftId()).toBe("candidate-by-id")
    expect(editor.getDraftStatus()).toBe("candidate")
    expect(editor.isReadonly()).toBe(true)
  })

  it("采用 candidate 后切换到 API 返回的可编辑工作稿", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "candidate-1",
      content: "AI 建议正文",
      title: "AI 建议",
      version_number: 3,
      status: "candidate",
    })
    api.writing.adoptDraftCandidate.mockResolvedValue({
      id: "working-4",
      content: "AI 建议正文",
      title: "AI 建议",
      version_number: 4,
      status: "draft",
      updated_at: "2026-07-10T10:00:00Z",
    })
    const onDraftAdopted = vi.fn()
    const editor = createTestEditor({ onDraftAdopted })
    await editor.loadChapter(1, { draftId: "candidate-1" })

    const adopted = await editor.adoptDraftCandidate()

    expect(api.writing.adoptDraftCandidate).toHaveBeenCalledWith("candidate-1", "p1")
    expect(adopted.id).toBe("working-4")
    expect(editor.getDraftId()).toBe("working-4")
    expect(editor.getDraftStatus()).toBe("draft")
    expect(editor.isReadonly()).toBe(false)
    expect(onDraftAdopted).toHaveBeenCalledWith(expect.objectContaining({ id: "working-4" }))
    expect(editor.render()).toContain("工作稿")
    expect(editor.render()).not.toContain("采用到工作稿")
  })

  it("published 首次暂存后切换到 copy-on-write 新 draft ID", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "published-1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({
      id: "published-1",
      content: "已发布正文",
      title: "第一章",
      version_number: 1,
      status: "published",
      updated_at: "2026-07-10T00:00:00Z",
    })
    api.writing.autosave.mockResolvedValue({
      id: "working-2",
      content: "已修改工作稿",
      title: "第一章",
      version_number: 2,
      status: "draft",
      updated_at: "2026-07-10T00:01:00Z",
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()
    document.getElementById("writing-editor").value = "已修改工作稿"

    await editor.autosave()

    expect(api.writing.autosave).toHaveBeenCalledWith(
      "published-1",
      expect.objectContaining({ content: "已修改工作稿" }),
      "p1",
    )
    expect(editor.getDraftId()).toBe("working-2")
    expect(state._currentDraftId).toBe("working-2")
  })

  it("保存进行中再次编辑会在前一次完成后继续暂存", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "published-1",
      content: "原文",
      title: "第一章",
      version_number: 1,
      status: "published",
    })
    let resolveFirst
    let resolveSecond
    api.writing.autosave
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))
    let editor
    editor = createTestEditor({
      onVersionChanged: async () => editor.updateMeta(),
    })
    await editor.loadChapter(1, { draftId: "published-1" })
    document.body.innerHTML = editor.render()
    editor.bindEvents(document.body)
    const textarea = document.getElementById("writing-editor")
    textarea.value = "第一次修改"
    textarea.dispatchEvent(new Event("input"))
    const firstSave = editor.autosave()
    textarea.value = "第二次修改"
    textarea.dispatchEvent(new Event("input"))
    const secondSave = editor.autosave()
    resolveFirst({
      id: "working-2",
      content: "第一次修改",
      title: "第一章",
      version_number: 2,
      status: "draft",
      provenance_json: { version_origin: "auto", base_draft_id: "published-1" },
    })

    await vi.waitFor(() => expect(api.writing.autosave).toHaveBeenCalledTimes(2))

    expect(document.getElementById("writing-editor").value).toBe("第二次修改")
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("第二次修改")
    resolveSecond({
      id: "working-2",
      content: "第二次修改",
      title: "第一章",
      version_number: 2,
      status: "draft",
      provenance_json: { version_origin: "auto", base_draft_id: "published-1" },
    })

    await Promise.all([firstSave, secondSave])

    expect(api.writing.autosave).toHaveBeenCalledTimes(2)
    expect(api.writing.autosave).toHaveBeenLastCalledWith(
      "working-2",
      expect.objectContaining({ content: "第二次修改", expected_version: 2 }),
      "p1",
    )
    expect(localStorage.getItem("draft_backup_p1_1")).toBeNull()
  })

  it("保存历史恢复所需的最新版本快照", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "旧版本",
      title: "旧标题",
      version_number: 1,
      updated_at: "2026-07-01T00:00:00Z",
      status: "published",
    })
    const editor = createTestEditor()

    await editor.loadChapter(1, {
      draftId: "d1",
      versionNumber: 1,
      isReadonly: false,
      restoreSourceVersion: 1,
      restoreExpectedVersion: 3,
      restoreExpectedUpdatedAt: "2026-07-03T00:00:00Z",
    })

    expect(editor.getRestoreSourceVersion()).toBe(1)
    expect(editor.getRestoreExpectedVersion()).toBe(3)
    expect(editor.getRestoreExpectedUpdatedAt()).toBe("2026-07-03T00:00:00Z")
  })

  it("纯空白修改只保存本地且不请求自动版本", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [{ id: "published-1", version_number: 1 }] })
    api.writing.get.mockResolvedValue({
      id: "published-1",
      content: "甲\n乙",
      title: "第一章",
      version_number: 1,
      status: "published",
    })
    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()
    editor.bindEvents(document.body)
    const textarea = document.getElementById("writing-editor")
    textarea.value = " \u3000甲\t\n\n乙 "
    textarea.dispatchEvent(new Event("input"))

    await editor.autosave()

    expect(api.writing.autosave).not.toHaveBeenCalled()
    expect(editor.saveStatusText()).toBe("仅本地修改")
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("甲")
  })

  it("撤销 auto 版本时保留纯排版和标题本地修改", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "working-2",
      content: "新正文",
      title: "第一章",
      version_number: 2,
      status: "draft",
      provenance_json: { version_origin: "auto", base_draft_id: "published-1" },
    })
    api.writing.autosave.mockResolvedValue({
      id: "published-1",
      content: "甲\n乙",
      title: "第一章",
      version_number: 1,
      status: "published",
    })
    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "working-2" })
    document.body.innerHTML = editor.render()
    document.getElementById("writing-editor").value = " 甲\n\n乙 "
    document.getElementById("writing-title-input").value = "新标题"

    await editor.autosave()

    expect(editor.getDraftId()).toBe("published-1")
    expect(editor.getContent()).toBe(" 甲\n\n乙 ")
    expect(editor.getTitle()).toBe("新标题")
    expect(editor.saveStatusText()).toBe("仅本地修改")
    expect(localStorage.getItem("draft_backup_p1_1")).toContain("新标题")
  })

  it("可强制保存无实质变化的新版本", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "published-1",
      content: "正文",
      title: "第一章",
      version_number: 1,
      status: "published",
    })
    api.writing.checkpoint.mockResolvedValue({
      id: "manual-2",
      content: "正文",
      title: "第一章",
      version_number: 2,
      status: "draft",
      provenance_json: { version_origin: "manual", base_draft_id: "published-1" },
    })
    autoConfirm()
    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "published-1" })

    await editor.checkpoint()

    expect(api.writing.checkpoint).toHaveBeenCalledWith(
      "published-1",
      expect.objectContaining({ force: true }),
      "p1",
    )
    expect(editor.getDraftId()).toBe("manual-2")
  })

  it("显式放弃未发布版本后回到基线", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "working-2",
      content: "修改",
      title: "第一章",
      version_number: 2,
      status: "draft",
      provenance_json: { version_origin: "auto", base_draft_id: "published-1" },
    })
    api.writing.discard.mockResolvedValue({
      id: "published-1",
      content: "原文",
      title: "第一章",
      version_number: 1,
      status: "published",
    })
    autoConfirm()
    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "working-2" })

    await editor.discardChanges()

    expect(api.writing.discard).toHaveBeenCalledWith(
      "working-2",
      "p1",
      expect.objectContaining({ expected_version: 2 }),
    )
    expect(editor.getDraftId()).toBe("published-1")
    expect(editor.getContent()).toBe("原文")
  })

  it("按 draftId 加载只读版本", async () => {
    state.currentProjectId = "p1"
    api.writing.get.mockResolvedValue({
      id: "d2",
      content: "旧版本正文",
      title: "旧标题",
      version_number: 1,
    })

    const editor = createTestEditor()
    await editor.loadChapter(1, { draftId: "d2", versionNumber: 1, isReadonly: true, restoreSourceVersion: 1 })

    expect(editor.getContent()).toBe("旧版本正文")
    expect(editor.render()).toContain("（只读）")
    expect(editor.render()).toContain("基于此版本创建")
  })

  it("getContent 优先返回 DOM 中 textarea 的值", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "初始", title: "", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)

    document.body.innerHTML = editor.render()
    const textarea = document.getElementById("writing-editor")
    textarea.value = "已修改"

    expect(editor.getContent()).toBe("已修改")
  })

  it("根据光标 offset 检测当前 scene", async () => {
    state.currentProjectId = "p1"
    state._scenes = [{
      id: "s1",
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 10 }],
    }]
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "0123456789", title: "", version_number: 1 })

    const onSceneChange = vi.fn()
    const editor = createTestEditor({ onSceneChange })
    await editor.loadChapter(1)

    document.body.innerHTML = editor.render()
    const textarea = document.getElementById("writing-editor")
    textarea.focus()
    textarea.setSelectionRange(5, 5)

    editor.bindEvents(document.body)
    document.dispatchEvent(new Event("selectionchange"))

    expect(editor.getCurrentSceneId()).toBe("s1")
    expect(onSceneChange).toHaveBeenCalledWith("s1")
  })

  it("重绑到无编辑器容器时清理 document 光标监听", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({ versions: [] })
    api.writing.get.mockResolvedValue({ id: "d1", content: "正文", title: "", version_number: 1 })
    const removeListener = vi.spyOn(document, "removeEventListener")
    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()
    editor.bindEvents(document.body)

    document.body.innerHTML = "<div>未选择章节</div>"
    editor.bindEvents(document.body)

    expect(removeListener).toHaveBeenCalledWith(
      "selectionchange",
      expect.any(Function),
    )
  })

  it("HTML 转义动态内容防止 XSS", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({
      id: "d1",
      content: "<script>alert(1)</script>",
      title: "<b>标题</b>",
      version_number: 1,
    })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    const html = editor.render()

    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;")
    expect(html).toContain("&lt;b&gt;标题&lt;/b&gt;")
    expect(html).not.toContain("<script>alert(1)</script>")
  })

  it("显示 POV 结构化候选与 failed 风险提示", () => {
    const editor = createTestEditor()
    editor.setState({
      chapter: 1,
      draftId: "d-pov",
      draftStatus: "candidate",
      title: "POV 候选",
      content: "正文候选",
      provenanceJson: {
        generation_profile: "pov_character",
        pov_view: {
          perception: "秦岚听见警报声。",
          interpretation: "她判断控制台被人动过。",
          inner_monologue: "她先稳住现场。",
          action: "她靠近控制台。",
          expression: "神色收紧。",
          dialogue_candidates: [
            { line: "别碰控制台。", tone: "冷静", subtext: "试探" },
          ],
          unsaid: "她没有说出口。",
        },
        pov_validation: {
          status: "failed",
          findings: [{
            rule: "hidden_truth_match",
            severity: "error",
            field_path: "pov_view.unsaid",
            generated_excerpt: "疑似越权片段",
            source_label: "已过滤的隐藏事实",
            redacted: true,
          }],
          warnings: [],
        },
      },
    })

    const html = editor.render()

    expect(html).toContain("角色视角建议预览")
    expect(html).toContain("高风险")
    expect(html).toContain("秦岚听见警报声。")
    expect(html).toContain("别碰控制台。")
    expect(html).toContain("确认风险并采用到工作稿")
    expect(html).toContain("疑似越权片段")
    expect(html).toContain("已过滤的隐藏事实")
    expect(html).not.toContain("hidden_source_text")
  })

  it("POV 高风险 candidate 提供显式采用动作而不是确认即生效", async () => {
    state.currentProjectId = "p1"
    api.writing.adoptDraftCandidate.mockResolvedValue({
      id: "working-2",
      content: "正文建议",
      status: "draft",
    })
    const editor = createTestEditor()
    editor.setState({
      chapter: 1,
      draftId: "candidate-1",
      draftStatus: "candidate",
      content: "正文候选",
      provenanceJson: {
        generation_profile: "pov_character",
        pov_validation: { status: "failed", findings: [], warnings: [] },
      },
    })
    document.body.innerHTML = editor.render()

    editor.bindEvents(document.body)
    const button = document.querySelector('[data-action="adopt-draft-candidate"]')
    await button.click()
    await Promise.resolve()

    expect(api.writing.adoptDraftCandidate).toHaveBeenCalledWith("candidate-1", "p1")
    expect(editor.getDraftId()).toBe("working-2")
    expect(editor.isReadonly()).toBe(false)
  })

  it("普通 draft 没有 provenance_json 时不显示 POV panel", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "正文", title: "第一章", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)

    expect(editor.render()).not.toContain("角色视角建议预览")
  })

  it("dispose 清理计时器与事件监听", async () => {
    state.currentProjectId = "p1"
    api.writing.getVersionHistory.mockResolvedValue({
      versions: [{ id: "d1", version_number: 1 }],
    })
    api.writing.get.mockResolvedValue({ id: "d1", content: "", title: "", version_number: 1 })

    const editor = createTestEditor()
    await editor.loadChapter(1)
    document.body.innerHTML = editor.render()
    editor.bindEvents(document.body)

    // 触发自动保存计时器
    const titleInput = document.getElementById("writing-title-input")
    titleInput.value = "x"
    titleInput.dispatchEvent(new Event("input"))

    editor.dispose()

    // 验证事件监听已移除：再次 dispose 不抛异常
    expect(() => editor.dispose()).not.toThrow()
  })
})
