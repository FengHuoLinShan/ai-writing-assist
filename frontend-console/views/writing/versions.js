/**
 * 章节版本管理器
 *
 * 负责版本历史加载、版本选择器渲染、版本切换/恢复/删除。
 * 从 writingView.js 拆分，便于独立测试。
 */

import { confirmAsync } from "../../shared/confirmAsync.js"
import { buildVersionDiff, renderVersionDiff } from "./versionDiff.js"

const MAX_DIFF_DRAFT_CACHE_ENTRIES = 8

export function createVersionManager({ state, api, toast, modal, esc, onSwitch }) {
  let _versions = []
  let _currentChapter = null
  let _currentDraftId = null
  let _currentVersionNumber = null
  let _loadGeneration = 0
  let _diffGeneration = 0
  let _loadedProjectId = null
  const _draftCache = new Map()

  function isActiveVersion(version) {
    if (!version) return false
    if (version?.display_state) return version.display_state === "active"
    return !["candidate", "deprecated"].includes(version?.status)
  }

  function latestActiveVersion() {
    return _versions.find(isActiveVersion) || null
  }

  function activeVersionLabel(version) {
    if (version.status === "published" || version.status === "canonical") {
      return "已发布"
    }
    return version.version_origin === "manual" ? "手动保存" : "未发布"
  }

  function historyVersionLabel(version) {
    const displayState = version.display_state
      || (version.status === "candidate"
        ? "review"
        : (version.status === "deprecated" ? "archived" : "active"))
    if (displayState === "review") return "待审核"
    if (displayState !== "archived") return activeVersionLabel(version)

    let originalLabel = null
    if (["published", "canonical"].includes(version.deprecated_from_status)) {
      originalLabel = "原已发布"
    } else if (version.deprecated_from_status === "draft") {
      originalLabel = "原工作稿"
    } else if (version.deprecated_from_status === "candidate") {
      originalLabel = "原待审核"
    }
    return originalLabel ? `历史 · ${originalLabel}` : "历史"
  }

  async function load(chapterIndex) {
    const loadGeneration = ++_loadGeneration
    const projectId = state.currentProjectId
    _diffGeneration += 1
    _draftCache.clear()
    _currentChapter = chapterIndex
    _loadedProjectId = null
    _currentDraftId = null
    _currentVersionNumber = null
    try {
      const history = await api.writing.getVersionHistory(chapterIndex, projectId)
      if (loadGeneration !== _loadGeneration || state.currentProjectId !== projectId) return false
      _versions = history.versions || []
      _loadedProjectId = projectId
      const latest = latestActiveVersion()
      if (latest) {
        _currentDraftId = latest.id
        _currentVersionNumber = latest.version_number
      }
      return true
    } catch (err) {
      if (loadGeneration !== _loadGeneration || state.currentProjectId !== projectId) return false
      _versions = []
      _loadedProjectId = projectId
      toast("版本历史加载失败：" + (err.message || "未知错误"), "error")
      return false
    }
  }

  function render() {
    if (!_currentChapter || _versions.length === 0 || _loadedProjectId !== state.currentProjectId) return ""
    const current = _versions.find((version) => version.id === _currentDraftId)
    const canManageCurrent = isActiveVersion(current)

    let html = `
      <div class="writing-version-bar">
        <span class="writing-version-label">版本：</span>
        <span class="writing-version-select-wrap">
          <select id="version-selector" class="writing-version-select" aria-label="选择章节版本">
    `

    const activeVersions = _versions.filter(isActiveVersion)
    const latest = latestActiveVersion()
    for (const v of activeVersions) {
      const selected = v.version_number === _currentVersionNumber
      const isCurLatest = v.id === latest?.id
      const stateLabel = activeVersionLabel(v)
      html += `<option value="${esc(v.id)}" data-version="${esc(v.version_number)}" data-latest="${isCurLatest ? 1 : 0}" ${selected ? "selected" : ""}>v${esc(v.version_number)}${isCurLatest ? " (最新)" : ""} · ${esc(stateLabel)}</option>`
    }

    html += `
          </select>
        </span>
        <button class="btn btn-sm writing-btn-compact" data-action="version-history" title="版本历史">历史</button>
        ${diffVersions().length >= 2 ? '<button class="btn btn-sm writing-btn-compact" data-action="version-diff" title="比较两个版本">比较</button>' : ""}
        ${canManageCurrent ? '<button class="btn btn-sm writing-version-delete" id="btn-delete-version" data-action="delete-version" title="删除当前版本" aria-label="删除当前版本">🗑</button>' : ""}
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

    const diffBtn = container.querySelector('[data-action="version-diff"]')
    if (diffBtn) {
      diffBtn.onclick = () => showVersionDiff()
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
      const latest = latestActiveVersion()
      const selectedVersion = _versions.find((version) => version.id === draftData.id)
      const canRestore = isActiveVersion(selectedVersion || draftData)
      onSwitch({
        draftId: draftData.id,
        versionNumber,
        isReadonly: canRestore
          ? (options.isReadonly !== undefined ? options.isReadonly : !isLatest)
          : true,
        restoreSourceVersion: canRestore
          ? (options.restoreSourceVersion !== undefined ? options.restoreSourceVersion : (isLatest ? null : versionNumber))
          : null,
        restoreExpectedVersion: canRestore && !isLatest ? (latest?.version_number || null) : null,
        restoreExpectedUpdatedAt: canRestore && !isLatest ? (latest?.updated_at || null) : null,
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
    const selected = _versions.find((version) => version.id === _currentDraftId)
    if (!isActiveVersion(selected)) return
    const latest = latestActiveVersion()
    onSwitch({
      draftId: _currentDraftId,
      versionNumber: _currentVersionNumber,
      isReadonly: false,
      restoreSourceVersion: _currentVersionNumber,
      restoreExpectedVersion: latest?.version_number || null,
      restoreExpectedUpdatedAt: latest?.updated_at || null,
    })
    toast("已创建新版本，可继续编辑", "success")
  }

  async function deleteVersion() {
    if (!_currentDraftId || !_currentChapter) return
    const activeVersions = _versions.filter(isActiveVersion)
    const selected = _versions.find((version) => version.id === _currentDraftId)
    if (!isActiveVersion(selected)) {
      toast("待审核或已归档版本仅供预览", "warning")
      return
    }
    if (activeVersions.length <= 1) {
      toast("不能删除唯一版本", "warning")
      return
    }

    const latestVer = latestActiveVersion()?.version_number
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
      const latest = latestActiveVersion()
      if (latest) {
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
    const latest = latestActiveVersion()
    let listHtml = `
      <div class="writing-version-history-toolbar">
        ${diffVersions().length >= 2 ? '<button class="btn btn-sm btn-primary" data-action="version-diff" type="button">比较版本</button>' : ""}
        <span>比较仅在当前页面临时计算，不会创建、恢复或采用版本。</span>
      </div>
      <div class="writing-version-history-list">
    `
    for (const v of _versions) {
      const isLatest = v.id === latest?.id
      const canRestore = isActiveVersion(v)
      const wordCount = v.word_count || 0
      const created = v.created_at ? new Date(v.created_at).toLocaleDateString("zh-CN") : ""
      const isCurrent = v.version_number === _currentVersionNumber
      const stateLabel = historyVersionLabel(v)
      listHtml += `
        <div class="writing-version-item ${isCurrent ? "writing-version-item--current" : ""}">
          <div class="writing-version-item__main">
            <span class="writing-version-item__number">v${esc(v.version_number)}</span>
            <span class="pill">${esc(stateLabel)}</span>
            ${isLatest ? " <span class=\"badge badge-canonical\">最新</span>" : ""}
            ${isCurrent ? " <span class=\"pill pill-accent\">当前</span>" : ""}
            <div class="writing-version-item__meta">${esc(created)} · ${esc(wordCount)} 字</div>
          </div>
          <div class="writing-version-item__actions">
            <button class="btn btn-sm writing-btn-compact version-preview-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">预览</button>
            ${canRestore && !isCurrent ? `<button class="btn btn-sm writing-btn-compact version-restore-btn" data-draft-id="${esc(v.id)}" data-version="${esc(v.version_number)}" data-is-latest="${isLatest ? 1 : 0}">恢复</button>` : ""}
          </div>
        </div>
      `
    }
    listHtml += "</div>"
    modal.showHtml(`第 ${_currentChapter} 章 — 版本历史 (${_versions.length})`, listHtml)
    bindVersionHistoryEvents()
  }

  function bindVersionHistoryEvents(container = document) {
    container.querySelectorAll('[data-action="version-diff"]').forEach((btn) => {
      btn.onclick = () => showVersionDiff()
    })
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

  function showVersionDiff() {
    if (_loadedProjectId !== state.currentProjectId) {
      toast("版本列表已过期，请重新选择章节", "warning")
      return
    }
    const availableVersions = diffVersions()
    if (!_currentChapter || availableVersions.length < 2) {
      toast("至少需要两个版本才能比较", "info")
      return
    }
    const currentDraftId = normalizeDraftId(_currentDraftId)
    const rightId = availableVersions.some((version) => normalizeDraftId(version.id) === currentDraftId)
      ? currentDraftId
      : normalizeDraftId(availableVersions[0]?.id)
    const leftId = normalizeDraftId(availableVersions.find(
      (version) => normalizeDraftId(version.id) !== rightId,
    )?.id)
    if (!leftId || !rightId) {
      toast("至少需要两个版本才能比较", "info")
      return
    }
    const options = availableVersions.map((version) => `
      <option value="${esc(normalizeDraftId(version.id))}">${esc(versionOptionLabel(version))}</option>
    `).join("")
    const body = `
      <div class="writing-version-diff-dialog">
        <div class="writing-version-diff-controls">
          <label>
            <span>左侧版本</span>
            <select id="writing-version-diff-left" class="form-select" aria-label="选择左侧版本">
              ${options}
            </select>
          </label>
          <button class="btn btn-sm writing-version-diff-swap" data-action="swap-version-diff" type="button" title="交换左右版本" aria-label="交换左右版本">⇄</button>
          <label>
            <span>右侧版本</span>
            <select id="writing-version-diff-right" class="form-select" aria-label="选择右侧版本">
              ${options}
            </select>
          </label>
          <button class="btn btn-sm btn-primary" data-action="refresh-version-diff" type="button">比较</button>
        </div>
        <p class="writing-version-diff-readonly">只读临时比较：包含工作稿、待审核与历史版本；不会修改任何版本状态。</p>
        <div id="writing-version-diff-result" class="writing-version-diff-result" aria-live="polite"></div>
      </div>
    `
    modal.showHtml(`第 ${_currentChapter} 章 — 版本比较`, body, [], {
      size: "large",
      protectUnsaved: false,
    })
    const leftSelect = document.getElementById("writing-version-diff-left")
    const rightSelect = document.getElementById("writing-version-diff-right")
    if (leftSelect) leftSelect.value = leftId
    if (rightSelect) rightSelect.value = rightId
    bindVersionDiffEvents()
    loadVersionDiff(leftId, rightId)
  }

  function bindVersionDiffEvents(container = document) {
    const leftSelect = container.querySelector("#writing-version-diff-left")
    const rightSelect = container.querySelector("#writing-version-diff-right")
    if (!leftSelect || !rightSelect) return
    const compare = () => loadVersionDiff(leftSelect.value, rightSelect.value, container)
    leftSelect.onchange = compare
    rightSelect.onchange = compare
    const swapBtn = container.querySelector('[data-action="swap-version-diff"]')
    if (swapBtn) {
      swapBtn.onclick = () => {
        const leftValue = leftSelect.value
        leftSelect.value = rightSelect.value
        rightSelect.value = leftValue
        compare()
      }
    }
    const refreshBtn = container.querySelector('[data-action="refresh-version-diff"]')
    if (refreshBtn) refreshBtn.onclick = compare
  }

  async function loadVersionDiff(leftId, rightId, container = document) {
    const resultEl = container.querySelector?.("#writing-version-diff-result")
      || document.getElementById("writing-version-diff-result")
    const requestGeneration = ++_diffGeneration
    if (!resultEl) return false
    const normalizedLeftId = normalizeDraftId(leftId)
    const normalizedRightId = normalizeDraftId(rightId)
    if (!normalizedLeftId || !normalizedRightId) {
      resultEl.textContent = "请选择两个版本"
      return false
    }
    if (normalizedLeftId === normalizedRightId) {
      resultEl.textContent = "左右两侧不能选择同一版本"
      return false
    }

    const projectId = state.currentProjectId
    const chapterIndex = _currentChapter
    if (_loadedProjectId !== projectId || !chapterIndex) {
      resultEl.textContent = "版本列表已过期，请重新加载章节"
      return false
    }
    const availableIds = new Set(diffVersions().map((version) => normalizeDraftId(version.id)))
    if (!availableIds.has(normalizedLeftId) || !availableIds.has(normalizedRightId)) {
      resultEl.textContent = "所选版本不属于当前章节，请重新选择"
      return false
    }
    resultEl.textContent = "正在读取并比较版本…"
    try {
      const [leftDraft, rightDraft] = await Promise.all([
        getDraftForDiff(normalizedLeftId, projectId, chapterIndex),
        getDraftForDiff(normalizedRightId, projectId, chapterIndex),
      ])
      if (!isCurrentDiffRequest(requestGeneration, projectId, chapterIndex, resultEl)) return false
      await new Promise((resolve) => setTimeout(resolve, 0))
      if (!isCurrentDiffRequest(requestGeneration, projectId, chapterIndex, resultEl)) return false
      const diff = buildVersionDiff(leftDraft?.content || "", rightDraft?.content || "")
      resultEl.innerHTML = renderVersionDiff(diff, {
        esc,
        leftLabel: versionLabelById(normalizedLeftId),
        rightLabel: versionLabelById(normalizedRightId),
      })
      return true
    } catch (err) {
      if (!isCurrentDiffRequest(requestGeneration, projectId, chapterIndex, resultEl)) return false
      resultEl.textContent = `版本比较失败：${err?.message || "未知错误"}`
      return false
    }
  }

  function getDraftForDiff(draftId, projectId, chapterIndex) {
    const cacheKey = `${projectId}:${draftId}`
    if (_draftCache.has(cacheKey)) {
      const cached = _draftCache.get(cacheKey)
      _draftCache.delete(cacheKey)
      _draftCache.set(cacheKey, cached)
      return cached
    }
    const request = api.writing.get(draftId, projectId)
      .then((draft) => {
        assertDiffDraftIdentity(draft, draftId, projectId, chapterIndex)
        return draft
      })
      .catch((error) => {
        if (_draftCache.get(cacheKey) === request) _draftCache.delete(cacheKey)
        throw error
      })
    _draftCache.set(cacheKey, request)
    while (_draftCache.size > MAX_DIFF_DRAFT_CACHE_ENTRIES) {
      _draftCache.delete(_draftCache.keys().next().value)
    }
    return request
  }

  function isCurrentDiffRequest(generation, projectId, chapterIndex, resultEl) {
    return (
      generation === _diffGeneration &&
      projectId === state.currentProjectId &&
      projectId === _loadedProjectId &&
      chapterIndex === _currentChapter &&
      isActiveDiffTarget(resultEl)
    )
  }

  function isActiveDiffTarget(resultEl) {
    if (!resultEl?.isConnected) return false
    if (document.getElementById("writing-version-diff-result") !== resultEl) return false
    const overlay = resultEl.closest?.("#modal-overlay")
    return !overlay?.classList.contains("hidden")
  }

  function assertDiffDraftIdentity(draft, draftId, projectId, chapterIndex) {
    if (!draft || normalizeDraftId(draft.id) !== draftId) {
      throw new Error("版本响应与所选版本不一致")
    }
    if (draft.novel_id != null && String(draft.novel_id) !== String(projectId)) {
      throw new Error("版本响应不属于当前项目")
    }
    if (draft.chapter_index != null && String(draft.chapter_index) !== String(chapterIndex)) {
      throw new Error("版本响应不属于当前章节")
    }
  }

  function normalizeDraftId(draftId) {
    return draftId == null ? "" : String(draftId)
  }

  function diffVersions() {
    const seen = new Set()
    return _versions.filter((version) => {
      const draftId = normalizeDraftId(version?.id)
      if (!draftId || seen.has(draftId)) return false
      seen.add(draftId)
      return true
    })
  }

  function versionOptionLabel(version) {
    return `v${version.version_number} · ${historyVersionLabel(version)}`
  }

  function versionLabelById(draftId) {
    const version = _versions.find((item) => String(item.id) === String(draftId))
    return version ? versionOptionLabel(version) : "未知版本"
  }

  function setVersions(versions, chapterIndex) {
    _diffGeneration += 1
    _draftCache.clear()
    _versions = Array.isArray(versions) ? versions : []
    _loadedProjectId = state.currentProjectId
    _currentChapter = chapterIndex ?? _currentChapter
    const latest = latestActiveVersion()
    _currentDraftId = latest?.id || null
    _currentVersionNumber = latest?.version_number || null
  }

  function dispose() {
    _loadGeneration += 1
    _diffGeneration += 1
    _draftCache.clear()
    _versions = []
    _loadedProjectId = null
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
    showVersionDiff,
    bindVersionDiffEvents,
    loadVersionDiff,
    _handlePreviewClick,
    _handleRestoreClick,
    dispose,
  }
}
