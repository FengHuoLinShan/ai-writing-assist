/**
 * 剧情设定冲突检查模块
 *
 * 负责运行冲突检查、渲染检查条、打开检查详情弹窗。
 * 定位与打开来源通过回调交给 orchestrator 路由。
 */

import { showWritingConflictModal } from "../../views/writingConflictModal.js"

export function createConflictCheck({
  state,
  api,
  toast,
  modal,
  esc,
  onInsertText,
  onOpenMap,
  onNavigateOutline,
}) {
  const projectState = state
  const modalApi = modal
  const escapeHtml = esc

  let conflictChecks = []
  let latestConflictCheck = null
  let checkingConflicts = false

  function currentProjectId() {
    return projectState.currentProjectId
  }

  async function run(chapterIndex, getContentCallback) {
    if (checkingConflicts) return
    const projectId = currentProjectId()
    if (!projectId || !chapterIndex) {
      toast("请先选择章节", "warning")
      return
    }
    checkingConflicts = true
    try {
      const options = await confirmOptions()
      if (!options) return
      const content = typeof getContentCallback === "function"
        ? await getContentCallback()
        : null
      const currentScene = projectState._currentSceneId || null
      const check = await api.writing.createConflictCheck({
        novel_id: projectId,
        chapter_index: chapterIndex,
        scene_id: currentScene,
        content,
        include_candidates: options.includeCandidates,
      })
      await refresh(chapterIndex)
      open(check)
    } catch (err) {
      toast(err.message || "剧情设定冲突检查失败", "error")
    } finally {
      checkingConflicts = false
    }
  }

  async function saveDraftForConflictCheck(getContentCallback) {
    const projectId = currentProjectId()
    const chapterIndex = projectState._currentChapter
    const content = typeof getContentCallback === "function" ? await getContentCallback() : null
    if (!content) throw new Error("请先选择章节")
    // orchestrator 负责真实保存；此处仅作为兼容性占位，返回当前版本信息
    return {
      id: projectState._currentDraftId,
      version_number: projectState._currentVersionNumber,
      updated_at: projectState._currentUpdatedAt,
    }
  }

  function confirmOptions() {
    return new Promise((resolve) => {
      let settled = false
      let observer = null
      const modalClose = document.getElementById("modal-close")
      const modalOverlay = document.getElementById("modal-overlay")
      const cleanup = () => {
        modalClose?.removeEventListener("click", onCloseClick)
        modalOverlay?.removeEventListener("click", onOverlayClick)
        document.removeEventListener("keydown", onKeyDown, true)
        observer?.disconnect()
      }
      const settle = (value) => {
        if (settled) return
        settled = true
        cleanup()
        resolve(value)
      }
      const cancel = () => {
        modalApi.closeModal()
        settle(null)
      }
      const onCloseClick = cancel
      const onOverlayClick = (event) => {
        if (event.target === event.currentTarget) cancel()
      }
      const onKeyDown = (event) => {
        if (event.key === "Escape") {
          cancel()
        }
      }
      const body = `
        <div class="writing-conflict-options">
          <label class="writing-checkbox-label">
            <input id="writing-conflict-include-candidates" type="checkbox" />
            <span>包含待处理内容</span>
          </label>
          <p class="writing-form-hint">
            包含后，依赖待处理内容的检查结果会标记注意原因；不会修改正文、Scene、地图或已采用设定。
          </p>
        </div>
      `
      modalApi.showModalHtml("剧情设定冲突检查", body, [
        {
          text: "取消",
          class: "btn-ghost",
          handler: cancel,
        },
        {
          text: "开始检查",
          class: "btn-primary",
          handler: () => {
            const checkbox = document.getElementById("writing-conflict-include-candidates")
            modalApi.closeModal()
            settle({ includeCandidates: Boolean(checkbox?.checked) })
          },
        },
      ])
      modalClose?.addEventListener("click", onCloseClick)
      modalOverlay?.addEventListener("click", onOverlayClick)
      document.addEventListener("keydown", onKeyDown, true)
      if (modalOverlay && typeof MutationObserver !== "undefined") {
        observer = new MutationObserver(() => {
          if (modalOverlay.classList.contains("hidden")) settle(null)
        })
        observer.observe(modalOverlay, { attributes: true, attributeFilter: ["class"] })
      }
    })
  }

  async function refresh(chapterIndex) {
    const projectId = currentProjectId()
    if (!projectId || !chapterIndex) {
      conflictChecks = []
      latestConflictCheck = null
      return
    }
    try {
      const result = await api.writing.listConflictChecks({
        novel_id: projectId,
        chapter_index: chapterIndex,
        limit: 1,
      })
      conflictChecks = result.items || []
      latestConflictCheck = conflictChecks[0] || null
    } catch {
      conflictChecks = []
      latestConflictCheck = null
    }
  }

  function renderStrip() {
    if (!projectState._currentChapter) return ""
    const latest = latestConflictCheck || conflictChecks[0]
    const history = conflictChecks.slice(1)
    const latestHtml = latest
      ? `<button class="writing-conflict-latest" data-action="open-conflict-check" data-check-id="${escapeHtml(latest.id)}">
          ${escapeHtml(formatSummary(latest))}
        </button>`
      : '<span class="writing-conflict-empty-inline">暂无检查记录</span>'
    const historyHtml = history.length
      ? `
        <details class="writing-conflict-history">
          <summary>历史 ▾</summary>
          <div class="writing-conflict-history__list">
            ${history.map((item) => `
              <button data-action="open-conflict-check" data-check-id="${escapeHtml(item.id)}">
                ${escapeHtml(formatSummary(item))}
              </button>
            `).join("")}
          </div>
        </details>
      `
      : ""
    return `
      <div class="writing-conflict-strip" id="writing-conflict-strip">
        ${latestHtml}
        ${historyHtml}
      </div>
    `
  }

  function updateStrip(container = document) {
    const stripEl = container.querySelector
      ? container.querySelector("#writing-conflict-strip")
      : document.getElementById("writing-conflict-strip")
    if (stripEl) stripEl.outerHTML = renderStrip()
  }

  function formatSummary(check) {
    const created = check?.created_at ? new Date(check.created_at) : null
    const time = created && !Number.isNaN(created.getTime())
      ? created.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
      : "刚刚"
    const total = check?.summary_json?.total ?? (check?.items || []).length
    return `${time} · 发现 ${total} 个冲突`
  }

  function open(checkOrId) {
    const projectId = currentProjectId()
    const check = typeof checkOrId === "string"
      ? conflictChecks.find((item) => item.id === checkOrId)
      : checkOrId
    if (!check) {
      toast("检查记录暂不可用", "warning")
      return
    }
    showWritingConflictModal({
      check,
      novelId: projectId,
      onStatusChanged: async () => {
        await refresh(projectState._currentChapter)
      },
      onAiReviewComplete: async (updatedCheck) => {
        await refresh(projectState._currentChapter)
        const refreshed = conflictChecks.find((item) => item.id === updatedCheck?.id) || updatedCheck
        if (refreshed) open(refreshed)
      },
      onSuggestionComplete: async (updatedItem) => {
        await refresh(projectState._currentChapter)
        const refreshed = conflictChecks.find((item) => item.id === updatedItem?.check_id) || check
        if (refreshed) open(refreshed)
      },
      onApplySuggestion: (_itemId, text) => {
        onInsertText?.(text)
        toast("AI 建议已采用到当前工作稿", "success")
      },
      onLocate: (itemId) => locateItem(check, itemId),
      onOpenSource: (itemId) => openSource(check, itemId),
    })
  }

  function bindEvents(container) {
    container.querySelectorAll('[data-action="open-conflict-check"]').forEach((btn) => {
      btn.addEventListener("click", () => {
        const checkId = btn.getAttribute("data-check-id")
        open(checkId)
      })
    })
  }

  function locateItem(check, itemId) {
    const item = (check?.items || []).find((entry) => entry.id === itemId)
    const location = item?.location_json || {}
    const textRange = location.text_range || location
    const editorEl = document.getElementById("writing-editor")
    if (!editorEl || typeof textRange.start !== "number") {
      toast("该问题暂无正文定位", "info")
      return
    }
    editorEl.focus()
    editorEl.setSelectionRange(textRange.start, textRange.end || textRange.start)
  }

  function openSource(check, itemId) {
    const item = (check?.items || []).find((entry) => entry.id === itemId)
    const location = item?.location_json || {}
    const openTarget = location.open_target || {}
    const openTargetKind = openTarget.kind

    if (openTargetKind === "text_range") {
      locateItem(check, itemId)
      return
    }
    if (openTargetKind === "map_scene" || openTargetKind === "map_object") {
      onOpenMap?.(openTarget)
      return
    }
    if (openTargetKind === "outline_scene") {
      const hint = location.source?.label || openTarget.scene_id || "Scene"
      onNavigateOutline?.(`已打开大纲：${hint}`)
      return
    }
    if (openTargetKind === "memory_chapter") {
      const chapterIndex = openTarget.chapter_index || location.source?.chapter_index || "-"
      const characterId = openTarget.character_id || location.source?.character_id || "-"
      modalApi.showModalHtml("记忆来源", `
        <div class="writing-conflict-source-modal">
          <p><strong>章节</strong>：第 ${escapeHtml(chapterIndex)} 章</p>
          <p><strong>角色</strong>：${escapeHtml(characterId)}</p>
        </div>
      `, [{ text: "关闭", class: "btn-ghost", handler: modalApi.closeModal }])
      return
    }
    if (item?.source_module === "world") {
      onOpenMap?.(openTarget)
      return
    }
    if (item?.source_module === "outline") {
      onNavigateOutline?.()
      return
    }
    toast("该来源暂无可打开视图", "info")
  }

  function dispose() {
    conflictChecks = []
    latestConflictCheck = null
    checkingConflicts = false
  }

  return {
    run,
    saveDraftForConflictCheck,
    refresh,
    renderStrip,
    updateStrip,
    bindEvents,
    open,
    locateItem,
    openSource,
    dispose,
  }
}
