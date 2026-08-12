/**
 * outlineStructureOps — outline 结构子标签（threads/arcs/foreshadowing/reveals）
 * 的创建、编辑、删除、复核标记，以及批量执行。
 *
 * 模态全部走全局 showModalHtml（Vue 树外）；成功后 router.refresh()。
 * AI 入口按钮调用另一 lane 的模块（showOutlineLayerAiForm 等，签名见任务规格）。
 */
import { getApi, getAppState, getCloseModal, getConfirm, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { structureAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { runBulkAction, bulkResultMessage, selectedItemsFrom, getBulkSelection, clearBulkSelection, clearAllBulkSelections } from "./outlineBulkSelection.js"
import {
  ENTITY_ALLOWED_STATUSES,
  FORESHADOWING_STATUSES,
  FORESHADOWING_STATUS_LABELS,
  P20_TARGET_BY_SUBVIEW,
  REVEAL_STATUSES,
  REVEAL_STATUS_LABELS,
} from "./outlineStructure.js"

// ============================================================
// 资产来源与复核状态辅助
// ============================================================

export function assetProvenance(asset) {
  return asset?.provenance_meta && typeof asset.provenance_meta === "object"
    ? asset.provenance_meta
    : {}
}

function structureReviewState(asset) {
  const meta = assetProvenance(asset)
  return {
    reviewed: Boolean(meta.reviewed_at),
    needsReview: meta.needs_review === true,
  }
}

function reviewThreadPayload(thread, reviewedFrom) {
  const meta = {
    ...assetProvenance(thread),
    needs_review: false,
    reviewed_at: new Date().toISOString(),
    reviewed_by: "manual",
    reviewed_from: reviewedFrom,
  }
  if (!meta.review_previous_status && thread?.status && thread.status !== "canonical") {
    meta.review_previous_status = thread.status
  }
  return {
    status: "canonical",
    provenance_meta: meta,
  }
}

function unreviewThreadPayload(thread) {
  const meta = { ...assetProvenance(thread), needs_review: true }
  const restoreStatus = meta.review_previous_status || "draft"
  delete meta.reviewed_at
  delete meta.reviewed_by
  delete meta.reviewed_from
  delete meta.review_previous_status
  return {
    status: restoreStatus,
    provenance_meta: meta,
  }
}

// ============================================================
// 刷新辅助
// ============================================================

async function finishMutation(successMessage) {
  const toast = getToast()
  try {
    const refreshed = await getRouter()?.refresh?.()
    if (refreshed === false) throw new Error("当前页面未完成刷新")
  } catch (err) {
    toast(`${successMessage}，但列表刷新失败：${err.message || "未知错误"}`, "warning")
    return true
  }
  toast(successMessage, "success")
  return true
}

async function refreshCurrentView() {
  await getRouter()?.refresh?.()
}

// ============================================================
// 伏笔 CRUD (vanilla L1442-1540)
// ============================================================

export function showCreateForeshadowingForm(guessLastChapter) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const defaultChapter = (guessLastChapter && guessLastChapter()) || 1
  const statusOptions = FORESHADOWING_STATUSES.map(
    (s) => `<option value="${s}">${FORESHADOWING_STATUS_LABELS[s] || s}</option>`,
  ).join("")

  const formHtml = `
    <div class="form-group">
      <label>描述 *</label>
      <textarea class="form-textarea" id="create-foreshadowing-description" rows="3" placeholder="伏笔描述"></textarea>
    </div>
    <div class="form-group">
      <label>目标章节</label>
      <input class="form-input" id="create-foreshadowing-target-chapter" type="number" min="1" value="${defaultChapter}" />
    </div>
    <div class="form-group">
      <label>状态</label>
      <select class="form-select" id="create-foreshadowing-status">${statusOptions}</select>
    </div>
  `
  showModalHtml("新建伏笔", formHtml, [{
    text: "创建", class: "btn-primary", handler: async () => {
      const description = document.getElementById("create-foreshadowing-description")?.value?.trim()
      if (!description) { toast("请输入描述", "warning"); return }
      const targetChapter = parseInt(document.getElementById("create-foreshadowing-target-chapter")?.value || "1", 10)
      try {
        await getApi().outline.createForeshadowing(getAppState()?.currentProjectId, {
          name: description,
          summary: description,
          planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
          status: document.getElementById("create-foreshadowing-status")?.value || "planted",
        })
        toast("伏笔已创建", "success")
        refreshCurrentView()
      } catch (err) {
        toast(err.message || "创建失败", "error")
      }
    },
  }])
}

export function editForeshadowing(id, foreshadowingList, guessLastChapter) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const f = (foreshadowingList || []).find((item) => item.id === id)
  if (!f) return

  const description = f.summary || f.name || ""
  const targetChapter = f.planned_seed_chapter || (guessLastChapter && guessLastChapter()) || 1
  const statusOptions = FORESHADOWING_STATUSES.map(
    (s) => `<option value="${s}" ${f.status === s ? "selected" : ""}>${FORESHADOWING_STATUS_LABELS[s] || s}</option>`,
  ).join("")

  const formHtml = `
    <div class="form-group">
      <label>描述 *</label>
      <textarea class="form-textarea" id="edit-foreshadowing-description" rows="3">${esc(description)}</textarea>
    </div>
    <div class="form-group">
      <label>目标章节</label>
      <input class="form-input" id="edit-foreshadowing-target-chapter" type="number" min="1" value="${targetChapter}" />
    </div>
    <div class="form-group">
      <label>状态</label>
      <select class="form-select" id="edit-foreshadowing-status">${statusOptions}</select>
    </div>
  `
  showModalHtml("编辑伏笔", formHtml, [{
    text: "保存", class: "btn-primary", handler: async () => {
      const description = document.getElementById("edit-foreshadowing-description")?.value?.trim()
      if (!description) { toast("请输入描述", "warning"); return }
      const targetChapter = parseInt(document.getElementById("edit-foreshadowing-target-chapter")?.value || "1", 10)
      try {
        await getApi().outline.updateForeshadowing(id, getAppState()?.currentProjectId, {
          name: description,
          summary: description,
          planned_seed_chapter: Number.isInteger(targetChapter) && targetChapter >= 1 ? targetChapter : 1,
          status: document.getElementById("edit-foreshadowing-status")?.value || "planted",
        })
        toast("伏笔已保存", "success")
        refreshCurrentView()
      } catch (err) {
        toast(err.message || "保存失败", "error")
      }
    },
  }])
}

