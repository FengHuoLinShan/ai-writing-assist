/**
 * useWorldBible — world bible 视图的状态与操作 composable。
 *
 * 对应 vanilla worldBibleView（worldBibleView.js）的模块单例字段和方法；
 * DOM 事件用 Vue 绑定替代手动委托；模态框操作仍走 showModalHtml。
 * 投影轮询 / 简介轮询等后台任务使用 useWorkflowPolling。
 */
import { computed, reactive, ref, watch } from "vue"
import { getApi, getAppState, getRouteQuery, getRouter, getToast, getConfirm, getConfirmAction, getShowModalHtml, getCloseModal, getEsc, getErrorLog } from "../../../bridge/index.js"
import { useLeaveGuard } from "../../../composables/useLeaveGuard.js"
import { worldSession } from "../../world/worldSession.js"
import { pollTaskProgress } from "../../../../shared/workflowProgress.js"
import { worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import {
  clearCreativeContinuation,
  readCreativeContinuation,
  writeCreativeContinuation,
} from "../../generate/generateSession.js"
import { authorDecisionPresentation } from "../../generate/logic/generateLogic.js"
import {
  editorPayloadFromSource,
  editorSourceKey,
  formatAssetRefs,
  normalizeEditorPayload,
  parseAssetRefs,
  readDraftFromDom,
} from "../pages/worldBiblePageEditor.js"
import { BIBLE_CATEGORY_PRESETS, BIBLE_PAGE_TYPES } from "../pages/worldBiblePresentation.js"
import { publishImpactHtml, publishReceiptHtml } from "../pages/worldBiblePublishing.js"

const PROJECTION_TYPE = "context_brief"
const BIBLE_DISPLAY_MODES = new Set(["editor", "gallery", "filter", "graph"])
const NEW_CATEGORY_VALUE = "__new_category__"

const BIBLE_FALLBACK_TYPE = {
  label: "其他", title: "其他", desc: "未识别类别的世界书页面", color: "#64748b", symbol: "OT",
}

/**
 * 从 localStorage 恢复显示偏好。
 */
function storedDisplayPref(projectId, key, fallback) {
  try {
    const value = localStorage.getItem(`worldBible:${projectId}:${key}`)
    if (key === "displayMode" && BIBLE_DISPLAY_MODES.has(value)) return value
    if (key === "activeCategory") return value || fallback
  } catch { /* ignore */ }
  return fallback
}

function saveDisplayPref(projectId, key, value) {
  try {
    localStorage.setItem(`worldBible:${projectId}:${key}`, value)
  } catch { /* ignore */ }
}

/**
 * taskStorageKey — localStorage 键，用于跨刷新恢复投影任务。
 */
function taskStorageKey(projectId, pageId) {
  return `worldBibleProjection:${projectId}:${pageId}:${PROJECTION_TYPE}`
}

function isTerminalTask(task) {
  return ["done", "failed", "cancelled"].includes(task?.status)
}

export function useWorldBible(props) {
  const api = getApi()
  const router = getRouter()
  const toast = getToast()
  const confirm = getConfirm()
  const confirmAction = getConfirmAction()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const esc = getEsc()
  const errorLog = getErrorLog()

  // ---- data from props (pre-fetched by worldIsland load()) ----
  const projectId = computed(() => props.projectId)
  const pages = computed(() => props.bible?.pages || [])
  const savedCategories = reactive(new Map())
  const categories = computed(() => {
    const merged = new Map((props.bible?.categories || []).map((category) => [category.id || category.category_key, category]))
    for (const [id, category] of savedCategories) merged.set(id, category)
    return Array.from(merged.values())
  })
  const savedDrafts = reactive(new Map())
  const drafts = computed(() => {
    const merged = new Map((props.bible?.drafts || []).map((draft) => [draft.id, draft]))
    for (const [id, draft] of savedDrafts) merged.set(id, draft)
    return Array.from(merged.values())
  })
  const synopsis = ref(props.bible?.synopsis || null)
  const savedPageTemplates = reactive(new Map())
  const pageTemplates = computed(() => {
    const merged = new Map((props.bible?.pageTemplates || []).map((template) => [template.id || template.template_key, template]))
    for (const [id, template] of savedPageTemplates) merged.set(id, template)
    return Array.from(merged.values()).filter((template) => template.status !== "archived")
  })
  const activationProfiles = computed(() => props.bible?.activationProfiles || [])
  const bibleDeepLink = computed(() => props.bibleDeepLink || { draftId: "", pageId: "" })

  // ---- reactive state (对应 vanilla 模块单例字段) ----
  const displayMode = ref(props.defaultDisplayMode
    || storedDisplayPref(projectId.value, "displayMode", "editor"))
  const activeCategory = ref(storedDisplayPref(projectId.value, "activeCategory", "all"))
  const galleryCategory = ref(null)
  const activeActivationProfileId = ref(worldSession.bible.activeActivationProfileId || null)
  const activationTrace = ref(null)
  const synopsisTask = ref(null)
  const synopsisTerminalTaskId = ref(null)
  const synopsisPoller = ref(null)
  const suggestions = ref([])
  const suggestionHistory = ref([])
  const conflicts = ref([])
  const semanticInspectionPending = ref(false)
  const projectionTask = ref(null)
  const projectionConflictHint = ref(null)
  const projectionPoller = ref(null)
  const projectionRetryPending = ref(false)
  const editorMutationPending = ref(false)
  const beforeUnloadBound = ref(false)
  const suggestionBatchKey = ref(null)
  let disposed = false
  let activationGeneration = 0
  let projectionGeneration = 0
  let synopsisGeneration = 0

  function ownsProject(novelId) {
    return !disposed
      && projectId.value === novelId
      && getAppState()?.currentProjectId === novelId
  }

  function ownsPage(novelId, pageId) {
    return ownsProject(novelId) && activePageId.value === pageId
  }

  // ---- active page / draft state (从 session 恢复) ----
  const activePageId = ref(worldSession.bible.activePageId || null)
  const activeDraftId = ref(worldSession.bible.activeDraftId || null)
  const editorBaseline = ref(worldSession.bible.editorBaseline || null)
  const editorBaselineKey = ref(worldSession.bible.editorBaselineKey || null)

  function captureEditorOwner() {
    return { novelId: projectId.value, pageId: activePageId.value, draftId: activeDraftId.value }
  }

  function ownsEditor(owner) {
    return ownsPage(owner.novelId, owner.pageId) && activeDraftId.value === owner.draftId
  }

  function captureModalOwner(node = null) {
    const body = document.getElementById("modal-body")
    const overlay = document.getElementById("modal-overlay")
    return {
      body,
      overlay,
      node: node || body?.firstElementChild || null,
      open: Boolean(overlay && !overlay.classList.contains("hidden")),
    }
  }

  function ownsModalOwner(owner) {
    if (!owner?.body || !owner?.overlay) return true
    if (document.getElementById("modal-body") !== owner.body || document.getElementById("modal-overlay") !== owner.overlay) return false
    if (!owner.open) {
      return owner.overlay.classList.contains("hidden") && owner.body.firstElementChild === owner.node
    }
    return Boolean(
      owner.node?.isConnected
      && owner.body.contains(owner.node)
      && !owner.overlay.classList.contains("hidden"),
    )
  }

  // ---- 从 pageId/draftId 解析对象 ----
  const activePage = computed(() => {
    if (!activePageId.value) return null
    return pages.value.find((p) => p.id === activePageId.value) || null
  })

  const activeDraft = computed(() => {
    if (!activeDraftId.value) return null
    return drafts.value.find((d) => d.id === activeDraftId.value) || null
  })

  /** 当前编辑源（draft 优先于 page） */
  const editSource = computed(() => activeDraft.value || activePage.value)

  /** 当前页面是否有工作稿 */
  const draftForActivePage = computed(() => {
    if (!activePageId.value) return null
    return drafts.value.find((d) => d.page_id === activePageId.value) || null
  })

  const isWorkingDraft = computed(() => Boolean(activeDraft.value))

  let semanticInspectionController = null
  // ---- 初始化 ----
  function initialize() {
    const dl = bibleDeepLink.value
    if (dl.draftId) {
      const requestedDraft = drafts.value.find((d) => d.id === dl.draftId)
      if (requestedDraft) {
        activeDraftId.value = requestedDraft.id
        activePageId.value = requestedDraft.page_id
          ? (pages.value.find((p) => p.id === requestedDraft.page_id)?.id || null)
          : null
        displayMode.value = "editor"
      }
    } else if (dl.pageId) {
      const requestedPage = pages.value.find((p) => p.id === dl.pageId)
      if (requestedPage) {
        activePageId.value = requestedPage.id
        activeDraftId.value = draftForActivePage.value?.id || null
        displayMode.value = "editor"
      }
    }

    // activation profile default
    if (!activationProfiles.value.some((profile) => profile.id === activeActivationProfileId.value)) {
      activeActivationProfileId.value = activationProfiles.value[0]?.id || null
    }

    // synopsis recovery
    const syn = props.bible?.synopsis
    if (syn?.active_task_id && syn.active_task_id !== synopsisTerminalTaskId.value && !synopsisPoller.value) {
      synopsisTask.value = { task_id: syn.active_task_id, status: "running" }
      startSynopsisPolling(syn.active_task_id)
    }

    // fallback active page
    if (!activePageId.value && !activeDraftId.value && pages.value.length) {
      activePageId.value = pages.value[0].id
    }
    if (activePageId.value && !activeDraftId.value) {
      activeDraftId.value = draftForActivePage.value?.id || null
    }
    if (!activePageId.value && !activeDraftId.value) {
      const freeDraft = drafts.value.find((d) => !d.page_id)
      if (freeDraft) activeDraftId.value = freeDraft.id
    }

    // restore projection task for active page
    if (activePageId.value) {
      restoreProjectionTask(activePageId.value)
    }

    // Set editor baseline
    resetEditorBaseline()

    // Sync to session
    syncSession()
    if (dl.openSuggestions) {
      ensureSuggestionContinuation(dl.suggestionId)
      void openSuggestions(dl.suggestionId)
    }
    if (dl.openConflicts) void openConflicts(dl.conflictId)
    if (dl.adoptionPackageId) void openAdoptionPackage(dl.adoptionPackageId)
  }

  function syncSession() {
    worldSession.bible.activePageId = activePageId.value
    worldSession.bible.activeDraftId = activeDraftId.value
    worldSession.bible.activeActivationProfileId = activeActivationProfileId.value
    worldSession.bible.editorBaseline = editorBaseline.value
    worldSession.bible.editorBaselineKey = editorBaselineKey.value
  }

  function replaceEditorDeepLink({ pageId = null, draftId = null } = {}) {
    const query = getRouteQuery()
    query.delete("entity_id")
    query.delete("page_id")
    query.delete("draft_id")
    if (draftId) query.set("draft_id", draftId)
    else if (pageId) query.set("page_id", pageId)
    router.commitCurrentQuery?.(query, "replace")
  }

  function rememberDraft(draft) {
    if (!draft?.id) return
    writeCreativeContinuation(projectId.value, {
      destination: "world_bible_draft",
      route: { draft_id: draft.id, page_id: draft.page_id || null },
    })
  }

  function clearDraftContinuation(draftId) {
    const continuation = readCreativeContinuation(projectId.value)
    if (continuation?.destination === "world_bible_draft" && continuation.route.draft_id === draftId) {
      clearCreativeContinuation(projectId.value)
    }
  }

  function rememberSuggestion(suggestionId) {
    if (!suggestionId) return
    writeCreativeContinuation(projectId.value, {
      destination: "world_suggestion_review",
      route: { suggestion_id: suggestionId },
    })
  }

  function ensureSuggestionContinuation(suggestionId) {
    const continuation = readCreativeContinuation(projectId.value)
    if (continuation?.destination === "world_suggestion_review" && continuation.route.suggestion_id === suggestionId) return
    rememberSuggestion(suggestionId)
  }

  function clearSuggestionContinuation(suggestionId) {
    const continuation = readCreativeContinuation(projectId.value)
    if (continuation?.destination === "world_suggestion_review" && continuation.route.suggestion_id === suggestionId) {
      clearCreativeContinuation(projectId.value)
    }
  }

  // ---- display mode ----
  function setDisplayMode(mode) {
    if (!BIBLE_DISPLAY_MODES.has(mode)) mode = "editor"
    if (mode !== displayMode.value && editorHasUnsavedChanges()) {
      if (!confirm("当前页面有未保存修改，确定放弃并切换视图吗？")) return
    }
    displayMode.value = mode
    if (mode !== "gallery") galleryCategory.value = null
    saveDisplayPref(projectId.value, "displayMode", mode)
  }

  function setActiveCategory(category) {
    if (editorHasUnsavedChanges() && !confirm("当前页面有未保存修改，确定放弃并切换分类吗？")) return
    activeCategory.value = category || "all"
    saveDisplayPref(projectId.value, "activeCategory", activeCategory.value)
  }

  function openGalleryCategory(category) {
    if (editorHasUnsavedChanges() && !confirm("当前页面有未保存修改，确定放弃并打开图鉴吗？")) return
    galleryCategory.value = category || "all"
  }

  function backToGalleryHome() {
    if (editorHasUnsavedChanges() && !confirm("当前页面有未保存修改，确定放弃并返回图鉴吗？")) return
    galleryCategory.value = null
  }

  function openPageCard(pageId) {
    const page = pages.value.find((p) => p.id === pageId)
    if (!page) return
    if (editorHasUnsavedChanges() && !confirm("当前页面有未保存修改，确定放弃并打开其他页面吗？")) return
    activePageId.value = page.id
    activeDraftId.value = draftForActivePage.value?.id || null
    displayMode.value = "editor"
    galleryCategory.value = null
    saveDisplayPref(projectId.value, "displayMode", "editor")
    resetEditorBaseline()
    syncSession()
    replaceEditorDeepLink({ pageId: page.id })
    restoreProjectionTask(page.id)
  }

  function openDraft(draftId) {
    const draft = drafts.value.find((d) => d.id === draftId)
    if (!draft) return
    if (editorHasUnsavedChanges() && !confirm("当前页面有未保存修改，确定放弃并切换工作稿吗？")) return
    activeDraftId.value = draft.id
    activePageId.value = draft.page_id
      ? (pages.value.find((p) => p.id === draft.page_id)?.id || null)
      : null
    displayMode.value = "editor"
    resetEditorBaseline()
    syncSession()
    replaceEditorDeepLink({ draftId: draft.id })
    rememberDraft(draft)
  }

  // ---- page navigation / categories ----
  function typeMeta(type) {
    if (type === "custom") return BIBLE_PAGE_TYPES.custom
    const category = categories.value.find((c) => c.category_key === type)
    if (category) {
      return {
        label: category.name,
        title: category.name,
        desc: category.description || "项目自定义世界书分类",
        color: category.color || "#64748b",
        symbol: category.icon || String(category.name || type).slice(0, 2),
      }
    }
    return BIBLE_PAGE_TYPES[type] || { ...BIBLE_FALLBACK_TYPE, title: type || BIBLE_FALLBACK_TYPE.title, label: type || BIBLE_FALLBACK_TYPE.label }
  }

  function categoryItems(includeAll = false) {
    const counts = new Map()
    for (const page of pages.value) {
      const t = page.page_type || "custom"
      counts.set(t, (counts.get(t) || 0) + 1)
    }
    const activeCats = categories.value.filter((c) => c.status !== "archived")
    const knownKeys = new Set(activeCats.map((c) => c.category_key))
    const known = activeCats.map((c) => ({
      type: c.category_key,
      count: counts.get(c.category_key) || 0,
      meta: typeMeta(c.category_key),
    }))
    const unknown = Array.from(counts.entries())
      .filter(([t]) => !knownKeys.has(t))
      .sort(([a], [b]) => String(a).localeCompare(String(b)))
      .map(([t, count]) => ({ type: t, count, meta: typeMeta(t) }))
    const items = [...known, ...unknown]
    if (!includeAll) return items
    return [{ type: "all", count: pages.value.length, meta: { label: "全部", title: "全部", desc: "查看所有世界书页面", color: "#6366f1", symbol: "ALL" } }, ...items]
  }

  function pagesForCategory(category) {
    if (!category || category === "all") return pages.value
    return pages.value.filter((p) => (p.page_type || "custom") === category)
  }

  function statusLabel(status) {
    return worldAssetDisplay({ status }).label
  }

  function taskStatusLabel(status) {
    const labels = {
      missing: "尚未生成", pending: "等待处理", queued: "等待处理",
      running: "生成中", done: "已完成", success: "已完成",
      fresh: "已更新", degraded: "降级版本", refreshing: "生成中",
      failed: "生成失败", cancelled: "已取消", stale: "需要刷新",
    }
    return labels[status] || "状态未知"
  }

  function pageExcerpt(page) {
    const text = String(page?.free_text || "").replace(/\s+/g, " ").trim()
    if (!text) return "暂无正文摘要"
    return text.length > 120 ? text.slice(0, 120) + "..." : text
  }

  function categoryOptions(selected) {
    const cats = categories.value.length
      ? categories.value.filter((c) => c.status !== "archived" || c.category_key === selected)
      : Object.keys(BIBLE_PAGE_TYPES)
          .filter((k) => k !== "item")
          .map((k) => ({ category_key: k, name: BIBLE_PAGE_TYPES[k].title }))
    if (selected && !cats.some((c) => c.category_key === selected)) {
      cats.push({ category_key: selected, name: selected === "custom" ? "未分类" : `${selected}（历史类别）` })
    }
    return cats.map((category) => category.category_key === "custom" ? { ...category, name: "未分类" } : category)
  }

  function rememberCategory(category, fallback = {}) {
    const saved = { ...fallback, ...category }
    savedCategories.set(saved.id || saved.category_key, saved)
    return saved
  }

  // ---- editor state (baseline / unsaved changes) ----
  function setEditorBaseline(source) {
    editorBaselineKey.value = editorSourceKey(source)
    editorBaseline.value = source ? normalizeEditorPayload(editorPayloadFromSource(source)) : null
    syncSession()
  }

  function resetEditorBaseline() {
    setEditorBaseline(editSource.value)
  }

  function editorHasUnsavedChanges() {
    const currentSource = () => editSource.value
    // If the DOM is available, read from DOM (matches vanilla _editorHasUnsavedChanges behavior)
    const titleEl = typeof document !== "undefined" && document.getElementById("bible-title")
    if (titleEl) {
      try {
        const current = normalizeEditorPayload({
          title: document.getElementById("bible-title")?.value?.trim() || "",
          page_type: document.getElementById("bible-page-type")?.value || "custom",
          free_text: document.getElementById("bible-free-text")?.value || "",
          sort_order: Number(document.getElementById("bible-sort-order")?.value || 0),
          linked_asset_refs_json: parseAssetRefs(document.getElementById("bible-asset-refs")?.value || ""),
          sections_json: readSectionsFromDom(),
        })
        const source = currentSource()
        if (!source) return true
        const baseline = editorBaselineKey.value === editorSourceKey(source)
          ? editorBaseline.value
          : normalizeEditorPayload(editorPayloadFromSource(source))
        return JSON.stringify(current) !== JSON.stringify(baseline)
      } catch {
        return true
      }
    }
    // Fallback: compare from source object (no DOM available)
    const source = currentSource()
    if (!source) return false
    try {
      const current = normalizeEditorPayload(editorPayloadFromSource(source))
      const baseline = editorBaselineKey.value === editorSourceKey(source)
        ? editorBaseline.value
        : normalizeEditorPayload(editorPayloadFromSource(source))
      return JSON.stringify(current) !== JSON.stringify(baseline)
    } catch {
      return true
    }
  }

  function confirmDiscardEditorChanges(message) {
    if (!editorHasUnsavedChanges()) return true
    return confirm(message)
  }

  let externalLeaveGuard = null
  let externalHasUnsavedChanges = null
  function setExternalLeaveGuard(fn, isDirty) {
    externalLeaveGuard = typeof fn === "function" ? fn : null
    externalHasUnsavedChanges = typeof isDirty === "function" ? isDirty : null
  }

  // ---- leave guard ----
  useLeaveGuard(() => {
    return confirmDiscardEditorChanges("当前世界书页面有未保存修改，确定放弃并离开吗？")
      && (!externalLeaveGuard || externalLeaveGuard())
  })

  // 应用内导航有 useLeaveGuard；刷新/关闭标签页必须依赖 beforeunload，
  // 否则未保存的世界书编辑会静默丢失（与写作台的持久化守卫对齐）
  function handleBeforeUnload(event) {
    if (!editorHasUnsavedChanges() && !externalHasUnsavedChanges?.()) return
    event.preventDefault()
    event.returnValue = ""
  }
  if (typeof window !== "undefined" && !beforeUnloadBound.value) {
    window.addEventListener("beforeunload", handleBeforeUnload)
    beforeUnloadBound.value = true
  }

  // ---- CRUD: Save / Publish / Discard ----
  async function savePage(refreshView = false, modalOwner = null) {
    if (editorMutationPending.value) return false
    const page = activePage.value
    let draft = activeDraft.value || draftForActivePage.value
    if (!page && !draft) return false
    const owner = captureEditorOwner()
    const novelId = owner.novelId
    editorMutationPending.value = true
    try {
      const payload = {
        title: document.getElementById("bible-title")?.value?.trim() || "",
        page_type: document.getElementById("bible-page-type")?.value || "custom",
        free_text: document.getElementById("bible-free-text")?.value || "",
        sort_order: Number(document.getElementById("bible-sort-order")?.value || 0),
        linked_asset_refs_json: parseAssetRefs(document.getElementById("bible-asset-refs")?.value || ""),
        sections_json: readSectionsFromDom(),
      }
      if (!payload.title) {
        toast("标题不能为空", "warning")
        return false
      }
      if (!draft) {
        draft = await api.world.createBibleDraft({
          novel_id: novelId,
          page_id: page.id,
        })
      }
      draft = await api.world.updateBibleDraft(draft.id, payload, novelId)
      if (!ownsEditor(owner) || (modalOwner && !ownsModalOwner(modalOwner))) return false
      savedDrafts.set(draft.id, draft)
      activeDraftId.value = draft.id
      setEditorBaseline(draft)
      rememberDraft(draft)
      toast("工作稿已保存；正式页面尚未变化", "success")
      if (refreshView) router.refresh()
      return true
    } catch (err) {
      if (ownsEditor(owner) && (!modalOwner || ownsModalOwner(modalOwner))) toast(err.message || "保存失败", "error")
      return false
    } finally {
      editorMutationPending.value = false
    }
  }

  function readSectionsFromDom() {
    return Array.from(document.querySelectorAll(".world-bible-section-editor")).map((node, index) => {
      const field = (name) => node.querySelector(`[data-section-field="${name}"]`)
      const title = field("title")?.value?.trim() || ""
      if (!title) throw new Error(`第 ${index + 1} 个分区标题不能为空`)
      return {
        section_id: node.getAttribute("data-section-id"),
        section_type: field("section_type")?.value || "markdown",
        title,
        body_markdown: field("body_markdown")?.value || "",
        sort_order: (index + 1) * 10,
        linked_asset_ref_hashes: String(field("linked_asset_ref_hashes")?.value || "")
          .split(/\n+/).map((v) => v.trim()).filter(Boolean),
        projection_policy: field("projection_policy")?.value || "eligible",
        sensitivity_hint: field("sensitivity_hint")?.value || "author_safe",
      }
    })
  }

  function captureSectionsFromDom() {
    const source = editSource.value
    if (!source) return []
    const title = document.getElementById("bible-title")
    const pageType = document.getElementById("bible-page-type")
    const freeText = document.getElementById("bible-free-text")
    const sortOrder = document.getElementById("bible-sort-order")
    const assetRefs = document.getElementById("bible-asset-refs")
    if (title) source.title = title.value
    if (pageType) source.page_type = pageType.value
    if (freeText) source.free_text = freeText.value
    if (sortOrder) source.sort_order = Number(sortOrder.value || 0)
    if (assetRefs) {
      try {
        source.linked_asset_refs_json = parseAssetRefs(assetRefs.value || "")
      } catch (err) {
        toast(err.message || "读取页面引用失败", "error")
      }
    }
    try {
      source.sections_json = readSectionsFromDom()
    } catch (err) {
      toast(err.message || "读取分区失败", "error")
    }
    return source.sections_json || []
  }

  function addSection() {
    const source = editSource.value
    if (!source) return
    const sections = [...captureSectionsFromDom()]
    const used = new Set(sections.map((s) => s.section_id))
    let id = `section_${Date.now().toString(36)}`
    let suffix = 1
    while (used.has(id)) id = `section_${Date.now().toString(36)}_${suffix++}`
    sections.push({
      section_id: id,
      section_type: "markdown",
      title: "新分区",
      body_markdown: "",
      sort_order: (sections.length + 1) * 10,
      linked_asset_ref_hashes: [],
      projection_policy: "eligible",
      sensitivity_hint: "author_safe",
    })
    source.sections_json = sections
    // Trigger re-render of section editor via reactive
    rerenderSectionEditor()
  }

  function removeSection(sectionId) {
    const source = editSource.value
    if (!source) return
    source.sections_json = captureSectionsFromDom().filter((s) => s.section_id !== sectionId)
    rerenderSectionEditor()
  }

  function moveSection(sectionId, direction) {
    const source = editSource.value
    if (!source) return
    const sections = [...captureSectionsFromDom()]
    const index = sections.findIndex((s) => s.section_id === sectionId)
    const next = index + direction
    if (index < 0 || next < 0 || next >= sections.length) return
    const tmp = sections[index]
    sections[index] = sections[next]
    sections[next] = tmp
    source.sections_json = sections.map((s, i) => ({ ...s, sort_order: (i + 1) * 10 }))
    rerenderSectionEditor()
  }

  function rerenderSectionEditor() {
    // We use a reactive sections signal to trigger re-render in the component
    sectionsSignal.value = Date.now()
  }

  // Force reactive update signal for sections
  const sectionsSignal = ref(0)

  async function commitPublish(draft, expectedImpactScopeHash = null) {
    if (editorMutationPending.value) return false
    const owner = captureEditorOwner()
    const modalOwner = captureModalOwner()
    editorMutationPending.value = true
    try {
      const validation = api.world.getLatestWorldValidationRun
        ? await api.world.getLatestWorldValidationRun(owner.novelId, {
            scope: "targeted",
            target_type: "world_bible_draft",
            target_id: draft.id,
          })
        : null
      const publishArgs = [draft.id, owner.novelId, expectedImpactScopeHash]
      if (validation?.id) publishArgs.push(validation.id)
      const page = await api.world.publishBibleDraft(...publishArgs)
      if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
      closeModal()
      clearDraftContinuation(draft.id)
      activeDraftId.value = null
      activePageId.value = page.id
      replaceEditorDeepLink({ pageId: page.id })
      toast("页面已发布，世界观简介已标记为需要刷新", "success")
      await router.refresh()
      if (page.validation_receipt) {
        showModalHtml(
          "发布完成 · 检查回执",
          publishReceiptHtml(page.validation_receipt, esc),
          [{ text: "知道了", class: "btn-primary", handler: closeModal }],
          { size: "large" },
        )
      }
      return true
    } catch (err) {
      if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
      const message = err.status === 409
        ? "暂时无法发布。工作稿已保留；请在“世界健康”重新校验，并核对正式页或显式引用关系已变化。"
        : err.message || "发布失败"
      closeModal()
      toast(message, err.status === 409 ? "warning" : "error")
      return false
    } finally {
      editorMutationPending.value = false
    }
  }

  async function publishDraft() {
    const saved = await savePage(false)
    if (!saved) return false
    const draft = activeDraft.value || draftForActivePage.value
    if (!draft?.id) return false
    try {
      const impact = await api.world.previewBibleDraftPublishImpact(
        draft.id,
        projectId.value,
      )
      showModalHtml(
        "发布前影响核对",
        publishImpactHtml(impact, esc),
        [
          { text: "继续编辑", class: "btn-ghost", handler: closeModal },
          {
            text: "确认发布",
            class: "btn-primary",
            handler: () => commitPublish(draft, impact.impact_scope_hash),
          },
        ],
        { size: "large" },
      )
      return true
    } catch (err) {
      if (err.status === 409) {
        toast("正式页已变化。工作稿已保留，请重新核对后发布。", "warning")
        return false
      }
      showModalHtml(
        "影响预演暂不可用",
        `<p>工作稿已经保存，但暂时无法读取显式引用影响。你可以稍后重试，或在知道“自由文本和其他创作领域未检查”的前提下继续发布。</p>`,
        [
          { text: "返回编辑", class: "btn-ghost", handler: closeModal },
          {
            text: "仍然发布",
            class: "btn-primary",
            handler: () => commitPublish(draft),
          },
        ],
      )
      return false
    }
  }

  function discardDraft() {
    const draft = activeDraft.value || draftForActivePage.value
    if (!draft) return
    // vanilla 走 confirmAction 应用模态（"确认操作" + 危险按钮），非原生 confirm
    return confirmAction("丢弃这个工作稿？正式页面和历史版本不会受影响。", async () => {
      const owner = captureEditorOwner()
      const modalOwner = captureModalOwner()
      try {
        await api.world.discardBibleDraft(draft.id, owner.novelId)
        if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
        clearDraftContinuation(draft.id)
        activeDraftId.value = null
        if (!draft.page_id) {
          activePageId.value = pages.value[0]?.id || null
        }
        syncSession()
        replaceEditorDeepLink({ pageId: activePageId.value })
        toast("工作稿已丢弃", "success")
        router.refresh()
      } catch (err) {
        if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
          toast(err.message || "丢弃工作稿失败", "error")
          return false
        }
        return true
      }
    })
  }

  async function applySelectedPageTemplate() {
    const templateKey = document.getElementById("bible-page-template")?.value || ""
    if (!templateKey) {
      toast("请选择页面模板", "warning")
      return
    }
    const owner = captureEditorOwner()
    try {
      let draft = activeDraft.value || draftForActivePage.value
      if (!draft && activePage.value) {
        draft = await api.world.createBibleDraft({
          novel_id: owner.novelId,
          page_id: owner.pageId,
        })
      }
      if (!draft) return
      const selected = pageTemplates.value.find((t) => t.template_key === templateKey)
      draft = await api.world.applyBiblePageTemplate(draft.id, {
        template_key: templateKey,
        template_version: selected?.version_number || 1,
        replace_sections: false,
      }, owner.novelId)
      if (!ownsEditor(owner)) return false
      savedDrafts.set(draft.id, draft)
      activeDraftId.value = draft.id
      setEditorBaseline(draft)
      sectionsSignal.value = Date.now()
      toast("模板已生成工作稿分区；发布前可继续编辑", "success")
      return true
    } catch (err) {
      if (ownsEditor(owner)) toast(err.message || "应用模板失败", "error")
      return false
    }
  }

  // ---- create page ----
  function createPage() {
    showCreatePageStep({
      title: "世界基本背景",
      categoryKey: "background",
      templateKey: "",
    })
  }

  function readCreatePageStep(state) {
    state.title = document.getElementById("bible-create-title")?.value ?? state.title
    state.categoryKey = document.getElementById("bible-create-type")?.value || state.categoryKey
    state.templateKey = document.getElementById("bible-create-template")?.value ?? state.templateKey
    return state
  }

  function showCreatePageStep(state) {
    const options = categoryOptions(state.categoryKey).filter((category) => category.category_key !== "custom")
    if (state.categoryKey && state.categoryKey !== NEW_CATEGORY_VALUE && !options.some((category) => category.category_key === state.categoryKey)) {
      options.push({ category_key: state.categoryKey, name: typeMeta(state.categoryKey).title })
    }
    const formHtml = `
      <div class="form-group">
        <label for="bible-create-title">页面标题 *</label>
        <input class="form-input" id="bible-create-title" value="${esc(state.title)}" />
      </div>
      <div class="form-group">
        <label for="bible-create-type">页面分类</label>
        <select class="form-select" id="bible-create-type">
          ${options.map((category) => `<option value="${esc(category.category_key)}"${category.category_key === state.categoryKey ? " selected" : ""}>${esc(category.name)}</option>`).join("")}
          <option value="${NEW_CATEGORY_VALUE}">＋新建分类…</option>
        </select>
      </div>
      <div class="form-group">
        <label for="bible-create-template">页面模板</label>
        <select class="form-select" id="bible-create-template">
          <option value=""${state.templateKey ? "" : " selected"}>空白页</option>
          ${pageTemplates.value.map((template) => `<option value="${esc(template.template_key)}"${template.template_key === state.templateKey ? " selected" : ""}>${esc(template.name)} · v${esc(template.version_number)}</option>`).join("")}
        </select>
      </div>
    `
    showModalHtml("新建世界书页面", formHtml, [
      {
        text: "创建",
        class: "btn-primary",
        handler: async () => {
          readCreatePageStep(state)
          if (state.categoryKey === NEW_CATEGORY_VALUE || state.categoryKey === "custom") {
            state.previousCategoryKey ||= "background"
            showCategoryCreator(state)
            return false
          }
          const owner = captureEditorOwner()
          const modalOwner = captureModalOwner(document.getElementById("bible-create-title"))
          const title = state.title.trim()
          if (!title) {
            toast("请输入页面标题", "warning")
            return false
          }
          try {
            const templateKey = state.templateKey
            const template = pageTemplates.value.find((t) => t.template_key === templateKey)
            const createPayload = {
              novel_id: owner.novelId,
              title,
              page_type: state.categoryKey,
            }
            if (templateKey) {
              createPayload.template_key = templateKey
              createPayload.template_version = template?.version_number || 1
            }
            let draft = await api.world.createBibleDraft(createPayload)
            if (templateKey) {
              draft = await api.world.applyBiblePageTemplate(draft.id, {
                template_key: templateKey,
                template_version: template?.version_number || 1,
                replace_sections: true,
              }, owner.novelId)
            }
            if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
            savedDrafts.set(draft.id, draft)
            activeDraftId.value = draft.id
            activePageId.value = null
            displayMode.value = "editor"
            galleryCategory.value = null
            saveDisplayPref(owner.novelId, "displayMode", "editor")
            setEditorBaseline(draft)
            syncSession()
            replaceEditorDeepLink({ draftId: draft.id })
            toast("工作稿已创建；发布后才进入世界观简介来源", "success")
            return true
          } catch (err) {
            if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
              toast(err.message || "创建页面失败", "error")
              return false
            }
            return true
          }
        },
      },
      { text: "取消", class: "btn-ghost", handler: closeModal },
    ])
    const categorySelect = document.getElementById("bible-create-type")
    if (Array.from(categorySelect?.options || []).some((option) => option.value === state.categoryKey)) categorySelect.value = state.categoryKey
    const templateSelect = document.getElementById("bible-create-template")
    if (templateSelect) templateSelect.value = state.templateKey
    categorySelect?.addEventListener("change", (event) => {
      const previousCategoryKey = state.categoryKey
      readCreatePageStep(state)
      if (event.target.value === NEW_CATEGORY_VALUE) {
        state.previousCategoryKey = previousCategoryKey
        showCategoryCreator(state)
      }
    })
  }

  // ---- projection ----
  async function refreshProjection(force) {
    const page = activePage.value
    if (!page) return
    const novelId = projectId.value
    const pageId = page.id
    try {
      const result = await api.world.refreshBibleProjection(pageId, novelId, PROJECTION_TYPE, force)
      localStorage.setItem(taskStorageKey(novelId, pageId), result.task_id)
      if (!ownsPage(novelId, pageId)) return false
      const task = await api.tasks.get(result.task_id, novelId)
      if (!ownsPage(novelId, pageId)) return false
      projectionTask.value = task
      projectionConflictHint.value = null
      toast(result.existing ? "已有刷新任务正在运行" : "刷新任务已提交", "success")
      if (!isTerminalTask(task)) startProjectionPolling(result.task_id, pageId)
    } catch (err) {
      const apiErr = errorLog?._lastApiError || null
      if (err.status === 409 || apiErr?.status === 409) {
        if (errorLog) errorLog._lastApiError = null
        const finishedTaskId = extractFinishedTaskId(err, apiErr)
        if (finishedTaskId) {
          localStorage.setItem(taskStorageKey(novelId, pageId), finishedTaskId)
          if (!ownsPage(novelId, pageId)) return false
          try {
            const task = await api.tasks.get(finishedTaskId, novelId)
            if (!ownsPage(novelId, pageId)) return false
            projectionTask.value = task
          } catch {
            if (ownsPage(novelId, pageId)) projectionTask.value = null
          }
        }
        if (!ownsPage(novelId, pageId)) return false
        projectionConflictHint.value = "上次刷新已结束，可使用强制重新刷新。"
        toast("上次刷新已结束，如需重跑请使用强制刷新", "warning")
      } else {
        if (ownsPage(novelId, pageId)) toast(projectionRefreshErrorMessage(err), "error")
      }
      return false
    }
  }

  function projectionRefreshErrorMessage(err) {
    const msg = err?.message || ""
    if (msg.includes("No handler registered") || msg.includes("world_bible_projection_refresh")) {
      return "资料刷新任务暂不可用，请确认后台服务已更新并重启后重试"
    }
    return msg || "刷新投影失败"
  }

  async function restoreProjectionTask(pageId) {
    stopProjectionPolling()
    const generation = projectionGeneration
    const novelId = projectId.value
    const storageKey = taskStorageKey(novelId, pageId)
    const storedId = localStorage.getItem(storageKey)
    projectionTask.value = null
    if (!storedId) return
    try {
      const task = await api.tasks.get(storedId, novelId)
      if (generation !== projectionGeneration || !ownsPage(novelId, pageId)) return false
      const meta = task.meta || {}
      if (meta.novel_id === novelId && meta.page_id === pageId && meta.projection_type === PROJECTION_TYPE) {
        projectionTask.value = task
        if (!isTerminalTask(task)) startProjectionPolling(storedId, pageId)
      }
    } catch {
      if (generation === projectionGeneration && ownsPage(novelId, pageId)) localStorage.removeItem(storageKey)
    }
  }

  function stopProjectionPolling() {
    projectionGeneration += 1
    if (projectionPoller.value?.stop) projectionPoller.value.stop()
    projectionPoller.value = null
  }

  function startProjectionPolling(taskId, pageId) {
    const novelId = projectId.value
    if (!ownsPage(novelId, pageId)) return false
    stopProjectionPolling()
    const generation = projectionGeneration
    projectionPoller.value = pollTaskProgress({
      taskId,
      workflowType: "world_bible_projection_refresh",
      apiClient: {
        tasks: {
          get: (id) => api.tasks.get(id, novelId),
        },
      },
      intervalMs: 800,
      onUpdate: (_progress, task) => {
        if (generation !== projectionGeneration || !ownsPage(novelId, pageId)) return
        if (task) projectionTask.value = task
      },
      onDone: (_progress, task) => {
        if (generation !== projectionGeneration || !ownsPage(novelId, pageId)) return
        projectionPoller.value = null
        if (task) projectionTask.value = task
        toast("世界书投影刷新完成", "success")
      },
      onFailed: (progress, task) => {
        if (generation !== projectionGeneration || !ownsPage(novelId, pageId)) return
        projectionPoller.value = null
        if (task) projectionTask.value = task
        toast(`世界书投影刷新失败：${progress.errorMessage || "未知错误"}`, "error")
      },
    })
    localStorage.setItem(taskStorageKey(novelId, pageId), taskId)
  }

  function extractFinishedTaskId(err, apiErr) {
    const msg = `${err?.message || ""} ${apiErr?.response || ""}`
    const match = msg.match(/task_id:\s*([^；;\s]+)/)
    if (match?.[1]) return match[1].replace(/[",}]+$/, "")
    try {
      const parsed = JSON.parse(apiErr?.response || "{}")
      return parsed?.detail?.task_id || null
    } catch {
      return null
    }
  }

  async function retryProjectionTask() {
    const taskId = projectionTask.value?.task_id || projectionTask.value?.id
    const page = activePage.value
    if (!taskId || !page || projectionRetryPending.value || !projectionTask.value?.available_actions?.includes("retry")) return false
    const novelId = projectId.value
    const pageId = page.id
    projectionRetryPending.value = true
    try {
      const result = await api.tasks.retry(taskId, novelId)
      projectionRetryPending.value = false
      if (!ownsPage(novelId, pageId)) return false
      projectionTask.value = {
        ...projectionTask.value,
        ...result,
        task_id: taskId,
        status: result.status || "pending",
        error_message: null,
        available_actions: ["cancel"],
      }
      projectionConflictHint.value = null
      startProjectionPolling(taskId, pageId)
      toast("投影刷新任务已重新加入队列", "success")
      return true
    } catch (err) {
      projectionRetryPending.value = false
      if (ownsPage(novelId, pageId)) toast(err.message || "重试投影刷新失败", "error")
      return false
    }
  }

  // ---- synopsis ----
  async function confirmSynopsisRefresh(novelId) {
    return confirmAiReference({
      novel_id: novelId,
      action: "world.world_bible.synopsis.refresh",
      task: "刷新世界观简介",
      scope: "world",
      include_world_synopsis: false,
      include_pending_objects: false,
      budget_tokens: 12000,
    })
  }

  async function refreshSynopsis() {
    if (synopsis.value?.pinned) {
      toast('当前固定在历史版本；请先"取消固定并刷新"', "warning")
      return false
    }
    const novelId = projectId.value
    try {
      const confirmation = await confirmSynopsisRefresh(novelId)
      const task = await api.world.refreshBibleSynopsis(novelId, confirmation.id)
      if (!ownsProject(novelId)) return false
      synopsisTask.value = task
      synopsisTerminalTaskId.value = null
      toast(synopsisTask.value.existing ? "已有简介刷新任务在运行" : "简介刷新任务已提交", "success")
      startSynopsisPolling(synopsisTask.value.task_id)
    } catch (err) {
      if (ownsProject(novelId)) toast(err.message || "刷新世界观简介失败", "error")
      return false
    }
  }

  function stopSynopsisPolling() {
    synopsisGeneration += 1
    if (synopsisPoller.value?.stop) synopsisPoller.value.stop()
    synopsisPoller.value = null
  }

  function startSynopsisPolling(taskId) {
    if (!taskId) return
    const novelId = projectId.value
    if (!ownsProject(novelId)) return
    stopSynopsisPolling()
    const generation = synopsisGeneration
    synopsisPoller.value = pollTaskProgress({
      taskId,
      workflowType: "world_bible_synopsis_refresh",
      apiClient: {
        tasks: {
          get: (id) => api.tasks.get(id, novelId),
        },
      },
      intervalMs: 800,
      onUpdate: (_progress, task) => {
        if (generation !== synopsisGeneration || !ownsProject(novelId)) return
        if (task) synopsisTask.value = { ...task, task_id: task.id || task.task_id }
      },
      onDone: async () => {
        if (generation !== synopsisGeneration || !ownsProject(novelId)) return
        synopsisPoller.value = null
        synopsisTerminalTaskId.value = taskId
        synopsisTask.value = { task_id: taskId, status: "done" }
        const nextSynopsis = await api.world.getBibleSynopsis(novelId)
        if (generation !== synopsisGeneration || !ownsProject(novelId)) return
        synopsis.value = nextSynopsis
        toast("世界观简介已刷新", "success")
      },
      onFailed: async (progress) => {
        if (generation !== synopsisGeneration || !ownsProject(novelId)) return
        synopsisPoller.value = null
        synopsisTerminalTaskId.value = taskId
        synopsisTask.value = { task_id: taskId, status: "failed" }
        const nextSynopsis = await api.world.getBibleSynopsis(novelId)
        if (generation !== synopsisGeneration || !ownsProject(novelId)) return
        synopsis.value = nextSynopsis
        toast(`世界观简介刷新失败：${progress.errorMessage || "未知错误"}`, "error")
      },
    })
  }

  async function toggleSynopsisAuto() {
    const novelId = projectId.value
    const enabled = !synopsis.value?.auto_refresh_enabled
    try {
      const updated = await api.world.setBibleSynopsisAutoRefresh(novelId, enabled)
      if (!ownsProject(novelId)) return false
      synopsis.value = updated
      if (synopsis.value?.active_task_id) synopsisTerminalTaskId.value = null
      toast(synopsis.value.auto_refresh_enabled ? "已授权自动维护世界观简介" : "已关闭自动维护", "success")
    } catch (err) {
      if (ownsProject(novelId)) toast(err.message || "更新自动维护授权失败", "error")
      return false
    }
  }

  async function openSynopsisHistory() {
    const novelId = projectId.value
    const modalOwner = captureModalOwner()
    try {
      const data = await api.world.listBibleSynopsisRevisions(novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      const items = data.items || []
      const body = items.length ? items.map((item) => `
        <article class="world-bible-suggestion-item">
          <strong>第 ${esc(item.version_number)} 版</strong> · ${esc(taskStatusLabel(item.status))}
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

  async function restoreSynopsis(revisionId, novelId = projectId.value, ownerNode = null) {
    if (!ownsProject(novelId)) return false
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const restored = await api.world.restoreBibleSynopsisRevision(revisionId, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      synopsis.value = restored
      closeModal()
      toast("已恢复并固定旧版本；自动晋升暂停", "success")
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "恢复简介版本失败", "error")
      return false
    }
  }

  async function unpinSynopsis() {
    const novelId = projectId.value
    try {
      const confirmation = await confirmSynopsisRefresh(novelId)
      const unpinned = await api.world.unpinBibleSynopsis(novelId)
      if (!ownsProject(novelId)) return false
      synopsis.value = unpinned
      const task = await api.world.refreshBibleSynopsis(novelId, confirmation.id)
      if (!ownsProject(novelId)) return false
      synopsisTask.value = task
      synopsisTerminalTaskId.value = null
      startSynopsisPolling(synopsisTask.value.task_id)
      toast(synopsisTask.value.existing ? "已取消固定，刷新任务正在运行" : "已取消固定并提交刷新", "success")
    } catch (err) {
      if (ownsProject(novelId)) toast(err.message || "取消固定失败", "error")
      return false
    }
  }

  // ---- activation profile ----
  function activeActivationProfile() {
    return activationProfiles.value.find((p) => p.id === activeActivationProfileId.value) || null
  }

  async function dryRunActivationProfile() {
    const profile = activeActivationProfile()
    if (!profile) return
    const generation = ++activationGeneration
    const novelId = projectId.value
    const profileId = profile.id
    try {
      const trace = await api.context.previewActivationProfile({
        novel_id: novelId,
        profile_id: profileId,
        action: profile.applicable_actions_json?.[0] || "writing.generate",
        reveal_mode: "author_safe",
        task_text: document.getElementById("bible-activation-task")?.value || "",
        entity_ids: [],
        top_k: 64,
        depth: 2,
      })
      if (generation !== activationGeneration || !ownsProject(novelId) || activeActivationProfileId.value !== profileId) return false
      activationTrace.value = trace
    } catch (err) {
      if (generation === activationGeneration && ownsProject(novelId) && activeActivationProfileId.value === profileId) {
        toast(err.message || "Dry-run 失败", "error")
      }
      return false
    }
  }

  watch(activeActivationProfileId, () => {
    activationGeneration += 1
    activationTrace.value = null
  })

  // ---- open in generation center ----
  function openInGenerationCenter() {
    const page = activePage.value
    if (!page?.id) return false
    const proceed = () => {
      const query = new URLSearchParams({
        tab: "world",
        source_page_id: page.id,
        target: "world_bible_page",
      })
      router.navigate("generate", null, true, query)
      return true
    }
    if (!editorHasUnsavedChanges()) return proceed()
    showModalHtml(
      "保存后打开 AI 工具",
      `<p>当前页面有未保存修改。AI 工具只从服务器读取页面与工作稿，请先保存。</p>`,
      [
        { text: "取消", class: "btn-ghost", handler: closeModal },
        {
          text: "保存并继续",
          class: "btn-primary",
          handler: async () => {
            const owner = captureEditorOwner()
            const modalOwner = captureModalOwner()
            const saved = await savePage(false, modalOwner)
            if (!ownsModalOwner(modalOwner)) return true
            if (!saved) return ownsEditor(owner) ? false : true
            closeModal()
            return proceed()
          },
        },
      ],
    )
    return false
  }

  // ---- suggestions ----
  function adoptionLabels(suggestion) {
    const items = suggestion?.payload_json?.items || []
    const claims = new Map()
    for (const item of items) {
      if (item.kind !== "world_bible_page") continue
      for (const mapping of item.payload?.claim_mappings || []) claims.set(mapping.item_key, mapping.claim)
    }
    return new Map(items.map((item) => {
      const payload = item.payload || {}
      const label = claims.get(item.item_key)
        || payload.entity?.name
        || (item.kind === "world_bible_page" ? payload.title : "已导入的世界资料")
      return [item.item_key, label]
    }))
  }

  async function openAdoptionPackage(packageId, ownerNovelId = projectId.value) {
    const novelId = typeof ownerNovelId === "string" ? ownerNovelId : projectId.value
    if (!packageId || !ownsProject(novelId)) return false
    const modalOwner = captureModalOwner()
    try {
      const preview = await api.world.previewAdoptionPackage(packageId, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      const labels = adoptionLabels(preview.suggestion)
      const rows = preview.canon_diff || []
      const existing = rows.filter((item) => item.action === "existing_ref")
      const pending = rows.filter((item) => item.action !== "existing_ref")
      const list = (items, empty) => items.length
        ? `<ul>${items.map((item) => `<li>${esc(labels.get(item.item_key) || "已导入的世界资料")}</li>`).join("")}</ul>`
        : `<p class="muted">${empty}</p>`
      const warning = (preview.omissions || []).length
        ? `<div class="alert alert-warning">来源覆盖不完整，本次不能提交。</div>`
        : ""
      showModalHtml(
        "审阅世界设定吸取",
        `<div class="world-adoption-preview">
          ${warning}
          <section><h3>流水线已写入</h3><p>这些对象只建立引用，不会重复创建。</p>${list(existing, "无")}</section>
          <section><h3>本次确认将写入</h3><p>待处理对象、关系与完整世界书页将在同一事务中提交。</p>${list(pending, "无")}</section>
        </div>`,
        [
          { text: "稍后再说", class: "btn-ghost", handler: closeModal },
          {
            text: "确认吸取",
            class: "btn-primary",
            handler: async () => {
              try {
                const validation = api.world.getLatestWorldValidationRun
                    ? await api.world.getLatestWorldValidationRun(novelId, {
                      scope: "full",
                    })
                  : null
                const applyArgs = [packageId, novelId, preview.expected_preview_hash]
                if (validation?.id) applyArgs.push(validation.id)
                await api.world.applyAdoptionPackage(...applyArgs)
                closeModal()
                toast("设定已吸取到世界对象、关系和世界书", "success")
                router.refresh()
                return true
              } catch (err) {
                if (!ownsProject(novelId)) return true
                toast(err?.status === 409 ? "请先在“世界健康”完成全面校验，或关闭后重新预览已变化的来源" : err.message || "吸取失败", err?.status === 409 ? "warning" : "error")
                return false
              }
            },
          },
        ],
        { size: "large" },
      )
      return true
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载采纳预览失败", "error")
      return false
    }
  }

  async function openSuggestions(focusSuggestionId = "", ownerNovelId = projectId.value) {
    const novelId = typeof ownerNovelId === "string" ? ownerNovelId : projectId.value
    if (!ownsProject(novelId)) return false
    const modalOwner = captureModalOwner()
    try {
      const query = {
        novel_id: novelId,
        source_module: "world",
        review_group: "generation_center",
      }
      const [data, history] = await Promise.all([
        api.world.listSuggestions({ ...query, status: "pending" }),
        api.world.listSuggestions({ ...query, status: "rejected", limit: 200 }),
      ])
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      suggestions.value = (data.items || []).filter((item) => item.target_type === "world_bible_page_draft")
      suggestionHistory.value = (history.items || []).filter((item) => (
        item.target_type === "world_bible_page_draft"
        && (item.revision_link?.predecessor_suggestion_id || item.revision_link?.successor_suggestion_id)
      ))
      const focusId = typeof focusSuggestionId === "string" ? focusSuggestionId : ""
      const focused = focusId && suggestions.value.find((item) => item.id === focusId)
      if (focused) {
        suggestions.value = [focused, ...suggestions.value.filter((item) => item.id !== focusId)]
      } else if (focusId) {
        clearSuggestionContinuation(focusId)
        toast("这条建议已处理或不可用，已显示其他待处理建议。", "info")
      }
      suggestionBatchKey.value = suggestions.value[0] ? suggestionGroupKey(suggestions.value[0]) : null
      const body = renderSuggestionsModal()
      showModalHtml("创设建议", body, [], { size: "large" })
      bindSuggestionModal(novelId)
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载建议失败", "error")
      return false
    }
  }

  function renderSuggestionsModal() {
    if (!suggestions.value.length && !suggestionHistory.value.length) return `<div class="empty-state"><p>暂无待处理建议或修订历史</p></div>`
    const base = suggestionBatchBase()
    return `
      <div class="world-bible-suggestion-list">
        ${suggestions.value.length ? `<div class="world-bible-suggestion-header">
          <div class="world-bible-suggestion-meta" data-bible-batch-meta>
            批量范围：${esc(base.review_group)} · ${esc(base.target_type)} · ${esc(base.action_schema)}
          </div>
          <div class="world-bible-suggestion-actions">
            <button class="btn btn-sm btn-primary" data-action="bible-batch-confirm">批量采用</button>
            <button class="btn btn-sm" data-action="bible-batch-reject">批量忽略</button>
          </div>
        </div>` : `<div class="empty-state"><p>暂无待处理建议</p></div>`}
        ${suggestions.value.map((item) => `
          <div class="world-bible-suggestion-item">
            ${renderSuggestionSelector(item, base)}
            <div class="world-bible-suggestion-title">${esc(suggestionTitle(item))}</div>
            <div class="world-bible-suggestion-risk">风险：${esc(item.risk_level)} · ${esc(item.action_schema)}</div>
            ${renderSuggestionRevision(item)}
            ${renderSuggestionDecision(item)}
            ${renderSuggestionComparison(item)}
            ${renderSuggestionPreview(item)}
            <div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm btn-primary" data-bible-edit-suggestion="${esc(item.id)}">编辑并应用到工作稿</button>
              <button class="btn btn-sm" data-bible-reject-suggestion="${esc(item.id)}">忽略</button>
            </div>
          </div>
        `).join("")}
        ${suggestionHistory.value.length ? `<details class="world-bible-suggestion-history"><summary>修订历史（${suggestionHistory.value.length}）</summary>${suggestionHistory.value.map((item) => `<div class="world-bible-suggestion-item world-bible-suggestion-item--historical"><div class="world-bible-suggestion-title">${esc(suggestionTitle(item))}</div>${renderSuggestionRevision(item)}${renderSuggestionDecision(item)}${renderSuggestionComparison(item)}${renderSuggestionPreview(item)}</div>`).join("")}</details>` : ""}
      </div>
    `
  }

  function bindSuggestionModal(novelId) {
    const confirmButton = document.querySelector("[data-action='bible-batch-confirm']")
    const rejectButton = document.querySelector("[data-action='bible-batch-reject']")
    confirmButton?.addEventListener("click", () => decideSuggestionBatch(true, novelId, confirmButton))
    rejectButton?.addEventListener("click", () => decideSuggestionBatch(false, novelId, rejectButton))
    document.querySelectorAll("[data-bible-edit-suggestion]").forEach((node) => {
      node.addEventListener("click", () => {
        const item = suggestions.value.find((entry) => entry.id === node.getAttribute("data-bible-edit-suggestion"))
        if (item && ownsModalOwner(captureModalOwner(node))) editSuggestionIntoDraft(item, novelId)
      })
    })
    document.querySelectorAll("[data-bible-reject-suggestion]").forEach((node) => {
      node.addEventListener("click", () => decideSuggestion(node.getAttribute("data-bible-reject-suggestion"), false, novelId, node))
    })
    document.querySelectorAll("[data-bible-batch-suggestion]").forEach((node) => {
      node.addEventListener("change", () => {
        if (!node.checked) return
        const item = suggestions.value.find((entry) => entry.id === node.getAttribute("data-bible-batch-suggestion"))
        if (!item) return
        suggestionBatchKey.value = suggestionGroupKey(item)
        syncSuggestionBatchSelection()
      })
    })
  }

  function suggestionBatchBase() {
    const selected = suggestions.value.find((item) => suggestionGroupKey(item) === suggestionBatchKey.value)
    const first = selected || suggestions.value[0] || {}
    return { review_group: first.review_group || "", target_type: first.target_type || "", action_schema: first.action_schema || "" }
  }

  function suggestionGroupKey(item = {}) {
    return [item.review_group || "", item.target_type || "", item.action_schema || ""].join("::")
  }

  function isSuggestionCompatible(item, base) {
    return item.review_group === base.review_group && item.target_type === base.target_type && item.action_schema === base.action_schema
  }

  function renderSuggestionSelector(item, base) {
    const compatible = isSuggestionCompatible(item, base)
    return `<label class="world-bible-suggestion-selector"><input type="checkbox" data-bible-batch-suggestion="${esc(item.id)}" ${compatible ? "checked" : ""}><span data-bible-batch-label="${esc(item.id)}">${compatible ? "已纳入批量操作" : "选择此组进行批量操作"}</span></label>`
  }

  function syncSuggestionBatchSelection() {
    const base = suggestionBatchBase()
    const meta = document.querySelector("[data-bible-batch-meta]")
    if (meta) meta.textContent = `批量范围：${base.review_group} · ${base.target_type} · ${base.action_schema}`
    document.querySelectorAll("[data-bible-batch-suggestion]").forEach((node) => {
      const item = suggestions.value.find((entry) => entry.id === node.getAttribute("data-bible-batch-suggestion"))
      const compatible = item ? isSuggestionCompatible(item, base) : false
      node.checked = compatible
      const label = node.closest(".world-bible-suggestion-selector")?.querySelector("[data-bible-batch-label]")
      if (label) label.textContent = compatible ? "已纳入批量操作" : "选择此组进行批量操作"
    })
  }

  function suggestionTitle(item) {
    const payload = item.payload_json || {}
    return payload.page?.title || payload.name || targetTypeLabel(item.target_type)
  }

  function targetTypeLabel(targetType) {
    return { world_bible_page_draft: "世界书整页提案", core_entity_draft: "世界对象建议", profile_field: "档案字段" }[targetType] || targetType || "创设建议"
  }

  function renderSuggestionPreview(item) {
    const payload = item.payload_json || {}
    const excerpt = payload.page?.free_text || payload.summary || payload.public_info || ""
    const refs = Array.isArray(payload.source_refs) ? payload.source_refs : []
    return `<div class="world-bible-suggestion-preview">${esc(String(excerpt).slice(0, 320))}</div>${refs.length ? `<div class="world-bible-suggestion-refs">${refs.map((ref) => `<span class="badge">${esc(ref.title || ref.source_type || "来源")}</span>`).join("")}</div>` : ""}`
  }

  function renderSuggestionDecision(item) {
    const decision = authorDecisionPresentation(item?.decision_state)
    if (!decision) return `<div class="world-bible-empty-hint" data-state="missing-author-decision-summary">本次生成未保存决定摘要。</div>`
    return `<details class="world-bible-author-decisions" data-section="author-decision-summary"><summary>AI 本次理解${decision.needsReview ? " · 请核对" : ""}</summary><dl>${decision.rows.map((row) => `<dt>${esc(row.label)}</dt><dd><ul>${row.items.map((value) => `<li>${esc(value)}</li>`).join("")}</ul></dd>`).join("")}</dl><p>如果理解有偏差，请回到生成中心明确纠正后重新生成。</p></details>`
  }

  function renderSuggestionRevision(item) {
    const link = item?.revision_link
    if (!link) return ""
    if (link.predecessor_suggestion_id && link.successor_suggestion_id) return `<div class="world-bible-suggestion-revision">上一版 → 此历史版 → 后续版本</div>`
    if (link.successor_suggestion_id) return `<div class="world-bible-suggestion-revision">此版已由后续修订替代，不可再采用</div>`
    if (link.predecessor_suggestion_id) return `<div class="world-bible-suggestion-revision">上一版 → 当前修订版</div>`
    return ""
  }

  function renderSuggestionComparison(item) {
    const predecessorId = item?.revision_link?.predecessor_suggestion_id
    const predecessor = suggestionHistory.value.find((entry) => entry.id === predecessorId)
    if (!predecessor) return ""
    const before = predecessor.payload_json?.page || {}
    const after = item.payload_json?.page || {}
    const changes = [["标题", "title"], ["类别", "page_type"], ["页面概览", "free_text"]].flatMap(([label, key]) => {
      const oldValue = String(before[key] || "").slice(0, 180)
      const newValue = String(after[key] || "").slice(0, 180)
      return oldValue === newValue ? [] : [{ label, oldValue, newValue }]
    })
    return `<details class="world-bible-suggestion-comparison" open><summary>上一版 → 当前版 · 关键变化</summary>${changes.length ? `<dl>${changes.map((change) => `<dt>${esc(change.label)}</dt><dd><del>${esc(change.oldValue || "未填写")}</del><span aria-hidden="true"> → </span><ins>${esc(change.newValue || "未填写")}</ins></dd>`).join("")}</dl>` : `<p>关键字段没有变化，可继续核对完整提案。</p>`}</details>`
  }

  function editSuggestionIntoDraft(item, novelId = projectId.value) {
    if (!ownsProject(novelId)) return false
    rememberSuggestion(item?.id)
    const payload = item.payload_json || {}
    const page = payload.page || {}
    const body = `
      ${renderSuggestionDecision(item)}
      <div class="form-group"><label>标题</label><input class="form-input" id="bible-suggestion-title" value="${esc(page.title || "")}" /></div>
      <div class="form-group"><label>类别</label><select class="form-select" id="bible-suggestion-type">${categoryOptions(page.page_type || "custom").map((c) => `<option value="${esc(c.category_key)}">${esc(c.name)}</option>`).join("")}</select></div>
      <div class="form-group"><label>页面概览</label><textarea class="form-textarea" id="bible-suggestion-text" rows="8">${esc(page.free_text || "")}</textarea></div>
      <p class="world-bible-empty-hint">分区与关联资料会原样带入。应用只写入工作稿，之后仍可在页面编辑器中调整或丢弃。</p>
    `
    showModalHtml("编辑创设建议", body, [{ text: "应用到工作稿", class: "btn-primary", handler: () => applyEditedSuggestion(item, novelId) }], { size: "large" })
  }

  async function applyEditedSuggestion(item, novelId = projectId.value) {
    if (!ownsProject(novelId)) return true
    const modalOwner = captureModalOwner(document.getElementById("bible-suggestion-title"))
    const text = document.getElementById("bible-suggestion-text")?.value || ""
    try {
      const originalPage = item.payload_json?.page || {}
      const result = await api.generate.applyWorldPageDraft(item.id, {
        page: {
          ...originalPage,
          title: document.getElementById("bible-suggestion-title")?.value?.trim() || "",
          page_type: document.getElementById("bible-suggestion-type")?.value || "custom",
          free_text: text,
        },
      }, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return true
      closeModal()
      toast("建议已应用到工作稿；正式页面尚未变化", "success")
      const draft = result?.draft
      if (draft?.id) {
        rememberDraft(draft)
        savedDrafts.set(draft.id, draft)
        openDraft(draft.id)
      }
    } catch (err) {
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return true
      if (err?.status === 409) {
        toast("来源工作稿已变更，本次提案未覆盖新修改。请重新生成。", "warning")
      } else {
        toast(err.message || "应用建议失败", "error")
      }
      return false
    }
  }

  async function decideSuggestionBatch(accepted, novelId = projectId.value, ownerNode = null) {
    if (!ownsProject(novelId)) return false
    const modalOwner = captureModalOwner(ownerNode)
    const selected = Array.from(document.querySelectorAll("[data-bible-batch-suggestion]:checked"))
      .map((node) => node.getAttribute("data-bible-batch-suggestion"))
      .filter(Boolean)
    if (!selected.length) {
      toast("没有可批量处理的建议", "warning")
      return
    }
    const selectedItems = selected.map((id) => suggestions.value.find((item) => item.id === id)).filter(Boolean)
    const base = selectedItems[0] ? { review_group: selectedItems[0].review_group, target_type: selectedItems[0].target_type, action_schema: selectedItems[0].action_schema } : null
    if (!base || selectedItems.some((item) => !isSuggestionCompatible(item, base))) {
      toast("选中的建议类型不一致，请分别处理", "warning")
      return
    }
    if (accepted && selectedItems.some((item) => item.target_type === "world_bible_page_draft")) {
      toast("页面建议需要逐条编辑并应用到工作稿", "warning")
      return
    }
    let failed = 0
    for (const id of selected) {
      try {
        if (accepted) await api.world.confirmSuggestion(id, novelId)
        else await api.world.rejectSuggestion(id, novelId)
      } catch { failed++ }
    }
    if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
    toast(failed ? `批量处理完成，${failed} 条失败` : "批量处理完成", failed ? "warning" : "success")
    await openSuggestions("", novelId)
  }

  async function decideSuggestion(id, accepted, novelId = projectId.value, ownerNode = null) {
    if (!ownsProject(novelId)) return false
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const item = suggestions.value.find((entry) => entry.id === id)
      if (accepted && item?.target_type === "world_bible_page_draft") {
        editSuggestionIntoDraft(item, novelId)
        return
      }
      if (accepted) await api.world.confirmSuggestion(id, novelId)
      else await api.world.rejectSuggestion(id, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      clearSuggestionContinuation(id)
      toast(accepted ? "建议已采用" : "建议已忽略", "success")
      if (accepted) router.refresh()
      await openSuggestions("", novelId)
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "处理建议失败", "error")
      return false
    }
  }

  // ---- conflicts ----
  async function inspectCurrentPage() {
    if (semanticInspectionPending.value) {
      semanticInspectionController?.abort()
      semanticInspectionController = null
      semanticInspectionPending.value = false
      toast("已停止后续检修；远端请求可能正在结束", "warning")
      return
    }
    const page = activePage.value
    if (!page?.id) {
      toast("请先打开一个已保存的世界书页面", "warning")
      return
    }
    if (editorHasUnsavedChanges() && !(await savePage(false))) return

    const draft = (
      activeDraft.value?.page_id === page.id
        ? activeDraft.value
        : activeDraft.value?.page_id === page.id
          ? activeDraft.value
          : null
    )
    const requestProjectId = projectId.value
    const requestPageId = page.id
    const controller = new AbortController()
    semanticInspectionController = controller
    semanticInspectionPending.value = true
    try {
      const confirmation = await confirmAiReference({
        novel_id: requestProjectId,
        action: "world.generation.semantic_inspection",
        task: "检修当前世界书页面",
        scope: "full",
        pinned_refs: draft ? [] : [{ kind: "target", target_ref: { target_type: "world_bible_page", target_id: requestPageId, target_path: "" } }],
        selected_world_bible_draft_ids: draft ? [draft.id] : [],
        include_pending_objects: false,
        budget_tokens: 4000,
      })
      const result = await api.generate.inspectWorldPage({
        novel_id: requestProjectId,
        context_confirmation_id: confirmation.id,
        source_context: {
          kind: "world_bible_page",
          page_id: requestPageId,
          baseline: draft
            ? {
                kind: "draft",
                page_version: page.version_number,
                draft_id: draft.id,
                draft_updated_at: draft.updated_at,
              }
            : { kind: "published", page_version: page.version_number },
        },
        target: { kind: "world_bible_page", page_id: requestPageId },
        messages: [],
        quality_mode: "fast",
        include_world_synopsis: false,
      }, { signal: controller.signal })
      if (
        disposed
        || controller.signal.aborted
        || projectId.value !== requestProjectId
        || activePage.value?.id !== requestPageId
      ) return
      showSemanticInspection(result)
      toast("已完成本次当前页检修", "success")
    } catch (err) {
      if (disposed || controller.signal.aborted || err?.name === "AbortError") return
      if (err?.message === "已取消 AI 参考资料确认") return
      toast(err.message || "当前页检修失败", "error")
    } finally {
      if (!disposed && semanticInspectionController === controller) {
        semanticInspectionController = null
        semanticInspectionPending.value = false
      }
    }
  }

  function showSemanticInspection(result) {
    const actionLabel = {
      needs_decision: "需要你决定",
      can_improve: "可以改进",
    }
    const findings = Array.isArray(result?.findings) ? result.findings : []
    const receipt = result?.receipt || {}
    const body = `
      <div class="world-bible-suggestion-list">
        ${findings.length ? findings.map((item) => `
          <article class="world-bible-suggestion-item" data-author-action="${esc(item.author_action)}">
            <strong>${esc(actionLabel[item.author_action] || "请核对")} · ${esc(item.summary)}</strong>
            <p>证据：${esc(item.evidence)}</p>
            <p>位置：${esc(item.location)}</p>
            <p>下一步：${esc(item.next_step)}</p>
          </article>
        `).join("") : `<div class="empty-state"><p>本次窄检修没有发现需要决定或可以改进的项目；这不代表页面语义完整无误。</p></div>`}
        <details>
          <summary>本次检查范围</summary>
          <p>${esc(receipt.scope_label || "当前世界书页")} · 页面 v${esc(receipt.source_version || "-")}</p>
          <p>已运行：${esc((receipt.checks_run || []).join("、") || "无")}</p>
          <p>未运行：${esc((receipt.not_run || []).join("、") || "无")}</p>
          ${(receipt.omissions || []).map((item) => `<p>${esc(item)}</p>`).join("")}
        </details>
      </div>
    `
    showModalHtml("当前页检修", body, [{
      text: "查看当前检查项",
      handler: async () => {
        closeModal()
        await openConflicts()
      },
    }], { size: "large" })
  }

  async function resolveConflict(id, status, novelId = projectId.value, ownerNode = null) {
    if (!ownsProject(novelId)) return false
    const modalOwner = captureModalOwner(ownerNode)
    const item = conflicts.value.find((entry) => entry.id === id)
    if (!item) return false
    try {
      await api.world.resolveWorldConflict(id, {
        status,
        resolution_json: { ...(item.resolution_json || {}), resolved_by: "author" },
      }, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      toast(status === "resolved" ? "检查项已处理" : "检查项已忽略", "success")
      await openConflicts()
      return true
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "处理检查项失败", "error")
      return false
    }
  }

  async function openConflicts(focusId = "") {
    const novelId = projectId.value
    const modalOwner = captureModalOwner()
    try {
      const data = await api.world.listWorldConflicts({ novel_id: novelId, status: "pending" })
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      conflicts.value = data.items || []
      const body = conflicts.value.length
        ? conflicts.value.map((item) => {
            const action = item.resolution_json?.author_action
            const label = action === "needs_decision" ? "需要你决定" : action === "can_improve" ? "可以改进" : "检查项"
            const focused = focusId === item.id ? " is-focused" : ""
            return `<article class="world-bible-conflict-item${focused}" data-conflict-id="${esc(item.id)}" data-author-action="${esc(action || "unknown")}"><strong>${esc(label)} · ${esc(item.summary)}</strong>${item.resolution_json?.location ? `<p>位置：${esc(item.resolution_json.location)}</p>` : ""}${item.resolution_json?.next_step ? `<p>下一步：${esc(item.resolution_json.next_step)}</p>` : ""}<div class="world-bible-suggestion-item__actions"><button class="btn btn-sm btn-primary" data-bible-conflict-resolve="${esc(item.id)}">已处理</button><button class="btn btn-sm" data-bible-conflict-ignore="${esc(item.id)}">忽略</button></div></article>`
          }).join("")
        : `<div class="empty-state"><p>暂无冲突检查项</p></div>`
      showModalHtml("冲突检查", body, [])
      document.querySelectorAll("[data-bible-conflict-resolve]").forEach((button) => {
        button.addEventListener("click", () => resolveConflict(button.getAttribute("data-bible-conflict-resolve"), "resolved", novelId, button))
      })
      document.querySelectorAll("[data-bible-conflict-ignore]").forEach((button) => {
        button.addEventListener("click", () => resolveConflict(button.getAttribute("data-bible-conflict-ignore"), "ignored", novelId, button))
      })
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载冲突失败", "error")
      return false
    }
  }

  // ---- category manager ----
  function matchingCategory(draft) {
    const name = draft.name.trim().toLocaleLowerCase()
    return categories.value.find((category) => (
      (draft.presetKey && category.category_key === draft.presetKey)
      || (name && String(category.name || "").trim().toLocaleLowerCase() === name)
    )) || null
  }

  function categoryActionLabel(draft, forPage = false) {
    const existing = matchingCategory(draft)
    if (existing?.status === "archived") return "恢复并使用"
    if (existing) return "使用此分类"
    return forPage ? "创建并用于此页面" : "创建并使用此分类"
  }

  function readCategoryCreator(draft) {
    draft.name = document.getElementById("bible-category-name")?.value ?? draft.name
    draft.description = document.getElementById("bible-category-description")?.value ?? draft.description
    draft.color = (document.getElementById("bible-category-color")?.value || draft.color).toUpperCase()
    draft.icon = document.getElementById("bible-category-icon")?.value ?? draft.icon
    return draft
  }

  function updateCategoryCreatorAction(draft, pageState) {
    readCategoryCreator(draft)
    const action = document.querySelector("#modal-footer .btn-primary")
    if (action) action.textContent = categoryActionLabel(draft, Boolean(pageState))
    const existing = matchingCategory(draft)
    const hint = document.getElementById("bible-category-existing-hint")
    if (hint) hint.textContent = existing
      ? (existing.status === "archived" ? "已有同名的归档分类，将恢复后使用。" : "已有这个分类，将直接使用。")
      : ""
  }

  function showCategoryCreator(pageState = null) {
    const categoryDraft = pageState?.categoryDraft || {
      presetKey: "",
      name: "",
      description: "",
      color: "#64748B",
      icon: "",
    }
    if (pageState) pageState.categoryDraft = categoryDraft
    const body = `
      <p class="world-bible-empty-hint">选一个常用分类再调整，或者自己命名。</p>
      <div class="world-bible-category-preset-grid" role="group" aria-label="常用分类">
        ${BIBLE_CATEGORY_PRESETS.map((preset) => `
          <button type="button" class="world-bible-category-preset${categoryDraft.presetKey === preset.key ? " is-active" : ""}" data-bible-category-preset="${preset.key}" aria-pressed="${categoryDraft.presetKey === preset.key}" style="--world-bible-type-color:${preset.color}">
            <strong>${preset.name}</strong><span>${preset.description}</span>
          </button>
        `).join("")}
        <button type="button" class="world-bible-category-preset${categoryDraft.presetKey ? "" : " is-active"}" data-bible-category-preset="" aria-pressed="${!categoryDraft.presetKey}">
          <strong>自己命名</strong><span>为这个世界创建专属分类</span>
        </button>
      </div>
      <div class="form-group"><label for="bible-category-name">分类名称 *</label><input class="form-input" id="bible-category-name" value="${esc(categoryDraft.name)}" placeholder="例如：天文与历法" /></div>
      <div class="form-group"><label for="bible-category-description">用途说明</label><input class="form-input" id="bible-category-description" value="${esc(categoryDraft.description)}" placeholder="这类页面主要记录什么" /></div>
      <p id="bible-category-existing-hint" class="world-bible-category-existing-hint" role="status"></p>
      <details class="world-bible-category-appearance">
        <summary>外观设置（可选）</summary>
        <div class="world-bible-category-appearance__fields">
          <div><label for="bible-category-color">颜色</label><input id="bible-category-color" type="color" value="${esc(categoryDraft.color)}" /></div>
          <div><label for="bible-category-icon">卡片标记</label><input class="form-input" id="bible-category-icon" maxlength="16" value="${esc(categoryDraft.icon)}" placeholder="最多 16 个字" /></div>
        </div>
      </details>
    `
    showModalHtml(pageState ? "为页面新建分类" : "新建世界书分类", body, [
      { text: categoryActionLabel(categoryDraft, Boolean(pageState)), class: "btn-primary", handler: () => saveCategoryFromCreator(categoryDraft, pageState) },
      {
        text: "返回",
        class: "btn-ghost",
        handler: () => {
          readCategoryCreator(categoryDraft)
          if (pageState) {
            pageState.categoryKey = pageState.previousCategoryKey || "background"
            showCreatePageStep(pageState)
          } else {
            openCategoryManager()
          }
          return false
        },
      },
      { text: "取消", class: "btn-ghost", handler: closeModal },
    ], { size: "large" })

    document.querySelectorAll("[data-bible-category-preset]").forEach((button) => {
      button.addEventListener("click", () => {
        const presetKey = button.getAttribute("data-bible-category-preset") || ""
        const preset = BIBLE_CATEGORY_PRESETS.find((item) => item.key === presetKey)
        categoryDraft.presetKey = presetKey
        categoryDraft.name = preset?.name || ""
        categoryDraft.description = preset?.description || ""
        categoryDraft.color = preset?.color || "#64748B"
        categoryDraft.icon = preset?.icon || ""
        document.querySelectorAll("[data-bible-category-preset]").forEach((item) => {
          item.classList.toggle("is-active", item === button)
          item.setAttribute("aria-pressed", String(item === button))
        })
        const values = {
          "bible-category-name": categoryDraft.name,
          "bible-category-description": categoryDraft.description,
          "bible-category-color": categoryDraft.color,
          "bible-category-icon": categoryDraft.icon,
        }
        for (const [id, value] of Object.entries(values)) {
          const input = document.getElementById(id)
          if (input) input.value = value
        }
        updateCategoryCreatorAction(categoryDraft, pageState)
        document.getElementById("bible-category-name")?.focus()
      })
    })
    ;["bible-category-name", "bible-category-description", "bible-category-color", "bible-category-icon"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", () => updateCategoryCreatorAction(categoryDraft, pageState))
    })
    updateCategoryCreatorAction(categoryDraft, pageState)
  }

  async function saveCategoryFromCreator(draft, pageState) {
    readCategoryCreator(draft)
    draft.name = draft.name.trim()
    if (!draft.name) {
      toast("请填写分类名称", "warning")
      return false
    }
    const owner = captureEditorOwner()
    const modalOwner = captureModalOwner(document.getElementById("bible-category-name"))
    const existing = matchingCategory(draft)
    try {
      let category = existing
      if (existing?.status === "archived") {
        const restored = await api.world.updateBibleCategory(existing.id, { status: "active" }, owner.novelId)
        category = { ...existing, status: "active", ...restored }
      } else if (!existing) {
        const payload = {
          novel_id: owner.novelId,
          category_key: draft.presetKey || `custom_${globalThis.crypto.randomUUID().replaceAll("-", "")}`,
          name: draft.name,
          description: draft.description.trim() || null,
          color: draft.color || "#64748B",
          icon: draft.icon.trim() || draft.name.slice(0, 2),
          sort_order: 100,
        }
        const created = await api.world.createBibleCategory(payload)
        category = { ...payload, status: "active", builtin: false, ...created }
      }
      if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
      rememberCategory(category)
      toast(existing ? (existing.status === "archived" ? "分类已恢复" : "已使用现有分类") : "分类已创建", "success")
      if (pageState) {
        pageState.categoryKey = category.category_key
        pageState.previousCategoryKey = category.category_key
        showCreatePageStep(pageState)
      } else {
        openCategoryManager()
      }
      return true
    } catch (err) {
      if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
        toast(err.message || "创建分类失败", "error")
        return false
      }
      return true
    }
  }

  function openCategoryManager() {
    const custom = categories.value.filter((c) => !c.builtin)
    const body = `
      <div class="world-bible-category-manager-list">
        ${custom.length ? custom.map((item) => `
          <article class="world-bible-category-manager-card" style="--world-bible-type-color:${esc(item.color || "#64748B")}">
            <span class="world-bible-category-manager-card__marker">${esc(item.icon || String(item.name || "").slice(0, 2))}</span>
            <div class="world-bible-category-manager-card__body"><strong>${esc(item.name)}</strong><p>${esc(item.description || "暂无说明")}</p></div>
            <span class="badge">${item.status === "archived" ? "已归档" : "使用中"}</span>
            <div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm" data-bible-category-edit="${esc(item.id)}">编辑</button>
              ${item.status !== "archived"
                ? `<button class="btn btn-sm" data-bible-category-archive="${esc(item.id)}">归档</button>`
                : `<button class="btn btn-sm" data-bible-category-restore="${esc(item.id)}">恢复</button>`}
            </div>
          </article>
        `).join("") : `<div class="world-bible-empty-hint">还没有为这个世界创建专属分类。</div>`}
      </div>
    `
    showModalHtml("管理世界书分类", body, [
      { text: "新建分类", class: "btn-primary", handler: () => { showCategoryCreator(); return false } },
      { text: "关闭", class: "btn-ghost", handler: closeModal },
    ], { size: "large" })
    document.querySelectorAll("[data-bible-category-edit]").forEach((button) => {
      button.addEventListener("click", () => editCategory(button.getAttribute("data-bible-category-edit")))
    })
    document.querySelectorAll("[data-bible-category-archive]").forEach((button) => {
      button.addEventListener("click", () => archiveCategory(button.getAttribute("data-bible-category-archive")))
    })
    document.querySelectorAll("[data-bible-category-restore]").forEach((button) => {
      button.addEventListener("click", () => restoreCategory(button.getAttribute("data-bible-category-restore"), button))
    })
  }

  function editCategory(categoryId) {
    const item = categories.value.find((c) => c.id === categoryId)
    if (!item || item.builtin) return
    const body = `
      <div class="form-group"><label for="bible-category-edit-name">分类名称 *</label><input class="form-input" id="bible-category-edit-name" value="${esc(item.name)}" /></div>
      <div class="form-group"><label for="bible-category-edit-description">用途说明</label><input class="form-input" id="bible-category-edit-description" value="${esc(item.description || "")}" /></div>
      <details class="world-bible-category-appearance"><summary>外观设置（可选）</summary><div class="world-bible-category-appearance__fields">
        <div><label for="bible-category-edit-color">颜色</label><input id="bible-category-edit-color" type="color" value="${esc(item.color || "#64748B")}" /></div>
        <div><label for="bible-category-edit-icon">卡片标记</label><input class="form-input" id="bible-category-edit-icon" maxlength="16" value="${esc(item.icon || "")}" /></div>
      </div></details>
    `
    showModalHtml("编辑世界书分类", body, [{ text: "保存", class: "btn-primary", handler: () => saveCategory(categoryId) }])
  }

  async function saveCategory(categoryId) {
    const name = document.getElementById("bible-category-edit-name")?.value?.trim() || ""
    if (!name) { toast("分类名称不能为空", "warning"); return false }
    const owner = captureEditorOwner()
    const modalOwner = captureModalOwner(document.getElementById("bible-category-edit-name"))
    try {
      const updated = await api.world.updateBibleCategory(categoryId, {
        name,
        description: document.getElementById("bible-category-edit-description")?.value || null,
        color: document.getElementById("bible-category-edit-color")?.value || "#64748B",
        icon: document.getElementById("bible-category-edit-icon")?.value || "",
      }, owner.novelId)
      if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
      rememberCategory(updated, { ...categories.value.find((category) => category.id === categoryId), name })
      toast("分类已更新", "success")
      openCategoryManager()
      return true
    } catch (err) {
      if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
        toast(err.message || "更新类别失败", "error")
        return false
      }
      return true
    }
  }

  function archiveCategory(categoryId) {
    // vanilla 走 confirmAction 应用模态（worldBibleView.js:1876），非原生 confirm
    return confirmAction("归档该分类？现有页面不会删除，但不能再将工作稿切换到该分类。", async () => {
      const owner = captureEditorOwner()
      const modalOwner = captureModalOwner()
      try {
        const current = categories.value.find((category) => category.id === categoryId)
        const archived = await api.world.updateBibleCategory(categoryId, { status: "archived" }, owner.novelId)
        if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
        rememberCategory(archived, { ...current, status: "archived" })
        toast("分类已归档，现有页面已保留", "success")
        openCategoryManager()
        return true
      } catch (err) {
        if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
          toast(err.message || "归档类别失败", "error")
          return false
        }
        return true
      }
    })
  }

  async function restoreCategory(categoryId, ownerNode = null) {
    const novelId = projectId.value
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const current = categories.value.find((category) => category.id === categoryId)
      const restored = await api.world.updateBibleCategory(categoryId, { status: "active" }, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      rememberCategory(restored, { ...current, status: "active" })
      toast("分类已恢复，可重新用于工作稿", "success")
      openCategoryManager()
      return true
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "恢复类别失败", "error")
      return false
    }
  }

  // ---- page template manager ----
  function openPageTemplateManager() {
    const body = `
      <p class="world-bible-empty-hint">页面模板只定义分区布局和默认值，不保存 Prompt、provider、工具或脚本。</p>
      <div class="world-bible-suggestion-list">
        ${pageTemplates.value.map((item) => `
          <div class="world-bible-suggestion-item">
            <div><strong>${esc(item.name)}</strong> · ${esc(item.template_key)} · v${esc(item.version_number)} ${item.builtin ? "· 内置" : `· ${esc(item.status)}`}</div>
            ${item.builtin ? "" : `<div class="world-bible-suggestion-item__actions">
              <button class="btn btn-sm" data-page-template-rename="${esc(item.id)}">编辑</button>
              <button class="btn btn-sm" data-page-template-history="${esc(item.id)}">历史</button>
            </div>`}
          </div>
        `).join("")}
      </div>
      <hr />
      <div class="form-group"><label>模板 key</label><input class="form-input" id="bible-template-key" placeholder="trade_guide" /></div>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-template-name" placeholder="贸易资料页" /></div>
      <div class="form-group"><label>默认分区标题</label><input class="form-input" id="bible-template-section-title" placeholder="货币与交换" /></div>
    `
    showModalHtml("页面模板", body, [{ text: "创建自定义模板", class: "btn-primary", handler: () => createPageTemplateFromModal() }], { size: "large" })
    const custom = pageTemplates.value.filter((t) => !t.builtin)
    if (!custom.length) return
    document.querySelectorAll("[data-page-template-rename]").forEach((button) => {
      button.addEventListener("click", () => editPageTemplate(button.getAttribute("data-page-template-rename")))
    })
    document.querySelectorAll("[data-page-template-history]").forEach((button) => {
      button.addEventListener("click", () => openPageTemplateHistory(button.getAttribute("data-page-template-history"), button))
    })
  }

  async function createPageTemplateFromModal() {
    const key = document.getElementById("bible-template-key")?.value?.trim() || ""
    const name = document.getElementById("bible-template-name")?.value?.trim() || ""
    const title = document.getElementById("bible-template-section-title")?.value?.trim() || ""
    if (!key || !name || !title) {
      toast("请填写模板 key、名称和默认分区标题", "warning")
      return false
    }
    const owner = captureEditorOwner()
    const modalOwner = captureModalOwner(document.getElementById("bible-template-key"))
    try {
      const template = await api.world.createBiblePageTemplate({
        novel_id: owner.novelId,
        template_key: key,
        name,
        default_sections_json: [{
          section_id: `section_${Date.now().toString(36)}`,
          section_type: "markdown",
          title,
          body_markdown: "",
          sort_order: 10,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        }],
      })
      if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
      savedPageTemplates.set(template.id || template.template_key, template)
      closeModal()
      toast("页面模板已创建", "success")
    } catch (err) {
      if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
        toast(err.message || "创建模板失败", "error")
        return false
      }
      return true
    }
  }

  function editPageTemplate(templateId) {
    const template = pageTemplates.value.find((t) => t.id === templateId && !t.builtin)
    if (!template) return
    const body = `
      <p class="world-bible-empty-hint">稳定键 ${esc(template.template_key)} 不可修改。升级模板不会自动改写已发布页面。</p>
      <div class="form-group"><label>名称</label><input class="form-input" id="bible-template-edit-name" value="${esc(template.name)}" /></div>
      <div class="form-group"><label>说明</label><textarea class="form-textarea" id="bible-template-edit-description" rows="3">${esc(template.description || "")}</textarea></div>
      <label class="bible-ai-toggle"><input id="bible-template-edit-archived" type="checkbox" ${template.status === "archived" ? "checked" : ""} /> 归档模板</label>
    `
    showModalHtml("编辑页面模板", body, [{ text: "保存新版本", class: "btn-primary", handler: async () => {
      const owner = captureEditorOwner()
      const modalOwner = captureModalOwner(document.getElementById("bible-template-edit-name"))
      try {
        const updated = await api.world.updateBiblePageTemplate(template.id, {
          base_version_number: template.version_number,
          name: document.getElementById("bible-template-edit-name")?.value?.trim() || template.name,
          description: document.getElementById("bible-template-edit-description")?.value || null,
          status: document.getElementById("bible-template-edit-archived")?.checked ? "archived" : "active",
        }, owner.novelId)
        if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
        savedPageTemplates.set(updated.id || updated.template_key, updated)
        closeModal()
        toast("模板新版本已保存", "success")
      } catch (err) {
        if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
          toast(err.message || "更新模板失败", "error")
          return false
        }
        return true
      }
    }}])
  }

  async function openPageTemplateHistory(templateId, ownerNode = null) {
    const template = pageTemplates.value.find((t) => t.id === templateId)
    if (!template || template.builtin) return
    const novelId = projectId.value
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const revisions = await api.world.listBiblePageTemplateRevisions(template.id, novelId)
      if (!ownsProject(novelId) || !ownsModalOwner(modalOwner)) return false
      const body = revisions.map((item) => `
        <div class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(item.revision_reason)} · ${esc(item.content_hash.slice(0, 12))}
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
            savedPageTemplates.set(restored.id || restored.template_key, restored)
            closeModal()
            toast("历史模板已恢复为新版本", "success")
          } catch (err) {
            if (ownsProject(novelId) && ownsModalOwner(restoreOwner)) toast(err.message || "恢复模板失败", "error")
            return false
          }
        })
      })
    } catch (err) {
      if (ownsProject(novelId) && ownsModalOwner(modalOwner)) toast(err.message || "加载模板历史失败", "error")
      return false
    }
  }

  // ---- page history ----
  async function openPageHistory() {
    const page = activePage.value
    if (!page?.id) return
    const novelId = projectId.value
    const pageId = page.id
    const modalOwner = captureModalOwner()
    try {
      const revisions = await api.world.listBiblePageRevisions(pageId, novelId)
      if (!ownsPage(novelId, pageId) || !ownsModalOwner(modalOwner)) return false
      const body = Array.isArray(revisions) && revisions.length ? revisions.map((item) => `
        <article class="world-bible-suggestion-item">
          <strong>v${esc(item.version_number)}</strong> · ${esc(item.revision_reason)}
          <pre class="generate-markdown-pre">${esc(String(item.snapshot_json?.free_text || "").slice(0, 1200))}</pre>
          <button class="btn btn-sm" data-bible-page-restore="${esc(item.version_number)}">恢复为工作稿</button>
        </article>
      `).join("") : `<div class="empty-state"><p>暂无页面版本</p></div>`
      showModalHtml("世界书页面版本", body, [], { size: "large" })
      document.querySelectorAll("[data-bible-page-restore]").forEach((button) => {
        button.addEventListener("click", () => restorePageRevision(Number(button.getAttribute("data-bible-page-restore")), novelId, pageId, button))
      })
    } catch (err) {
      if (ownsPage(novelId, pageId) && ownsModalOwner(modalOwner)) toast(err.message || "加载页面历史失败", "error")
      return false
    }
  }

  async function restorePageRevision(version, novelId = projectId.value, pageId = activePage.value?.id, ownerNode = null) {
    if (!pageId || !version || !ownsPage(novelId, pageId)) return false
    const modalOwner = captureModalOwner(ownerNode)
    try {
      const draft = await api.world.restoreBiblePageRevision(pageId, version, novelId)
      if (!ownsPage(novelId, pageId) || !ownsModalOwner(modalOwner)) return false
      closeModal()
      savedDrafts.set(draft.id, draft)
      activeDraftId.value = draft.id
      setEditorBaseline(draft)
      syncSession()
      toast("旧版本已恢复为工作稿，再次发布后才会生效", "success")
      return true
    } catch (err) {
      if (ownsPage(novelId, pageId) && ownsModalOwner(modalOwner)) toast(err.message || "恢复页面版本失败", "error")
      return false
    }
  }

  async function archivePage() {
    const page = activePage.value
    if (!page?.id || draftForActivePage.value) return
    // vanilla 走 confirmAction 应用模态（worldBibleView.js:1640），非原生 confirm
    return confirmAction("归档此已发布页面？历史版本会保留，且页面将不再进入世界观简介。", async () => {
      const owner = captureEditorOwner()
      const modalOwner = captureModalOwner()
      try {
        const updated = await api.world.updateBiblePage(page.id, { status: "archived" }, owner.novelId)
        if (!ownsEditor(owner) || !ownsModalOwner(modalOwner)) return true
        activePageId.value = updated.id
        syncSession()
        toast("页面已归档", "success")
        router.refresh()
      } catch (err) {
        if (ownsEditor(owner) && ownsModalOwner(modalOwner)) {
          toast(err.message || "归档页面失败", "error")
          return false
        }
        return true
      }
    })
  }

  // ---- lifecycle ----
  function onBeforeUnmount() {
    disposed = true
    activationGeneration += 1
    semanticInspectionController?.abort()
    semanticInspectionController = null
    stopSynopsisPolling()
    stopProjectionPolling()
    if (beforeUnloadBound.value && typeof window !== "undefined") {
      window.removeEventListener("beforeunload", handleBeforeUnload)
      beforeUnloadBound.value = false
    }
    syncSession()
  }

  // ---- initialize ----
  // Initialize immediately (setup phase, not onMounted)
  initialize()

  return {
    // state
    displayMode,
    activeCategory,
    galleryCategory,
    activeActivationProfileId,
    activationTrace,
    activePage,
    activeDraft,
    editSource,
    isWorkingDraft,
    draftForActivePage,
    synopsis,
    synopsisTask,
    projectionTask,
    projectionConflictHint,
    projectionRetryPending,
    editorMutationPending,
    sectionsSignal,
    suggestions,
    conflicts,
    semanticInspectionPending,
    // computed helpers
    pages,
    categories,
    drafts,
    pageTemplates,
    activationProfiles,

    // operations
    initialize,
    onBeforeUnmount,
    setDisplayMode,
    setActiveCategory,
    openGalleryCategory,
    backToGalleryHome,
    openPageCard,
    openDraft,
    createPage,
    savePage,
    publishDraft,
    discardDraft,
    applySelectedPageTemplate,
    addSection,
    removeSection,
    moveSection,
    refreshProjection,
    retryProjectionTask,
    refreshSynopsis,
    toggleSynopsisAuto,
    openSynopsisHistory,
    restoreSynopsis,
    unpinSynopsis,
    activeActivationProfile,
    dryRunActivationProfile,
    openInGenerationCenter,
    openAdoptionPackage,
    openSuggestions,
    openConflicts,
    inspectCurrentPage,
    openCategoryManager,
    openPageTemplateManager,
    openPageHistory,
    archivePage,
    setExternalLeaveGuard,
    editorHasUnsavedChanges,

    // helpers
    typeMeta,
    categoryItems,
    pagesForCategory,
    statusLabel,
    taskStatusLabel,
    pageExcerpt,
    categoryOptions,
    formatAssetRefs,
    parseAssetRefs,
    ownsProject,
    captureModalOwner,
    ownsModalOwner,
    captureSectionsFromDom,
    readSectionsFromDom,
    rerenderSectionEditor: () => { sectionsSignal.value = Date.now() },
    readDraftFromDom,
    esc,
  }
}
