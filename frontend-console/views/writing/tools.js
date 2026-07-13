/**
 * 写作台工具模块
 *
 * 负责工具栏菜单、导出、断章、AI 生成草稿等工具类操作。
 */

import { confirmAiReference } from "../../shared/aiReferenceModal.js"
import { findCurrentScene as locateCurrentScene } from "../../shared/sceneLocator.js"

export function createWritingTools({
  state,
  api,
  toast,
  modal,
  esc,
  editor,
  onInsertText,
  onRefresh,
}) {
  const projectState = state
  const modalApi = modal
  const escapeHtml = esc

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function renderToolsMenu(hasSelection) {
    const disabled = hasSelection && !projectState._isReadonly ? "" : "disabled"
    const disabledTitle = hasSelection ? "当前版本只读，需基于此版本创建后再使用" : "请先选择章节"
    return `
      <details class="writing-tools-menu">
        <summary class="btn btn-sm">AI 工具</summary>
        <div class="writing-tools-menu__body">
          <div class="writing-tools-menu__group">
            <strong>生成</strong>
            <button class="btn btn-sm" data-action="ai-generate-draft" ${disabled} title="${disabled ? escapeHtml(disabledTitle) : "基于上下文生成正文建议"}">AI 正文建议</button>
            <button class="btn btn-sm" data-action="ai-generate-pov-draft" ${disabled} title="${disabled ? escapeHtml(disabledTitle) : "基于当前 Scene 的 POV 角色有限认知生成正文建议"}">AI 角色视角建议</button>
          </div>
          ${currentProjectId() ? `<div class="writing-tools-menu__group">
            <strong>提取</strong>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="scenes">场景（scene）自动提取</button>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="world_objects">世界对象与别名/关系自动提取</button>
            <button class="btn btn-sm" data-action="auto-extract-stage" data-stage="plot_structure">剧情线自动提取</button>
            ${(projectState._chapterList || []).length > 0 ? `<button class="btn btn-sm" data-action="extract-cards">从正文整理 Scene</button>` : ""}
          </div>` : ""}
          <div class="writing-tools-menu__group">
            <strong>检查</strong>
            <span class="writing-tools-menu__hint">剧情设定冲突检查在编辑器顶部执行。</span>
            ${findCurrentScene() && projectState._currentChapter ? `<button class="btn btn-sm" data-action="split-scene">断章至此</button>` : ""}
          </div>
          ${currentProjectId() ? `<div class="writing-tools-menu__group">
            <strong>地图</strong>
            <button class="btn btn-sm" data-action="open-map">打开地图</button>
          </div>` : ""}
        </div>
      </details>
    `
  }

  function findCurrentScene() {
    const offset = typeof editor?.getCursorOffset === "function"
      ? editor.getCursorOffset()
      : (projectState._cursorOffset || 0)
    return locateCurrentScene({
      scenes: projectState._scenes,
      chapterIndex: projectState._currentChapter,
      cursorOffset: offset,
    })
  }

  function bindEvents(container) {
    container.querySelectorAll('[data-action="export-chapter"]').forEach((btn) => {
      btn.addEventListener("click", () => exportChapter())
    })
    container.querySelectorAll('[data-action="ai-generate-draft"]').forEach((btn) => {
      btn.addEventListener("click", () => generateDraft())
    })
    container.querySelectorAll('[data-action="ai-generate-pov-draft"]').forEach((btn) => {
      btn.addEventListener("click", () => generatePovDraft())
    })
    container.querySelectorAll('[data-action="split-scene"]').forEach((btn) => {
      btn.addEventListener("click", () => showSplitSceneForm())
    })
  }

  function exportChapter() {
    const title = projectState._currentTitle || `第 ${projectState._currentChapter} 章`
    const content = (typeof editor?.getContent === "function" ? editor.getContent() : projectState._currentContent) || ""
    const text = `${title}\n\n${content}`
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${title.replace(/[\\/:*?"<>|]/g, "")}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast(`已导出「${title}」`, "success")
  }

  async function showSplitSceneForm() {
    if (projectState._isReadonly) {
      toast("当前内容只读；待处理建议需先采用到工作稿", "warning")
      return
    }
    const currentChapter = projectState._currentChapter
    if (!currentChapter) { toast("请先选择章节", "warning"); return }
    const currentScene = findCurrentScene()
    if (!currentScene) { toast("当前章节未关联 Scene", "warning"); return }

    const content = (typeof editor?.getContent === "function" ? editor.getContent() : projectState._currentContent) || ""
    const cursorPos = typeof editor?.getCursorOffset === "function"
      ? editor.getCursorOffset()
      : (document.getElementById("writing-editor")?.selectionStart || 0)
    const contentLength = content.length

    if (contentLength < 2) {
      toast("当前章节内容太短，无法断章", "warning")
      return
    }

    const html = `
      <div class="form-group">
        <label>断章位置（字符 offset）</label>
        <input class="form-input" id="split-pos" type="number" min="1" max="${Math.max(1, contentLength - 1)}" value="${cursorPos}" />
      </div>
      <div class="form-group">
        <label>当前 Scene：${escapeHtml(currentScene.title || "未命名")}</label>
      </div>
      <p class="writing-form-hint">
        从当前章节的指定 offset 处切分为新章节，并同步更新 Scene chunk。
      </p>
    `
    modalApi.showModalHtml("断章", html, [{
      text: "确认断章", class: "btn-primary",
      handler: async () => {
        const splitPos = parseInt(document.getElementById("split-pos")?.value || "", 10)
        if (!splitPos || splitPos < 1) { toast("请输入有效的断章位置", "warning"); return }
        if (splitPos >= contentLength) { toast("断章位置必须小于正文长度", "warning"); return }
        modalApi.closeModal()
        await splitScene(splitPos, currentChapter, currentScene)
      },
    }])
  }

  async function splitScene(splitPos, currentChapter, currentScene) {
    const projectId = currentProjectId()
    try {
      const result = await api.writing.splitChapter(
        currentChapter,
        { split_pos: splitPos, source_scene_id: currentScene.id },
        projectId,
      )
      toast("断章完成", "success")
      onRefresh?.(result)
    } catch (err) {
      toast(err.message || "断章失败", "error")
    }
  }

  async function generateDraft() {
    const projectId = currentProjectId()
    const currentChapter = projectState._currentChapter
    if (!projectId || !currentChapter) {
      toast("请先选择章节", "warning")
      return
    }
    if (projectState._isReadonly) {
      toast("当前内容只读；待处理建议不会作为工作稿参考", "warning")
      return
    }
    try {
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "writing.generate",
        task: "生成正文建议预览",
        scope: "chapter",
        chapter_index: currentChapter,
        include_pending_objects: false,
      })
      const result = await api.writing.generate({
        novel_id: projectId,
        chapter_index: currentChapter,
        title: projectState._currentTitle || `第 ${currentChapter} 章`,
        instruction: confirmation.user_note || "",
        context_confirmation_id: confirmation.id,
      })
      toast(`AI 正文建议任务已提交：${result.task_id || result.id || ""}`, "success")
    } catch (err) {
      if (err.message && err.message.includes("取消")) return
      toast(err.message || "AI 正文建议生成失败", "error")
    }
  }

  async function generatePovDraft() {
    const projectId = currentProjectId()
    const currentChapter = projectState._currentChapter
    if (!projectId || !currentChapter) {
      toast("请先选择章节", "warning")
      return
    }
    if (projectState._isReadonly) {
      toast("当前内容只读；待处理建议不会作为工作稿参考", "warning")
      return
    }

    const currentScene = findCurrentScene()
    if (!currentScene) {
      toast("当前章节未关联 Scene", "warning")
      return
    }

    const viewpointCharacterId = currentScene.pov_character_id
    if (!viewpointCharacterId) {
      toast("当前 Scene 未设置 POV 角色", "warning")
      return
    }

    const povInstruction = [
      "请从当前 Scene 的 POV 角色有限认知出发生成正文建议。",
      "用户指令是作者意图，不等于角色知识。",
      "角色判断、台词、内心和行动只能使用确认上下文中该角色可见的信息。",
    ].join("\n")

    try {
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "writing.generate",
        task: "基于当前 Scene 的 POV 角色有限认知，生成正文建议预览",
        scope: "chapter",
        chapter_index: currentChapter,
        scene_id: currentScene.id,
        reveal_mode: "character",
        viewpoint_character_id: viewpointCharacterId,
        character_ids: [viewpointCharacterId],
        include_pending_objects: false,
      })
      const userNote = confirmation.user_note ? `${confirmation.user_note}\n\n` : ""
      const result = await api.writing.generate({
        novel_id: projectId,
        chapter_index: currentChapter,
        title: projectState._currentTitle || `第 ${currentChapter} 章`,
        instruction: `${userNote}${povInstruction}`,
        context_confirmation_id: confirmation.id,
      })
      toast(`AI 角色视角建议任务已提交：${result.task_id || result.id || ""}`, "success")
    } catch (err) {
      if (err.message && err.message.includes("取消")) return
      toast(err.message || "AI 角色视角建议生成失败", "error")
    }
  }

  function dispose() {
    // 无持久化资源
  }

  return {
    renderToolsMenu,
    bindEvents,
    exportChapter,
    splitScene,
    generateDraft,
    generatePovDraft,
    dispose,
  }
}
