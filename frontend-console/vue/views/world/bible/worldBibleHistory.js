/**
 * worldBibleHistory — 世界书页面 / 模板 / 简介三种历史弹窗（阶段 0 从 useWorldBible 拆出）。
 *
 * 沿用现有 showModalHtml 命令式模态模式：所有动态内容先经 esc() 转义再拼装。
 * 页面历史显示时间、与上一版的差异和备注；模板历史补时间与词典原因；
 * 简介历史补时间（简介没有原因字段）。
 */
import { getApi, getCloseModal, getEsc, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { captureModalOwner, ownsModalOwner } from "../logic/worldScopeGuards.js"
import {
  PAGE_REVISION_FIELD_LABELS,
  formatChangedFields,
  formatFullTime,
  formatRelativeTime,
  revisionReasonLabel,
} from "../../../../shared/revisionHistory.js"

/**
 * 创建三种历史弹窗操作。context 依赖由 useWorldBible 注入：
 * - projectId / activePage / pageTemplates：响应式引用
 * - ownsProject / ownsPage / taskStatusLabel：现有守卫与文案助手
 * - restoreSynopsis / restorePageRevision / applyRestoredTemplate：恢复回调（留在 composable 内）
 */
export function createWorldBibleHistory(context) {
  const {
    projectId,
    activePage,
    pageTemplates,
    ownsProject,
    ownsPage,
    taskStatusLabel,
    restoreSynopsis,
    restorePageRevision,
    applyRestoredTemplate,
  } = context
  const esc = getEsc()
  const toast = getToast()

  function timeHtml(item) {
    const full = formatFullTime(item?.created_at)
    const relative = formatRelativeTime(item?.created_at)
    return `<span class="muted" title="${esc(full)}">${esc(relative)}</span>`
  }

  function noteHtml(item) {
    if (!item?.change_note) return ""
    return `<p class="muted">备注：${esc(item.change_note)}</p>`
  }

  // ---- 简介历史：补时间（无原因字段） ----
  async function openSynopsisHistory() {
    const api = getApi()
    const showModalHtml = getShowModalHtml()
    const novelId = projectId.value
    const modalOwner = captureModalOwner()
    try {
      const data = await api.world.listBibleSynopsisRevisions(novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      const items = data.items || []
      const body = items.length ? items.map((item) => `
        <article class="world-bible-suggestion-item">
          <strong>第 ${esc(item.version_number)} 版</strong> · ${esc(taskStatusLabel(item.status))} · ${timeHtml(item)}
          <pre class="generate-markdown-pre">${esc(String(item.rendered_text || "").slice(0, 1200))}</pre>
          <button class="btn btn-sm" data-synopsis-restore="${esc(item.id)}">恢复并固定此版本</button>
        </article>
      `).join("") : `<div class="empty-state"><p>暂无简介版本</p></div>`
      showModalHtml("世界观简介版本", body, [], { size: "large" })
      document.querySelectorAll("[data-synopsis-restore]").forEach((button) => {
        button.addEventListener("click", () => restoreSynopsis(button.getAttribute("data-synopsis-restore"), novelId, button))
      })
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载简介历史失败", "error")
      return false
    }
  }

  // ---- 模板历史：补时间与词典原因（不再显示内容哈希） ----
  async function openPageTemplateHistory(templateId, ownerNode = null) {
    const api = getApi()
    const showModalHtml = getShowModalHtml()
    const template = pageTemplates.value.find((t) => t.id === templateId)
    if (!template || template.builtin) return
    const novelId = projectId.value
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const revisions = await api.world.listBiblePageTemplateRevisions(template.id, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      const body = revisions.map((item) => `
        <div class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${timeHtml(item)} · ${esc(revisionReasonLabel(item.revision_reason))}
          <button class="btn btn-sm" data-template-restore-version="${esc(item.version_number)}">恢复为新版本</button>
        </div>
      `).join("") || `<div class="world-bible-empty-hint">暂无历史</div>`
      showModalHtml("模板历史", body, [], { size: "large" })
      document.querySelectorAll("[data-template-restore-version]").forEach((button) => {
        button.addEventListener("click", async () => {
          if (!ownsProject(novelId)) return false
          const restoreOwner = captureModalOwner(button)
          try {
            const restored = await api.world.restoreBiblePageTemplateRevision(template.id, Number(button.getAttribute("data-template-restore-version")), novelId)
            if (!ownsProject(novelId) || !ownsModalOwner(restoreOwner)) return false
            applyRestoredTemplate(restored)
            getCloseModal()()
            getToast()("历史模板已恢复为新版本", "success")
          } catch (err) {
            if (ownsProject(novelId) && ownsModalOwner(restoreOwner)) getToast()(err.message || "恢复模板失败", "error")
            return false
          }
        })
      })
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载模板历史失败", "error")
      return false
    }
  }

  // ---- 页面历史：时间、与上一版差异和备注 ----
  async function openPageHistory(version = null) {
    const api = getApi()
    const showModalHtml = getShowModalHtml()
    const page = activePage.value
    if (!page?.id) return
    const novelId = projectId.value
    const pageId = page.id
    const modalOwner = captureModalOwner()
    try {
      const revisions = await api.world.listBiblePageRevisions(pageId, novelId)
      if (!ownsPage(novelId, pageId) || !ownsModalOwner(modalOwner)) return false
      const selected = Array.isArray(revisions) ? revisions.filter(item => !Number.isInteger(version) || item.version_number === version) : []
      const body = selected.length ? selected.map((item) => {
        const changed = formatChangedFields(item.changed_fields, { labels: PAGE_REVISION_FIELD_LABELS })
        return `
        <article class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(revisionReasonLabel(item.revision_reason))} · ${timeHtml(item)}
          ${changed ? `<p class="muted">与上一版相比：${esc(changed)}</p>` : ""}
          ${noteHtml(item)}
          <pre class="generate-markdown-pre">${esc(String(item.snapshot_json?.free_text || "").slice(0, 1200))}</pre>
          <button class="btn btn-sm" data-bible-page-restore="${esc(item.version_number)}">恢复为工作稿</button>
        </article>
      `}).join("") : `<div class="empty-state"><p>${Number.isInteger(version) ? "这份历史版本已不可用" : "暂无页面版本"}</p></div>`
      showModalHtml("世界书页面版本", body, [], { size: "large" })
      document.querySelectorAll("[data-bible-page-restore]").forEach((button) => {
        button.addEventListener("click", () => restorePageRevision(Number(button.getAttribute("data-bible-page-restore")), novelId, pageId, button))
      })
    } catch (err) {
      if (ownsPage(novelId, pageId) && ownsModalOwner(modalOwner)) toast(err.message || "加载页面历史失败", "error")
      return false
    }
  }

  return { openSynopsisHistory, openPageTemplateHistory, openPageHistory }
}
