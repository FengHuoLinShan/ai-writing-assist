/**
 * 章节版本管理器
 *
 * 负责版本历史加载、版本选择器渲染、版本切换/恢复/删除。
 * 从 writingView.js 拆分，便于独立测试。
 */

import { confirmAsync } from "../../shared/confirmAsync.js"

export function createVersionManager({ state, api, toast, modal, esc, onSwitch }) {
  let _versions = []
  let _currentChapter = null
  let _currentDraftId = null
  let _currentVersionNumber = null

  async function load(chapterIndex) {
    _currentChapter = chapterIndex
    _currentDraftId = null
    _currentVersionNumber = null
    try {
      const history = await api.writing.getVersionHistory(chapterIndex, state.currentProjectId)
      _versions = history.versions || []
      if (_versions.length > 0) {
        _currentVersionNumber = _versions[0].version_number
      }
    } catch (err) {
      _versions = []
      toast("版本历史加载失败：" + (err.message || "未知错误"), "error")
    }
  }

  function render() {
    if (!_currentChapter || _versions.length === 0) return ""

    let html = `
      <div class="writing-version-bar">
        <span class="writing-version-label">版本：</span>
        <span class="writing-version-select-wrap">
          <select id="version-selector" class="writing-version-select" aria-label="选择章节版本">
    `

    for (const v of _versions) {
      const selected = v.version_number === _currentVersionNumber
      const isCurLatest = v.version_number === _versions[0]?.version_number
      const stateLabel = v.status === "published"
        ? "已发布"
        : (v.version_origin === "manual" ? "手动保存" : "未发布")
      html += `<option value="${esc(v.id)}" data-version="${esc(v.version_number)}" data-latest="${isCurLatest ? 1 : 0}" ${selected ? "selected" : ""}>v${esc(v.version_number)}${isCurLatest ? " (最新)" : ""} · ${stateLabel}</option>`
    }

    html += `
          </select>
        </span>
        <button class="btn btn-sm writing-btn-compact" data-action="version-history" title="版本历史">历史</button>
        <button class="btn btn-sm writing-version-delete" id="btn-delete-version" data-action="delete-version" title="删除当前版本" aria-label="删除当前版本">🗑</button>
        <span id="publish-status-dot" class="publish-status-dot" title="发布任务进行中"></span>
      </div>
    `
    return html
  }

  function bindEvents(container) {
    const versionSelector = container.querySelector("#version-selector")
    if (versionSelector) {
      versionSelector.onchange = () => {
        const opt = versionSelector.options[versionSelector.selectedIndex]
        const draftId = opt.value
        const versionNumber = parseInt(opt.getAttribute("data-version"), 10)
        const isLatest = opt.getAttribute("data-latest") === "1"
        switchVersion(draftId, versionNumber, isLatest)
      }
    }

    const historyBtn = container.querySelector('[data-action="version-history"]')
    if (historyBtn) {
      historyBtn.onclick = () => showVersionHistory()
    }

    const deleteBtn = container.querySelector('[data-action="delete-version"]')
    if (deleteBtn) {
      deleteBtn.onclick = () => deleteVersion()
    }
  }

  async function switchVersion(draftId, versionNumber, isLatest, options = {}) {
    try {
      const draftData = await api.writing.get(draftId, state.currentProjectId)
      _currentDraftId = draftData.id
      _currentVersionNumber = versionNumber
      const latest = _versions[0] || null
      onSwitch({
        draftId: draftData.id,
        versionNumber,
        isReadonly: options.isReadonly !== undefined ? options.isReadonly : !isLatest,
        restoreSourceVersion: options.restoreSourceVersion !== undefined ? options.restoreSourceVersion : (isLatest ? null : versionNumber),
        restoreExpectedVersion: isLatest ? null : (latest?.version_number || null),
        restoreExpectedUpdatedAt: isLatest ? null : (latest?.updated_at || null),
        title: draftData.title || "",
        content: draftData.content || "",
        updatedAt: draftData.updated_at || null,
      })
      if (isLatest) {
        toast(`已恢复至 v${versionNumber}`, "success")
      }
    } catch (err) {
      toast("切换版本失败：" + (err.message || "未知错误"), "error")
    }
  }

  async function restoreFromVersion() {
    if (!_currentVersionNumber) return
    onSwitch({
      draftId: _currentDraftId,
      versionNumber: _currentVersionNumber,
      isReadonly: false,
      restoreSourceVersion: _currentVersionNumber,
      restoreExpectedVersion: _versions[0]?.version_number || null,
      restoreExpectedUpdatedAt: _versions[0]?.updated_at || null,
    })
    toast("已创建新版本，可继续编辑", "success")
  }

  async function deleteVersion() {
    if (!_currentDraftId || !_currentChapter) return
    if (_versions.length <= 1) {
      toast("不能删除唯一版本", "warning")
      return
    }

    const latestVer = _versions[0]?.version_number
    if (_currentVersionNumber === latestVer) {
      toast("不能删除最新版本", "warning")
      return
    }

    const confirmed = await confirmAsync(
      `确定删除第 ${_currentChapter} 章 v${_currentVersionNumber}？`,
      "确认删除",
    )
    if (!confirmed) return

    try {
      await api.writing.deleteDraft(_currentDraftId, state.currentProjectId)
      toast("版本已删除", "success")
      await load(_currentChapter)
      if (_versions.length > 0) {
        const latest = _versions[0]
        await switchVersion(latest.id, latest.version_number, true)
      }
    } catch (err) {
      toast(err.message || "删除失败", "error")
    }
  }

  function showVersionHistory() {
    if (!_currentChapter || _versions.length === 0) {
      toast("该章节暂无历史版本", "info")
      return
    }
    const latestVersion = _versions[0]?.version_number
    let listHtml = '<div class="writing-version-history-list">'
    for (const v of _versions) {
      const isLatest = v.version_number === latestVersion
      const wordCount = v.word_count || 0
      const created = v.created_at ? new Date(v.created_at).toLocaleDateString("zh-CN") : ""
      const isCurrent = v.version_number === _currentVersionNumber
      const stateLabel = v.status === "published"
        ? "已发布"
        : (v.version_origin === "manual" ? "手动保存" : "未发布")
      listHtml += `
        <div class="writing-version-item ${isCurrent ? "writing-version-item--current" : ""}">
          <div class="writing-version-item__main">
            <span class="writing-version-item__number">v${esc(v.version_number)}</span>
            <span class="pill">${stateLabel}</span>
            ${isLatest ? " <span class=\"badge badge-canonical\">最新</span>" : ""}
            ${isCurrent ? " <span class=\"pill pill-accent\">当前</span>" : ""}
            <div class="writing-version-item__meta">${esc(created)} · ${esc(wordCount)} 字</div>
          </div>
          <div class="writing-version-item__actions">
            <button class="btn btn-sm writing-btn-compact version-preview-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">预览</button>
            ${!isCurrent ? `<button class="btn btn-sm writing-btn-compact version-restore-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">恢复</button>` : ""}
          </div>
        </div>
      `
    }
    listHtml += "</div>"
    modal.showHtml(`第 ${_currentChapter} 章 — 版本历史 (${_versions.length})`, listHtml)
    setTimeout(() => bindVersionHistoryEvents(), 0)
  }

  function bindVersionHistoryEvents(container = document) {
    container.querySelectorAll(".version-preview-btn").forEach((btn) => {
      btn.onclick = () => _handlePreviewClick(btn)
    })
    container.querySelectorAll(".version-restore-btn").forEach((btn) => {
      btn.onclick = () => _handleRestoreClick(btn)
    })
  }

  function _handlePreviewClick(btn) {
    const draftId = btn.dataset.draftId
    const versionNumber = parseInt(btn.dataset.version, 10)
    const isLatest = btn.dataset.isLatest === "1"
    modal.close()
    switchVersion(draftId, versionNumber, isLatest)
  }

  function _handleRestoreClick(btn) {
    const draftId = btn.dataset.draftId
    const versionNumber = parseInt(btn.dataset.version, 10)
    const isLatest = btn.dataset.isLatest === "1"
    modal.close()
    if (isLatest) {
      switchVersion(draftId, versionNumber, true)
    } else {
      confirmAction(`恢复至 v${versionNumber}？当前编辑器内容将丢失。`, () => {
        switchVersion(draftId, versionNumber, isLatest, { isReadonly: false, restoreSourceVersion: versionNumber })
      }, "确认恢复")
    }
  }

  function setVersions(versions, chapterIndex) {
    _versions = Array.isArray(versions) ? versions : []
    _currentChapter = chapterIndex ?? _currentChapter
    _currentDraftId = _versions[0]?.id || null
    _currentVersionNumber = _versions[0]?.version_number || null
  }

  function dispose() {
    _versions = []
    _currentChapter = null
    _currentDraftId = null
    _currentVersionNumber = null
  }

  return {
    load,
    render,
    bindEvents,
    switchVersion,
    restoreFromVersion,
    deleteVersion,
    setVersions,
    bindVersionHistoryEvents,
    _handlePreviewClick,
    _handleRestoreClick,
    dispose,
  }
}