export function deleteForeshadowing(id) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  confirmAction("确定删除此伏笔？", async () => {
    try {
      await getApi().outline.deleteForeshadowing(id, getAppState()?.currentProjectId)
      toast("已删除", "success")
      refreshCurrentView()
    } catch (err) {
      toast(err.message || "删除失败", "error")
    }
  })
}

/** 伏笔状态就地更新（vanilla _bindEvents 中 .foreshadowing-status-select 的 change 事件）。 */
export async function updateForeshadowingStatus(id, newStatus) {
  const toast = getToast()
  try {
    await getApi().outline.updateForeshadowing(id, getAppState()?.currentProjectId, { status: newStatus })
    toast("伏笔状态已更新", "success")
    refreshCurrentView()
  } catch (err) {
    toast(err.message || "更新失败", "error")
  }
}

// ============================================================
// 揭示 CRUD (vanilla L1540-1665)
// ============================================================

export function showCreateRevealForm(guessLastChapter, buildForeshadowingOptions) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const defaultChapter = (guessLastChapter && guessLastChapter()) || 1
  const statusOptions = REVEAL_STATUSES.map(
    (s) => `<option value="${s}">${REVEAL_STATUS_LABELS[s] || s}</option>`,
  ).join("")
  const foreshadowingOptions = (buildForeshadowingOptions && buildForeshadowingOptions()) || ""

  const formHtml = `
    <div class="form-group">
      <label>描述 *</label>
      <textarea class="form-textarea" id="create-reveal-description" rows="3" placeholder="揭示的秘密"></textarea>
    </div>
    <div class="form-group">
      <label>揭示章节 *</label>
      <input class="form-input" id="create-reveal-chapter" type="number" min="1" value="${defaultChapter}" />
    </div>
    <div class="form-group">
      <label>关联伏笔（可选）</label>
      <select class="form-select" id="create-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
    </div>
    <div class="form-group">
      <label>状态</label>
      <select class="form-select" id="create-reveal-status">${statusOptions}</select>
    </div>
  `
  showModalHtml("新建揭示", formHtml, [{
    text: "创建", class: "btn-primary", handler: async () => {
      const description = document.getElementById("create-reveal-description")?.value?.trim()
      const chapterValue = document.getElementById("create-reveal-chapter")?.value
      if (!description) { toast("请输入描述", "warning"); return }
      const chapterIndex = parseInt(chapterValue || "1", 10)
      if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
        toast("揭示章节必须大于 0", "warning")
        return
      }
      try {
        await getApi().outline.createReveal(getAppState()?.currentProjectId, {
          target_type: "world_entity",
          target_id: "00000000-0000-0000-0000-000000000000",
          secret_summary: description,
          reveal_stages: [{
            stage_index: 0,
            chapter_index: chapterIndex,
            reveal_content: description,
          }],
          status: document.getElementById("create-reveal-status")?.value || "planned",
        })
        toast("揭示已创建", "success")
        refreshCurrentView()
      } catch (err) {
        toast(err.message || "创建失败", "error")
      }
    },
  }])
}

