/**
 * 移动端速记模块
 *
 * 负责在移动视口下渲染简化速记界面与保存。
 */

export function createMobileQuickNote({ state, api, toast, esc, editor, onSaved }) {
  const projectState = state
  const escapeHtml = esc

  function currentProjectId() {
    return projectState.currentProjectId
  }

  function shouldRender() {
    return typeof window !== "undefined"
      && window.innerWidth < 600
      && projectState._currentChapter !== null
      && !projectState._isReadonly
      && !projectState._forceDesktopMode
      && !document.body.classList.contains("force-desktop")
  }

  function render() {
    const currentText = projectState._currentContent || ""
    return `
      <div class="mobile-quick-note">
        <div class="mobile-note-header">
          <span class="mobile-note-chapter">第 ${escapeHtml(projectState._currentChapter)} 章</span>
          <span class="mobile-note-wc" id="mobile-note-wc">${escapeHtml(currentText.length.toLocaleString())} 字</span>
        </div>
        <textarea id="mobile-note-editor" class="mobile-note-editor" placeholder="在此记录灵感...">${escapeHtml(currentText)}</textarea>
        <div class="mobile-note-actions">
          <button class="btn btn-primary" data-action="save-mobile-note">保存为工作稿</button>
          <button class="btn btn-ghost" data-action="switch-desktop-mode">完整编辑器</button>
        </div>
      </div>
    `
  }

  async function save() {
    const editor = document.getElementById("mobile-note-editor")
    const currentChapter = projectState._currentChapter
    if (!editor || currentChapter == null) return
    const content = editor.value
    const title = projectState._currentTitle || `第 ${currentChapter} 章`
    try {
      let savedInfo
      if (projectState._currentDraftId) {
        const result = await api.writing.autosave(
          projectState._currentDraftId,
          {
            title,
            content,
            expected_version: projectState._currentVersionNumber,
            expected_updated_at: projectState._currentUpdatedAt,
          },
          currentProjectId(),
        )
        if (result?.id && result.id !== projectState._currentDraftId) {
          projectState._currentDraftId = result.id
        }
        savedInfo = {
          draftId: projectState._currentDraftId,
          versionNumber: result.version_number,
          updatedAt: result.updated_at || projectState._currentUpdatedAt,
          content,
          title,
          lastSavedContent: content,
        }
      } else {
        const created = await api.writing.autosaveDraftOnly({
          novel_id: currentProjectId(),
          chapter_index: currentChapter,
          title,
          content,
        })
        savedInfo = {
          draftId: created.id,
          versionNumber: created.version_number,
          updatedAt: created.updated_at || null,
          content,
          title,
          lastSavedContent: content,
        }
      }
      editor?.setState?.(savedInfo)
      onSaved?.()
      toast("已保存到工作稿", "success")
    } catch (err) {
      toast(err.message || "移动记录保存失败，已保留本地暂存", "error")
    }
  }

  function bindEvents(container) {
    const mobileEditor = container.querySelector("#mobile-note-editor")
    if (mobileEditor) {
      mobileEditor.oninput = () => {
        const count = mobileEditor.value.length
        const countEl = container.querySelector("#mobile-note-wc")
        if (countEl) countEl.textContent = `${count.toLocaleString()} 字`
      }
    }
    container.querySelectorAll('[data-action="save-mobile-note"]').forEach((btn) => {
      btn.onclick = () => save()
    })
  }

  function dispose() {
    // 无持久化资源
  }

  return {
    shouldRender,
    render,
    bindEvents,
    dispose,
  }
}