export function editReveal(id, revealsList, guessLastChapter, buildForeshadowingOptions) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const r = (revealsList || []).find((item) => item.id === id)
  if (!r) return

  const description = r.secret_summary || ""
  const revealChapter = (r.reveal_stages && r.reveal_stages[0] && r.reveal_stages[0].chapter_index) || (guessLastChapter && guessLastChapter()) || 1
  const statusOptions = REVEAL_STATUSES.map(
    (s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${REVEAL_STATUS_LABELS[s] || s}</option>`,
  ).join("")
  const foreshadowingOptions = (buildForeshadowingOptions && buildForeshadowingOptions()) || ""

  const formHtml = `
    <div class="form-group">
      <label>描述 *</label>
      <textarea class="form-textarea" id="edit-reveal-description" rows="3">${esc(description)}</textarea>
    </div>
    <div class="form-group">
      <label>揭示章节 *</label>
      <input class="form-input" id="edit-reveal-chapter" type="number" min="1" value="${revealChapter}" />
    </div>
    <div class="form-group">
      <label>关联伏笔（可选）</label>
      <select class="form-select" id="edit-reveal-foreshadowing-id"><option value="">- 无 -</option>${foreshadowingOptions}</select>
    </div>
    <div class="form-group">
      <label>状态</label>
      <select class="form-select" id="edit-reveal-status">${statusOptions}</select>
    </div>
  `
  showModalHtml("编辑揭示", formHtml, [{
    text: "保存", class: "btn-primary", handler: async () => {
      const description = document.getElementById("edit-reveal-description")?.value?.trim()
      const chapterValue = document.getElementById("edit-reveal-chapter")?.value
      if (!description) { toast("请输入描述", "warning"); return }
      const chapterIndex = parseInt(chapterValue || "1", 10)
      if (!Number.isInteger(chapterIndex) || chapterIndex < 1) {
        toast("揭示章节必须大于 0", "warning")
        return
      }
      try {
        await getApi().outline.updateReveal(id, getAppState()?.currentProjectId, {
          secret_summary: description,
          reveal_stages: [{
            stage_index: 0,
            chapter_index: chapterIndex,
            reveal_content: description,
          }],
          status: document.getElementById("edit-reveal-status")?.value || "planned",
        })
        toast("揭示已保存", "success")
        refreshCurrentView()
      } catch (err) {
        toast(err.message || "保存失败", "error")
      }
    },
  }])
}

export function deleteReveal(id) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  confirmAction("确定删除此揭示？", async () => {
    try {
      await getApi().outline.deleteReveal(id, getAppState()?.currentProjectId)
      toast("已删除", "success")
      refreshCurrentView()
    } catch (err) {
      toast(err.message || "删除失败", "error")
    }
  })
}

/** 揭示状态就地更新（vanilla _bindEvents 中 .reveal-status-select 的 change 事件）。 */
export async function updateRevealStatus(id, newStatus) {
  const toast = getToast()
  try {
    await getApi().outline.updateReveal(id, getAppState()?.currentProjectId, { status: newStatus })
    toast("揭示状态已更新", "success")
    refreshCurrentView()
  } catch (err) {
    toast(err.message || "更新失败", "error")
  }
}

// ============================================================
// 信息推进分配（vanilla _bindEvents L2705-2730）
// ============================================================

export async function assignInformationPlan(planId, kind, threadId, unassignedForeshadowing, unassignedReveals) {
  const toast = getToast()
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  if (!threadId || !planId) return
  try {
    if (kind === "foreshadowing") {
      const plan = (unassignedForeshadowing || []).find((item) => item.id === planId)
      await api.outline.updateForeshadowing(planId, projectId, {
        related_thread_ids: Array.from(new Set([...(plan?.related_thread_ids || []), threadId])),
      })
    } else {
      const plan = (unassignedReveals || []).find((item) => item.id === planId)
      await api.outline.updateReveal(planId, projectId, {
        related_thread_ids: Array.from(new Set([...(plan?.related_thread_ids || []), threadId])),
      })
    }
    toast("信息推进计划已归入剧情线", "success")
    refreshCurrentView()
  } catch (err) {
    toast(err.message || "分配失败", "error")
  }
}

// ============================================================
// 剧情线 CRUD (vanilla L1696-1811)
// ============================================================

export function showCreateThreadForm() {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const formHtml = `
    <div class="form-group">
      <label>名称 *</label>
      <input class="form-input" id="create-thread-name" placeholder="剧情线名称" />
    </div>
    <div class="form-group">
      <label>类型</label>
      <select class="form-select" id="create-thread-type">
        <option value="main">主线</option>
        <option value="sub">支线</option>
        <option value="background">暗线</option>
      </select>
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="create-thread-desc" rows="3" placeholder="剧情线描述"></textarea>
    </div>
  `
  showModalHtml("新建剧情线", formHtml, [{
    text: "创建", class: "btn-primary", handler: async () => {
      const name = document.getElementById("create-thread-name")?.value
      if (!name) { toast("请输入名称", "warning"); return }
      try {
        await getApi().outline.createThread(getAppState()?.currentProjectId, {
          name,
          thread_type: document.getElementById("create-thread-type")?.value || "main",
          summary: document.getElementById("create-thread-desc")?.value || "",
        })
        toast("剧情线已创建", "success")
        refreshCurrentView()
      } catch (err) { toast(err.message || "创建失败", "error") }
    },
  }])
}

export function editThread(id, threadsList) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const thread = (threadsList || []).find((t) => (t.id || t.thread_id) === id)
  if (!thread) return

  const formHtml = `
    <div class="form-group">
      <label>名称</label>
      <input class="form-input" id="edit-thread-name" value="${esc(thread.name || thread.title)}" />
    </div>
    <div class="form-group">
      <label>类型</label>
      <select class="form-select" id="edit-thread-type">
        <option value="main" ${(thread.thread_type || "main") === "main" ? "selected" : ""}>主线</option>
        <option value="sub" ${thread.thread_type === "sub" ? "selected" : ""}>支线</option>
        <option value="background" ${thread.thread_type === "background" ? "selected" : ""}>暗线</option>
      </select>
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="edit-thread-desc" rows="3">${esc(thread?.description || thread?.summary || thread?.visible_goal || thread?.hidden_truth || "")}</textarea>
    </div>
  `
  showModalHtml("编辑剧情线", formHtml, [{
    text: "保存", class: "btn-primary", handler: async () => {
      try {
        await getApi().outline.updateThread(id, getAppState()?.currentProjectId, {
          name: document.getElementById("edit-thread-name")?.value,
          thread_type: document.getElementById("edit-thread-type")?.value,
          summary: document.getElementById("edit-thread-desc")?.value,
        })
        toast("已保存", "success")
        refreshCurrentView()
      } catch (err) { toast(err.message || "保存失败", "error") }
    },
  }])
}

export function threadDescription(thread) {
  return thread?.description || thread?.summary || thread?.visible_goal || thread?.hidden_truth || "-"
}

export function findThread(threadsList, id) {
  return (threadsList || []).find((thread) => (thread.id || thread.thread_id) === id) || null
}

export async function markThreadReviewed(id, threadsList) {
  const toast = getToast()
  const thread = findThread(threadsList, id)
  if (!thread) {
    toast("未找到目标剧情线", "error")
    return
  }
  const projectId = getAppState()?.currentProjectId
  await getApi().outline.updateThread(id, projectId, reviewThreadPayload(thread, "outline_threads"))
  toast(structureAssetDisplay(thread).displayState === "active" ? "剧情线已标记为已检查" : "剧情线已采用", "success")
  await refreshCurrentView()
}

export async function markThreadUnreviewed(id, threadsList) {
  const toast = getToast()
  const thread = findThread(threadsList, id)
  if (!thread) {
    toast("未找到目标剧情线", "error")
    return
  }
  const projectId = getAppState()?.currentProjectId
  await getApi().outline.updateThread(id, projectId, unreviewThreadPayload(thread))
  toast("剧情线已标记为需要人工检查", "success")
  await refreshCurrentView()
}

export function deleteThread(id) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  confirmAction("确定删除此剧情线？", async () => {
    try {
      await getApi().outline.deleteThread(id, getAppState()?.currentProjectId)
      toast("已删除", "success")
      refreshCurrentView()
    } catch (err) { toast(err.message || "删除失败", "error") }
  }, "确认删除")
}

// ============================================================
// 篇章 CRUD (vanilla L1813-1923)
// ============================================================

export function showCreateArcForm() {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const formHtml = `
    <div class="form-group">
      <label>名称 *</label>
      <input class="form-input" id="create-arc-name" placeholder="篇章名称" />
    </div>
    <div class="form-group">
      <label>起始章节</label>
      <input class="form-input" id="create-arc-start" type="number" min="1" value="1" />
    </div>
    <div class="form-group">
      <label>结束章节</label>
      <input class="form-input" id="create-arc-end" type="number" min="1" value="10" />
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="create-arc-desc" rows="3" placeholder="篇章描述"></textarea>
    </div>
  `
  showModalHtml("新建篇章", formHtml, [{
    text: "创建", class: "btn-primary", handler: async () => {
      const title = document.getElementById("create-arc-name")?.value
      if (!title) { toast("请输入名称", "warning"); return }
      try {
        await getApi().outline.createArc(getAppState()?.currentProjectId, {
          title,
          start_chapter: parseInt(document.getElementById("create-arc-start")?.value || "1", 10),
          end_chapter: parseInt(document.getElementById("create-arc-end")?.value || "10", 10),
          arc_goal: document.getElementById("create-arc-desc")?.value || "",
        })
        toast("篇章已创建", "success")
        refreshCurrentView()
      } catch (err) { toast(err.message || "创建失败", "error") }
    },
  }])
}

export function editArc(id, arcsList) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const arc = (arcsList || []).find((a) => (a.id || a.arc_id) === id)
  if (!arc) return

  const formHtml = `
    <div class="form-group">
      <label>名称</label>
      <input class="form-input" id="edit-arc-name" value="${esc(arc.title || arc.name || "")}" />
    </div>
    <div class="form-group">
      <label>起始章节</label>
      <input class="form-input" id="edit-arc-start" type="number" min="1" value="${arc.start_chapter ?? ""}" placeholder="未定" />
    </div>
    <div class="form-group">
      <label>结束章节</label>
      <input class="form-input" id="edit-arc-end" type="number" min="1" value="${arc.end_chapter ?? ""}" placeholder="未定" />
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="edit-arc-desc" rows="3">${esc(arc?.description || arc?.summary || arc?.arc_goal || arc?.core_conflict || "")}</textarea>
    </div>
  `
  showModalHtml("编辑篇章", formHtml, [{
    text: "保存", class: "btn-primary", handler: async () => {
      try {
        await getApi().outline.updateArc(id, getAppState()?.currentProjectId, {
          title: document.getElementById("edit-arc-name")?.value?.trim(),
          start_chapter: optionalPositiveInteger("edit-arc-start", "起始章节"),
          end_chapter: optionalPositiveInteger("edit-arc-end", "结束章节"),
          arc_goal: document.getElementById("edit-arc-desc")?.value?.trim(),
        })
        toast("已保存", "success")
        refreshCurrentView()
      } catch (err) { toast(err.message || "保存失败", "error") }
    },
  }])
}

export function arcDescription(arc) {
  return arc?.description || arc?.summary || arc?.arc_goal || arc?.core_conflict || "-"
}

function optionalPositiveInteger(inputId, label) {
  const raw = document.getElementById(inputId)?.value?.trim() || ""
  if (!raw) return null
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1) throw new Error(`${label}必须是正整数或留空`)
  return value
}

export function findArc(arcsList, id) {
  return (arcsList || []).find((arc) => (arc.id || arc.arc_id) === id) || null
}

export async function markArcReviewed(id, arcsList) {
  const toast = getToast()
  const arc = findArc(arcsList, id)
  if (!arc) {
    toast("未找到目标篇章", "error")
    return
  }
  const projectId = getAppState()?.currentProjectId
  await getApi().outline.updateArc(id, projectId, reviewThreadPayload(arc, "outline_arcs"))
  toast(structureAssetDisplay(arc).displayState === "active" ? "篇章已标记为已检查" : "篇章已采用", "success")
  await refreshCurrentView()
}

export function deleteArc(id) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  confirmAction("确定删除此篇章？", async () => {
    try {
      await getApi().outline.deleteArc(id, getAppState()?.currentProjectId)
      toast("已删除", "success")
      refreshCurrentView()
    } catch (err) { toast(err.message || "删除失败", "error") }
  }, "确认删除")
}

// ============================================================
// 批量操作 (vanilla L2770-2822)
// ============================================================

export function runBulkOutlineAction(scope, action, items) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  const selectedItems = selectedItemsFrom(
    items,
    getBulkSelection(scope),
    (item) => item.id || item.thread_id || item.arc_id,
  )
  if (!selectedItems.length) {
    toast("请先选择要处理的项目", "warning")
    return
  }
  const labels = {
    "delete-threads": "批量删除剧情线",
    "review-threads": "批量采用 / 标记已检查",
    "review-arcs": "批量采用 / 标记已检查",
    "delete-arcs": "批量删除篇章",
    "delete-foreshadowing": "批量删除伏笔",
    "delete-reveals": "批量删除揭示",
  }
  const confirmText = action === "review-threads" || action === "review-arcs" ? "确认处理" : "确认删除"
  confirmAction(
    `确定对选中的 ${selectedItems.length} 项执行「${labels[action] || "批量删除"}」吗？`,
    async () => {
      await executeBulkOutlineAction(scope, action, selectedItems)
    },
    confirmText,
  )
}

export async function executeBulkOutlineAction(scope, action, items) {
  const toast = getToast()
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const labels = {
    "delete-threads": "批量删除剧情线",
    "review-threads": "批量采用 / 标记已检查",
    "review-arcs": "批量采用 / 标记已检查",
    "delete-arcs": "批量删除篇章",
    "delete-foreshadowing": "批量删除伏笔",
    "delete-reveals": "批量删除揭示",
  }
  const result = await runBulkAction(items, async (item) => {
    if (action === "delete-threads") await api.outline.deleteThread(item.id || item.thread_id, projectId)
    else if (action === "review-threads") {
      await api.outline.updateThread(item.id || item.thread_id, projectId, reviewThreadPayload(item, "outline_threads_bulk"))
    } else if (action === "review-arcs") {
      await api.outline.updateArc(item.id || item.arc_id, projectId, reviewThreadPayload(item, "outline_arcs_bulk"))
    } else if (action === "delete-arcs") await api.outline.deleteArc(item.id || item.arc_id, projectId)
    else if (action === "delete-foreshadowing") await api.outline.deleteForeshadowing(item.id, projectId)
    else if (action === "delete-reveals") await api.outline.deleteReveal(item.id, projectId)
  })
  toast(
    bulkResultMessage(result, labels[action] || "批量删除", (item) => item.name || item.title || item.summary || item.secret_summary || item.id),
    result.failed.length ? "warning" : "success",
  )
  clearBulkSelection(scope)
  await refreshCurrentView()
}

// ============================================================
// 猜测最大章节（vanilla L1666-1688）
// ============================================================

export function guessLastChapter(args = {}) {
  const { foreshadowing = [], reveals = [], arcs = [], threads = [] } = args
  let maxChapter = 0
  for (const f of foreshadowing) {
    if (f.planned_seed_chapter > maxChapter) maxChapter = f.planned_seed_chapter
    if (f.planned_payoff_chapter > maxChapter) maxChapter = f.planned_payoff_chapter
  }
  for (const r of reveals) {
    if (r.reveal_stages) {
      for (const stage of r.reveal_stages) {
        if (stage.chapter_index > maxChapter) maxChapter = stage.chapter_index
      }
    }
  }
  for (const a of arcs) {
    if (a.end_chapter > maxChapter) maxChapter = a.end_chapter
    if (a.start_chapter > maxChapter) maxChapter = a.start_chapter
  }
  for (const t of threads) {
    if (t.planned_payoff_chapter > maxChapter) maxChapter = t.planned_payoff_chapter
    if (t.start_chapter > maxChapter) maxChapter = t.start_chapter
  }
  return maxChapter > 0 ? maxChapter : null
}

export function buildForeshadowingOptions(foreshadowing = []) {
  const esc = getEsc()
  return foreshadowing.map(
    (f) => `<option value="${esc(f.id)}">${esc(f.summary || f.name || "未命名")}</option>`,
  ).join("")
}
