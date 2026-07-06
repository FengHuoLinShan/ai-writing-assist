import { bindWorkspaceClick, renderActionMenu, bindActionMenus } from "../shared/viewHelper.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"

const HEALTH_ORDER = [
  ["unreviewed", "未复核"],
  ["unassigned", "未关联章节"],
  ["missing_setup", "缺设定"],
  ["needs_organize", "待整理"],
]

const STATUS_OPTIONS = [
  ["draft", "草稿"],
  ["candidate", "候选"],
  ["canonical", "正史"],
  ["deprecated", "废弃"],
]

const SOURCE_OPTIONS = [
  ["manual", "手动"],
  ["deep_import", "深度导入"],
  ["ai_generated", "AI 生成"],
]

const BOUNDARY_STATUS_OPTIONS = [
  ["uncertain", "边界不确定"],
]

const PHASE_OPTIONS = [
  ["phase1a_fallback", "Phase 1A fallback"],
  ["phase1b_fusion", "Phase 1B fusion"],
]

const SCENE_FILTER_DEFAULTS = {
  status: "",
  source: "",
  workflow_id: "",
  needs_review: "",
  boundary_status: "",
  phase: "",
  phase1a_fallback: false,
  skip: 0,
  limit: 20,
}

const TAG_OPTIONS = [
  ["draft", "草稿"],
  ["hook", "钩子"],
  ["inciting_incident", "激励事件"],
  ["rising_action", "冲突升级"],
  ["climax", "阶段高潮"],
  ["valley", "低谷"],
  ["transition", "过渡"],
  ["payoff", "爽点"],
]

const sceneWorkbenchView = {
  _loading: true,
  _workbench: null,
  _total: 0,
  _activeHealth: null,
  _filters: { ...SCENE_FILTER_DEFAULTS },
  _advancedFiltersOpen: false,
  _selectedFusionSceneIds: new Set(),
  _autoExtractTaskId: null,
  _autoExtractProgress: null,
  _autoExtractPoller: null,
  _autoExtractMeta: null,
  _crossChapterTaskId: null,
  _crossChapterProgress: null,
  _crossChapterPoller: null,
  _activeDraftReview: null,
  _mobileDetailOpen: false,

  async onEnter() {
    this._loading = true
    this._workbench = null
    this._total = 0
    this._selectedFusionSceneIds = new Set()
    this._mobileDetailOpen = Boolean(state.currentSubView)
    if (!state.currentProjectId) {
      this._loading = false
      return
    }
    try {
      this._recoverCrossChapterWorkflow()
      await this._loadWorkbench()
    } catch (err) {
      toast(err.message || "场景工作台加载失败", "error")
      this._workbench = null
    } finally {
      this._loading = false
    }
  },

  onActivate() {
    this._bindEvents()
  },

  onLeave() {
    this._stopAutoExtractPolling()
    this._stopCrossChapterPolling()
  },

  async render() {
    if (this._loading) return '<div class="loading">加载中...</div>'
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先从左侧选择一个项目开始创作。</p></div>'
    }
    if (!this._workbench) {
      return '<div class="empty-state"><p>场景工作台暂不可用。</p></div>'
    }

    const selected = this._selectedSceneItem()
    const narrow = typeof window !== "undefined" && window.innerWidth < 720
    const showNarrowDetail = narrow && this._mobileDetailOpen && selected
    const detail = this._renderDetail(selected, narrow)
    const html = `
      <div style="margin-bottom:8px;display:flex;gap:8px;justify-content:flex-end;">
        <button class="btn" data-action="detect-cross-chapter-scenes">识别跨章 Scene</button>
        <button class="btn btn-primary" data-action="scene-auto-extract">场景（scene）自动提取</button>
      </div>
      ${this._renderAutoExtractProgress()}
      ${this._renderCrossChapterProgress()}
      <div class="scene-workbench ${narrow ? "is-narrow" : ""}">
        <section class="scene-workbench__organize">
          ${this._renderManagementFilters()}
          ${this._renderHealthFilters()}
          ${this._renderFusionToolbar()}
          ${this._renderSceneList()}
          ${this._renderPagination()}
        </section>
        ${narrow ? "" : `<aside class="scene-workbench__detail">${detail}</aside>`}
        ${showNarrowDetail ? `<div class="scene-workbench-drawer">${detail}</div>` : ""}
      </div>
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
  },

  async _loadWorkbench() {
    if (!state.currentProjectId) return
    this._workbench = await api.outline.getSceneWorkbench(
      state.currentProjectId,
      state.currentSubView || null,
      this._sceneWorkbenchParams(),
    )
    this._total = Number(this._workbench?.total ?? this._workbench?.items?.length ?? 0) || 0
  },

  _sceneWorkbenchParams() {
    const params = {
      skip: this._filters.skip,
      limit: this._filters.limit,
    }
    for (const key of ["status", "source", "workflow_id", "needs_review", "boundary_status", "phase"]) {
      const value = this._filters[key]
      if (value === "true") params[key] = true
      else if (value === "false") params[key] = false
      else if (value) params[key] = value
    }
    if (this._filters.phase1a_fallback) params.phase1a_fallback = true
    return params
  },

  _renderManagementFilters() {
    const advancedFilters = this._advancedFiltersOpen ? `
      ${this._filterSelect("scene-filter-boundary-status", "边界", this._filters.boundary_status, BOUNDARY_STATUS_OPTIONS, "全部边界")}
      ${this._filterSelect("scene-filter-phase", "阶段", this._filters.phase, PHASE_OPTIONS, "全部阶段")}
      <label class="scene-filter-checkbox">
        <input id="scene-filter-phase1a-fallback" type="checkbox" ${this._filters.phase1a_fallback ? "checked" : ""} />
        <span>Phase 1A fallback</span>
      </label>
    ` : ""
    return `
      <div class="scene-management-filters" aria-label="Scene 管理筛选">
        ${this._filterSelect("scene-filter-status", "状态", this._filters.status, STATUS_OPTIONS, "全部状态")}
        ${this._filterSelect("scene-filter-source", "来源", this._filters.source, SOURCE_OPTIONS, "全部来源")}
        <label class="scene-filter-field scene-filter-field--wide">
          <span>Workflow</span>
          <input class="form-input" id="scene-filter-workflow-id" value="${esc(this._filters.workflow_id)}" placeholder="workflow_id" />
        </label>
        ${this._filterSelect("scene-filter-needs-review", "复核", this._filters.needs_review, [["true", "需复核"], ["false", "无需复核"]], "全部复核")}
        <div class="scene-filter-actions">
          <button class="btn btn-sm" data-action="toggle-advanced-scene-filters">${this._advancedFiltersOpen ? "▾" : "▸"} 高级</button>
          <button class="btn btn-sm btn-primary" data-action="apply-scene-filters">应用</button>
          <button class="btn btn-sm" data-action="reset-scene-filters">重置</button>
        </div>
        ${advancedFilters}
      </div>
    `
  },

  _filterSelect(id, label, value, options, emptyLabel) {
    return `
      <label class="scene-filter-field">
        <span>${esc(label)}</span>
        <select class="form-select" id="${esc(id)}">
          <option value="">${esc(emptyLabel)}</option>
          ${options.map(([optionValue, optionLabel]) => `
            <option value="${esc(optionValue)}" ${optionValue === value ? "selected" : ""}>${esc(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    `
  },

  _renderHealthFilters() {
    return `
      <div class="scene-health-bar">
        ${HEALTH_ORDER.map(([key, fallback]) => {
          const item = this._workbench.health?.[key] || { label: fallback, count: 0 }
          const active = this._activeHealth === key ? "active" : ""
          return `
            <button class="scene-health-filter ${active}" data-action="filter-health" data-id="${esc(key)}">
              <span>${esc(item.label || fallback)}</span>
              <strong>${esc(item.count ?? 0)}</strong>
            </button>
          `
        }).join("")}
      </div>
    `
  },

  _renderSceneList() {
    const items = this._filteredItems()
    const selectedId = this._selectedSceneId()
    const rows = items.map((item) => this._renderSceneRow(item, selectedId)).join("")
    const unassigned = this._renderUnassignedChapters()
    if (!rows && !unassigned) {
      return '<div class="empty-state"><p>暂无需要整理的 Scene。</p></div>'
    }
    return `<div class="scene-workbench-list">${rows}${unassigned}</div>`
  },

  _renderPagination() {
    if (this._total <= this._filters.limit) return ""
    const currentPage = Math.floor(this._filters.skip / this._filters.limit) + 1
    const totalPages = Math.ceil(this._total / this._filters.limit)
    const prevDisabled = this._filters.skip <= 0 ? "disabled" : ""
    const nextDisabled = this._filters.skip + this._filters.limit >= this._total ? "disabled" : ""
    return `
      <div class="scene-workbench-pagination">
        <button class="btn btn-sm" data-action="prev-scene-page" ${prevDisabled}>上一页</button>
        <span>第 ${currentPage} / ${totalPages} 页，共 ${esc(this._total)} 条</span>
        <button class="btn btn-sm" data-action="next-scene-page" ${nextDisabled}>下一页</button>
      </div>
    `
  },

  _renderSceneRow(item, selectedId) {
    const scene = item.scene || {}
    const selected = selectedId === scene.id ? "is-selected" : ""
    const fusionSelected = this._selectedFusionSceneIds.has(scene.id)
    const reviewAction = this._renderReviewAction(item, "row")
    const health = (item.health || []).map((key) => {
      const label = this._healthLabel(key)
      return `<span class="scene-health-chip">${esc(label)}</span>`
    }).join("")
    return `
      <article class="scene-workbench-row ${selected}" data-id="${esc(scene.id)}">
        <label class="scene-fusion-select selection-checkbox" title="选择用于手动融合">
          <input
            type="checkbox"
            data-action="toggle-fusion-selection"
            data-id="${esc(scene.id)}"
            ${fusionSelected ? "checked" : ""}
          />
          <span>融合</span>
        </label>
        <button class="scene-workbench-row__main" data-action="select-workbench-scene" data-id="${esc(scene.id)}">
          <div class="scene-workbench-row__meta">
            <span>#${esc(scene.scene_index ?? "-")}</span>
            <span>${esc(this._statusLabel(scene.status))}</span>
            <span>${esc(this._sourceLabel(scene.source))}</span>
            <span>${esc(item.chapter_range || "未关联章节")}</span>
          </div>
          <div class="scene-workbench-row__title">${esc(scene.title || "未命名 Scene")}</div>
          <div class="scene-workbench-row__summary">${esc(item.summary || scene.goal || "暂无目标")}</div>
          <div class="scene-workbench-row__health">${health}</div>
        </button>
        <div class="scene-workbench-row__actions">
          ${reviewAction}
          <button class="btn btn-sm btn-primary" data-action="edit-workbench-scene" data-id="${esc(scene.id)}">编辑</button>
          ${renderActionMenu(`scene-actions-${esc(scene.id)}`, [
            { action: "organize-workbench-scene", label: "拆分/整理", data: { id: scene.id } },
            { action: "open-writing-scene", label: "打开写作", data: { id: scene.id } },
          ])}
        </div>
      </article>
    `
  },

  _renderFusionToolbar() {
    const count = this._selectedFusionSceneIds.size
    const disabled = count < 2 ? "disabled" : ""
    const hint = count < 2 ? `再选 ${2 - count} 个即可融合` : "已可开始融合"
    return `
      <div class="scene-fusion-toolbar" aria-label="Scene 手动融合">
        <div class="scene-fusion-toolbar__status">
          <strong>${esc(count)}</strong>
          <span>个 Scene 已选</span>
          <span class="scene-fusion-toolbar__hint">${esc(hint)}</span>
        </div>
        <button class="btn btn-sm" data-action="select-visible-fusion-scenes">全选当前列表</button>
        <button class="btn btn-sm" data-action="clear-fusion-selection" ${count === 0 ? "disabled" : ""} title="${count === 0 ? "当前没有选中的 Scene" : "清空当前选择"}">清空</button>
        <button class="btn btn-sm" data-action="start-selected-merge" ${disabled} title="${count < 2 ? hint : "机械合并：目标 Scene 吸收其他 Scene"}">
          机械合并
        </button>
        <button class="btn btn-sm btn-primary" data-action="start-ai-fusion-draft" ${disabled} title="${count < 2 ? hint : "为选中的 Scene 生成 AI 融合草稿"}">
          AI 融合草稿
        </button>
      </div>
    `
  },

  _renderUnassignedChapters() {
    const chapters = this._workbench.unassigned_chapters || []
    if (!chapters.length && this._activeHealth !== "unassigned") return ""
    if (this._activeHealth && this._activeHealth !== "unassigned") return ""
    return chapters.map((chapter) => `
      <article class="scene-workbench-row scene-workbench-row--unassigned">
        <div class="scene-workbench-row__main">
          <div class="scene-workbench-row__meta"><span>未归类章节</span></div>
          <div class="scene-workbench-row__title">第 ${esc(chapter)} 章</div>
          <div class="scene-workbench-row__summary">尚未分配到 Scene</div>
        </div>
        <div class="scene-workbench-row__actions">
          <button class="btn btn-sm" data-action="assign-unassigned-chapter" data-chapter="${esc(chapter)}">分配 Scene</button>
        </div>
      </article>
    `).join("")
  },

  _renderDetail(item, narrow) {
    if (!item?.scene) {
      return '<div class="scene-detail-empty">选择一个 Scene 查看详情。</div>'
    }
    const scene = item.scene
    const close = narrow
      ? '<button class="btn btn-sm" data-action="close-scene-detail">关闭</button>'
      : ""
    const reviewState = this._sceneReviewState(item)
    const reviewLabel = reviewState.reviewed
      ? `已复核 · ${this._formatReviewTime(reviewState.reviewedAt)}`
      : "未复核"
    return `
      <div class="scene-detail-panel">
        <div class="scene-detail-panel__head">
          <div>
            <div class="scene-detail-panel__eyebrow">Scene 详情</div>
            <h3>${esc(scene.title || "未命名 Scene")}</h3>
          </div>
          ${close}
        </div>
        <div class="scene-detail-grid">
          ${this._input("标题", "scene-detail-title", scene.title || "")}
          ${this._select("叙事标签", "scene-detail-tag", scene.narrative_tag || "draft", TAG_OPTIONS)}
          ${this._select("状态", "scene-detail-status", scene.status || "draft", STATUS_OPTIONS)}
          ${this._select("来源", "scene-detail-source", scene.source || "manual", SOURCE_OPTIONS)}
          ${this._textarea("目标", "scene-detail-goal", scene.goal || "")}
          ${this._textarea("核心冲突", "scene-detail-conflict", scene.core_conflict || "")}
          ${this._textarea("情感节奏", "scene-detail-emotion", scene.emotional_beat || "")}
          ${this._textarea("必须发生", "scene-detail-must", scene.must_happen || "")}
          ${this._textarea("禁止发生", "scene-detail-must-not", scene.must_not_happen || "")}
          ${this._input("POV", "scene-detail-pov", scene.pov_character_id || "")}
        </div>
        <section class="scene-detail-summary">
          <div><strong>章节映射</strong><span>${esc(item.chapter_range || "未关联章节")}</span></div>
          <div><strong>关联资产预览</strong><span>剧情线 / 伏笔 / 揭示 / 地图摘要将在整理预览中展示</span></div>
          <div><strong>来源与复核</strong><span>${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(reviewLabel)}</span></div>
        </section>
        <div class="scene-detail-actions">
          ${this._renderReviewAction(item, "detail")}
          <button class="btn btn-primary" data-action="save-scene-detail" data-id="${esc(scene.id)}">保存</button>
          <button class="btn" data-action="start-merge-scene" data-id="${esc(scene.id)}">合并</button>
          <button class="btn" data-action="start-split-scene" data-id="${esc(scene.id)}">拆分</button>
        </div>
      </div>
    `
  },

  _input(label, id, value) {
    return `
      <label class="scene-detail-field">
        <span>${esc(label)}</span>
        <input class="form-input" id="${esc(id)}" value="${esc(value)}" />
      </label>
    `
  },

  _textarea(label, id, value) {
    return `
      <label class="scene-detail-field scene-detail-field--wide">
        <span>${esc(label)}</span>
        <textarea class="form-textarea" id="${esc(id)}" rows="3">${esc(value)}</textarea>
      </label>
    `
  },

  _select(label, id, value, options) {
    return `
      <label class="scene-detail-field">
        <span>${esc(label)}</span>
        <select class="form-select" id="${esc(id)}">
          ${options.map(([optionValue, optionLabel]) => `
            <option value="${esc(optionValue)}" ${optionValue === value ? "selected" : ""}>${esc(optionLabel)}</option>
          `).join("")}
        </select>
      </label>
    `
  },

  _filteredItems() {
    const items = this._workbench?.items || []
    if (!this._activeHealth) return items
    return items.filter((item) => (item.health || []).includes(this._activeHealth))
  },

  _selectedSceneId() {
    return state.currentSubView || this._workbench?.selected_scene_id || this._workbench?.items?.[0]?.scene?.id || null
  },

  _selectedSceneItem() {
    const id = this._selectedSceneId()
    const items = this._filteredItems()
    return items.find((item) => item.scene?.id === id) || items[0] || null
  },

  _findScene(sceneId) {
    return (this._workbench?.items || []).find((item) => item.scene?.id === sceneId)?.scene || null
  },

  _findSceneItem(sceneId) {
    return (this._workbench?.items || []).find((item) => item.scene?.id === sceneId) || null
  },

  _sceneReviewState(item) {
    const meta = item?.scene?.structure_meta || {}
    const health = item?.health || []
    const reviewedAt = meta.reviewed_at || null
    return {
      reviewed: Boolean(reviewedAt),
      reviewedAt,
      needsReview: Boolean(meta.needs_review) || health.includes("unreviewed"),
    }
  },

  _renderReviewAction(item, placement) {
    const sceneId = item?.scene?.id
    if (!sceneId) return ""
    const state = this._sceneReviewState(item)
    const size = placement === "row" ? "btn-sm" : ""
    if (state.reviewed) {
      return `<button class="btn ${size} scene-review-action" data-action="mark-scene-unreviewed" data-id="${esc(sceneId)}">取消复核</button>`
    }
    const primary = state.needsReview ? "btn-primary" : ""
    return `<button class="btn ${size} ${primary} scene-review-action" data-action="mark-scene-reviewed" data-id="${esc(sceneId)}">复核通过</button>`
  },

  _formatReviewTime(value) {
    if (!value) return ""
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return String(value)
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  },

  _toggleFusionSelection(sceneId, selected) {
    if (!sceneId) return
    if (selected) this._selectedFusionSceneIds.add(sceneId)
    else this._selectedFusionSceneIds.delete(sceneId)
    this._syncFusionSelectionUi()
  },

  _selectVisibleFusionScenes() {
    for (const item of this._filteredItems()) {
      const id = item.scene?.id
      if (id) this._selectedFusionSceneIds.add(id)
    }
    this._syncFusionSelectionUi()
  },

  _clearFusionSelection() {
    this._selectedFusionSceneIds = new Set()
    this._syncFusionSelectionUi()
  },

  _syncFusionSelectionUi() {
    if (typeof document === "undefined") return
    const toolbar = document.querySelector(".scene-fusion-toolbar")
    if (toolbar) toolbar.outerHTML = this._renderFusionToolbar()
    document.querySelectorAll('input[data-action="toggle-fusion-selection"]').forEach((input) => {
      const id = input.getAttribute("data-id")
      input.checked = this._selectedFusionSceneIds.has(id)
    })
  },

  async _saveSceneDetails(sceneId) {
    const value = (id) => document.getElementById(id)?.value?.trim() || null
    await api.outline.updateScene(sceneId, state.currentProjectId, {
      title: value("scene-detail-title"),
      narrative_tag: value("scene-detail-tag") || "draft",
      status: value("scene-detail-status") || "draft",
      source: value("scene-detail-source") || "manual",
      goal: value("scene-detail-goal"),
      core_conflict: value("scene-detail-conflict"),
      emotional_beat: value("scene-detail-emotion"),
      must_happen: value("scene-detail-must"),
      must_not_happen: value("scene-detail-must-not"),
      pov_character_id: value("scene-detail-pov"),
    })
    toast("Scene 已保存", "success")
    await router.refresh()
  },

  async _markSceneReviewed(sceneId) {
    const item = this._findSceneItem(sceneId)
    const scene = item?.scene
    if (!scene) {
      toast("未找到目标 Scene", "error")
      return
    }
    const meta = {
      ...(scene.structure_meta || {}),
      needs_review: false,
      reviewed_at: new Date().toISOString(),
      reviewed_by: "manual",
      reviewed_from: "scene_workbench",
    }
    await api.outline.updateScene(sceneId, state.currentProjectId, { structure_meta: meta })
    toast("Scene 已标记为已复核", "success")
    await router.refresh()
  },

  async _markSceneUnreviewed(sceneId) {
    const item = this._findSceneItem(sceneId)
    const scene = item?.scene
    if (!scene) {
      toast("未找到目标 Scene", "error")
      return
    }
    const meta = { ...(scene.structure_meta || {}), needs_review: true }
    delete meta.reviewed_at
    delete meta.reviewed_by
    delete meta.reviewed_from
    await api.outline.updateScene(sceneId, state.currentProjectId, { structure_meta: meta })
    toast("Scene 已标记为需复核", "success")
    await router.refresh()
  },

  async _assignChapter(chapterIndex) {
    const sceneId = prompt("输入目标 Scene ID：")
    if (!sceneId) return
    const scene = this._findScene(sceneId)
    if (!scene) {
      toast("未找到目标 Scene", "error")
      return
    }
    const chapterIds = [...new Set([...(scene.chapter_ids || []), String(chapterIndex)])]
      .sort((a, b) => Number(a) - Number(b))
    await api.outline.updateSceneWorkbenchMapping(state.currentProjectId, sceneId, {
      chapter_ids: chapterIds,
      structure_meta: { needs_organize: false },
    })
    toast("章节已分配", "success")
    await router.refresh()
  },

  async _startMerge(targetSceneId) {
    const sourceId = prompt("输入要合并进来的 Scene ID：")
    if (!sourceId) return
    await this._previewAndMerge(targetSceneId, [sourceId])
  },

  async _previewAndMerge(targetSceneId, sourceSceneIds) {
    const request = {
      target_scene_id: targetSceneId,
      source_scene_ids: sourceSceneIds,
    }
    const preview = await api.outline.previewSceneMerge(state.currentProjectId, request)
    showModal("合并 Scene 影响预览", this._renderPreview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认合并",
        class: "btn-primary",
        handler: async () => {
          await api.outline.mergeScenes(state.currentProjectId, {
            ...request,
            confirmed: true,
          })
          toast("Scene 已合并", "success")
          closeModal()
          await router.refresh()
        },
      },
    ])
  },

  async _startManualFusion() {
    const sourceSceneIds = Array.from(this._selectedFusionSceneIds)
    if (sourceSceneIds.length < 2) {
      toast("请至少选择 2 个 Scene 再融合", "warning")
      return
    }
    this._showPrimaryScenePicker(sourceSceneIds)
  },

  async _startSelectedMerge() {
    const sourceSceneIds = Array.from(this._selectedFusionSceneIds)
    if (sourceSceneIds.length < 2) {
      toast("请至少选择 2 个 Scene 再合并", "warning")
      return
    }
    this._showMergeTargetPicker(sourceSceneIds)
  },

  _showMergeTargetPicker(sourceSceneIds) {
    const scenes = sourceSceneIds
      .map((id) => this._findScene(id))
      .filter(Boolean)
    if (scenes.length < 2) {
      toast("请至少选择 2 个 Scene 再合并", "warning")
      return
    }
    const cards = scenes.map((scene, index) => `
      <label class="scene-primary-card" style="display:block;margin-bottom:10px;border:1px solid var(--border);padding:10px;border-radius:6px;">
        <input type="radio" name="merge-target-scene-id" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
        <strong>${esc(scene.title || "未命名 Scene")}</strong>
        <div style="color:var(--text-dim);font-size:12px;">${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
        <p style="margin:6px 0 0;">${esc(scene.goal || scene.core_conflict || "暂无目标")}</p>
      </label>
    `).join("")
    showModal("选择目标 Scene", cards, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "预览机械合并",
        class: "btn-primary",
        handler: async () => {
          const targetSceneId = document.querySelector('input[name="merge-target-scene-id"]:checked')?.value
          if (!targetSceneId) {
            toast("请选择目标 Scene", "warning")
            return
          }
          const sourceIds = sourceSceneIds.filter((id) => id !== targetSceneId)
          closeModal()
          await this._previewAndMerge(targetSceneId, sourceIds)
        },
      },
    ])
  },

  _showPrimaryScenePicker(sourceSceneIds) {
    const scenes = sourceSceneIds
      .map((id) => this._findScene(id))
      .filter(Boolean)
    if (scenes.length < 2) {
      toast("请至少选择 2 个 Scene 再融合", "warning")
      return
    }
    const cards = scenes.map((scene, index) => {
      const meta = scene.structure_meta || {}
      const flags = [
        meta.needs_review ? "需复核" : "",
        meta.phase1a_fallback ? "fallback" : "",
        meta.boundary_status ? `边界:${meta.boundary_status}` : "",
        meta.confidence != null ? `置信度:${meta.confidence}` : "",
      ].filter(Boolean)
      return `
        <label class="scene-primary-card" style="display:block;margin-bottom:10px;border:1px solid var(--border);padding:10px;border-radius:6px;">
          <input type="radio" name="primary-scene-id" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
          <strong>${esc(scene.title || "未命名 Scene")}</strong>
          <div style="color:var(--text-dim);font-size:12px;">${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))} · ${esc(this._sceneChapterLabel(scene))}</div>
          <p style="margin:6px 0 0;">${esc(scene.goal || scene.core_conflict || "暂无目标")}</p>
          ${flags.length ? `<div style="margin-top:6px;color:var(--text-dim);font-size:12px;">${esc(flags.join(" · "))}</div>` : ""}
        </label>
      `
    }).join("")
    showModal("选择主 Scene", cards, [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "生成 AI 融合草稿",
        class: "btn-primary",
        handler: async () => {
          const primarySceneId = document.querySelector('input[name="primary-scene-id"]:checked')?.value
          if (!primarySceneId) {
            toast("请选择主 Scene", "warning")
            return
          }
          closeModal()
          await this._previewFusionWithPrimary(sourceSceneIds, primarySceneId)
        },
      },
    ])
  },

  async _previewFusionWithPrimary(sourceSceneIds, primarySceneId) {
    try {
      const preview = await api.outline.previewSceneFusion(state.currentProjectId, {
        source_scene_ids: sourceSceneIds,
        primary_scene_id: primarySceneId,
      })
      this._showFusionPreview(preview, sourceSceneIds)
    } catch (err) {
      toast(err.message || "Scene 融合预览失败", "error")
    }
  },

  _showFusionPreview(preview, fallbackSourceIds) {
    const sourceSceneIds = preview?.source_scene_ids?.length
      ? preview.source_scene_ids
      : fallbackSourceIds
    this._activeDraftReview = preview || null
    showModal("Scene AI 草稿审稿", this._renderDraftReview(preview), [
      {
        text: "保留原 Scene + 保存融合 Scene",
        class: "btn-primary",
        handler: () => this._saveFusionResult("keep_originals", sourceSceneIds),
      },
      {
        text: "保存融合 Scene，并废弃原 Scene",
        class: "btn-primary",
        handler: () => this._saveFusionResult("deprecate_originals", sourceSceneIds),
      },
      {
        text: "放弃融合结果",
        class: "btn-ghost",
        handler: () => this._saveFusionResult("discard", sourceSceneIds),
      },
      {
        text: "继续编辑融合结果后再保存",
        class: "btn-primary",
        handler: () => this._saveFusionResult("edit_then_save", sourceSceneIds),
      },
    ])
  },

  _renderDraftReview(preview) {
    const fused = preview?.draft_scene || preview?.fused_scene || preview?.preview_scene || {}
    const sourceIds = preview?.source_scene_ids || []
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    const conflicts = (preview?.conflicts || []).map((item) => `<li>${esc(item.message || item.field || "")}</li>`).join("")
    const refs = preview?.field_references || {}
    const row = (field, label, editorHtml) => {
      const fieldRefs = refs[field] || []
      const primaryRefs = fieldRefs.filter((item) => item.role === "primary")
      const otherRefs = fieldRefs.filter((item) => item.role !== "primary")
      const renderRef = (item) => `<div class="scene-draft-ref"><strong>${esc(item.title || item.scene_id)}</strong><p>${esc(this._formatDraftRefValue(item.value))}</p></div>`
      return `
        <div class="scene-draft-review-row">
          <div class="scene-draft-review-row__label">${esc(label)}</div>
          <div>${editorHtml}</div>
          <div>${primaryRefs.map(renderRef).join("") || '<span class="muted">无</span>'}</div>
          <div>${otherRefs.map(renderRef).join("") || '<span class="muted">无</span>'}</div>
        </div>
      `
    }
    return `
      <div class="scene-fusion-preview">
        <section class="scene-fusion-preview__meta">
          <div><strong>来源 Scene</strong><span>${esc(sourceIds.join(", "))}</span></div>
          ${preview?.primary_scene_id ? `<div><strong>主 Scene</strong><span>${esc(preview.primary_scene_id)}</span></div>` : ""}
          ${preview?.reason ? `<p>${esc(preview.reason)}</p>` : ""}
          ${warnings ? `<ul>${warnings}</ul>` : ""}
          ${conflicts ? `<ul>${conflicts}</ul>` : ""}
        </section>
        <div class="scene-draft-review-grid">
          <div class="scene-draft-review-head">字段</div>
          <div class="scene-draft-review-head">AI 草稿</div>
          <div class="scene-draft-review-head">主 Scene 原值</div>
          <div class="scene-draft-review-head">其他 Scene 原值</div>
          ${row("title", "标题", `<input class="form-input" id="scene-fusion-title" value="${esc(fused.title || "")}" />`)}
          ${row("goal", "目标", `<textarea class="form-textarea" id="scene-fusion-goal" rows="3">${esc(fused.goal || "")}</textarea>`)}
          ${row("core_conflict", "核心冲突", `<textarea class="form-textarea" id="scene-fusion-conflict" rows="3">${esc(fused.core_conflict || "")}</textarea>`)}
          ${row("emotional_beat", "情感节奏", `<textarea class="form-textarea" id="scene-fusion-emotion" rows="3">${esc(fused.emotional_beat || "")}</textarea>`)}
          ${row("must_happen", "必须发生", `<textarea class="form-textarea" id="scene-fusion-must" rows="3">${esc(fused.must_happen || "")}</textarea>`)}
          ${row("must_not_happen", "禁止发生", `<textarea class="form-textarea" id="scene-fusion-must-not" rows="3">${esc(fused.must_not_happen || "")}</textarea>`)}
          ${row("chapter_ids", "章节 IDs", `<input class="form-input" id="scene-fusion-chapters" value="${esc((fused.chapter_ids || []).join(", "))}" />`)}
        </div>
      </div>
    `
  },

  _formatDraftRefValue(value) {
    if (Array.isArray(value)) return value.map((item) => typeof item === "object" ? JSON.stringify(item) : String(item)).join("；")
    if (value && typeof value === "object") return JSON.stringify(value)
    return value == null ? "" : String(value)
  },

  _sceneChapterLabel(scene) {
    const chapterIds = scene?.chapter_ids || []
    if (!chapterIds.length) return "未关联章节"
    return chapterIds.map((id) => `第 ${String(id)} 章`).join(" / ")
  },

  _readFusionDraftFields() {
    const draft = this._activeDraftReview?.draft_scene || this._activeDraftReview?.fused_scene || {}
    const value = (id, fallback = null) => {
      const el = document.getElementById(id)
      if (!el) return fallback
      return el.value?.trim() || null
    }
    const chaptersText = value("scene-fusion-chapters", (draft.chapter_ids || []).join(", ")) || ""
    const chapters = chaptersText
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
    return {
      title: value("scene-fusion-title", draft.title || null),
      goal: value("scene-fusion-goal", draft.goal || null),
      core_conflict: value("scene-fusion-conflict", draft.core_conflict || null),
      emotional_beat: value("scene-fusion-emotion", draft.emotional_beat || null),
      must_happen: value("scene-fusion-must", draft.must_happen || null),
      must_not_happen: value("scene-fusion-must-not", draft.must_not_happen || null),
      chapter_ids: chapters,
      structure_meta: {
        draft_review_mode: this._activeDraftReview?.mode || "fusion",
        primary_scene_id: this._activeDraftReview?.primary_scene_id || null,
        confidence: this._activeDraftReview?.confidence ?? null,
        draft_review_warnings: this._activeDraftReview?.warnings || [],
        draft_review_conflicts: this._activeDraftReview?.conflicts || [],
      },
    }
  },

  async _saveFusionResult(mode, sourceSceneIds) {
    const payload = {
      source_scene_ids: sourceSceneIds,
      primary_scene_id: this._activeDraftReview?.primary_scene_id || null,
      mode,
    }
    if (mode !== "discard") {
      payload.fused_scene = this._readFusionDraftFields()
    }
    try {
      const result = await api.outline.saveSceneFusion(state.currentProjectId, payload)
      this._selectedFusionSceneIds = new Set()
      toast(result?.status === "discarded" ? "融合结果已放弃" : "融合 Scene 已保存", "success")
      closeModal()
      await router.refresh()
    } catch (err) {
      toast(err.message || "Scene 融合保存失败", "error")
    }
  },

  async _startSplit(sourceSceneId) {
    const raw = prompt("输入拆分起始章节：")
    const chapter = parseInt(raw || "", 10)
    if (!Number.isFinite(chapter)) return
    await this._previewAndSplit(sourceSceneId, chapter)
  },

  async _previewAndSplit(sourceSceneId, splitChapterIndex) {
    const request = {
      source_scene_id: sourceSceneId,
      split_chapter_index: splitChapterIndex,
    }
    const preview = await api.outline.previewSceneSplit(state.currentProjectId, request)
    showModal("Scene AI 草稿审稿", this._renderSplitDraftReview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认拆分",
        class: "btn-primary",
        handler: async () => {
          await api.outline.splitScene(state.currentProjectId, {
            ...request,
            draft_scenes: this._readSplitDraftScenes(),
            confirmed: true,
          })
          toast("Scene 已拆分", "success")
          closeModal()
          await router.refresh()
        },
      },
    ])
  },

  _renderSplitDraftReview(preview) {
    const drafts = preview?.draft_scenes || []
    const sourceRefs = preview?.field_references || {}
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    const fields = [
      ["title", "标题"],
      ["goal", "目标"],
      ["core_conflict", "核心冲突"],
      ["emotional_beat", "情感节奏"],
      ["must_happen", "必须发生"],
      ["must_not_happen", "禁止发生"],
      ["chapter_ids", "章节 IDs"],
    ]
    const refValue = (field) => (sourceRefs[field] || [])
      .map((item) => `${item.title || item.scene_id}: ${this._formatDraftRefValue(item.value)}`)
      .join("；") || "无"
    const splitEditor = (draftIndex, field, value) => {
      const id = `scene-split-${draftIndex}-${field}`
      if (field === "chapter_ids") {
        return `<input class="form-input" id="${esc(id)}" value="${esc(this._formatDraftRefValue(value))}" readonly />`
      }
      return `<textarea class="form-textarea" id="${esc(id)}" rows="2">${esc(value || "")}</textarea>`
    }
    const rows = fields.map(([field, label]) => `
      <div class="scene-draft-review-row">
        <div class="scene-draft-review-row__label">${esc(label)}</div>
        <div>${esc(refValue(field))}</div>
        <div>${splitEditor(0, field, drafts[0]?.[field])}</div>
        <div>${splitEditor(1, field, drafts[1]?.[field])}</div>
      </div>
    `).join("")
    return `
      <div class="scene-fusion-preview">
        <section class="scene-fusion-preview__meta">
          <div><strong>操作</strong><span>AI 拆分草稿</span></div>
          ${warnings ? `<ul>${warnings}</ul>` : ""}
        </section>
        <div class="scene-draft-review-grid">
          <div class="scene-draft-review-head">字段</div>
          <div class="scene-draft-review-head">原 Scene</div>
          <div class="scene-draft-review-head">草稿 A</div>
          <div class="scene-draft-review-head">草稿 B</div>
          ${rows}
        </div>
        ${this._renderPreview(preview)}
      </div>
    `
  },

  _readSplitDraftScenes() {
    const fields = ["title", "goal", "core_conflict", "emotional_beat", "must_happen", "must_not_happen", "narrative_tag"]
    return [0, 1].map((index) => {
      const draft = {}
      for (const field of fields) {
        const value = document.getElementById(`scene-split-${index}-${field}`)?.value?.trim()
        if (value) draft[field] = value
      }
      return draft
    })
  },

  _renderPreview(preview) {
    const mapping = preview?.chapter_mapping_change || {}
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    return `
      <div class="scene-impact-preview">
        <div><strong>操作</strong><span>${esc(preview?.operation || "")}</span></div>
        <div><strong>章节映射变化</strong><pre>${esc(JSON.stringify(mapping, null, 2))}</pre></div>
        <div><strong>字段变化</strong><pre>${esc(JSON.stringify(preview?.field_changes || {}, null, 2))}</pre></div>
        <div><strong>关联剧情线</strong><span>${esc(preview?.related_threads?.count ?? 0)} 条</span></div>
        <div><strong>关联伏笔 / 揭示</strong><span>${esc(preview?.related_foreshadowing?.count ?? 0)} / ${esc(preview?.related_reveals?.count ?? 0)}</span></div>
        <div><strong>地图摘要影响</strong><span>${esc(preview?.map_summary_impact?.message || "无")}</span></div>
        ${warnings ? `<ul>${warnings}</ul>` : ""}
      </div>
    `
  },

  _openWritingForScene(scene) {
    const first = (scene.chapter_ids || []).find((id) => String(id).match(/^\d+$/))
    if (first) {
      state.viewStates = state.viewStates || {}
      state.viewStates.writing = {
        ...(state.viewStates.writing || {}),
        currentChapter: parseInt(first, 10),
      }
    }
    router.navigate("writing", null)
  },

  _healthLabel(key) {
    return this._workbench?.health?.[key]?.label || HEALTH_ORDER.find(([k]) => k === key)?.[1] || key
  },

  _statusLabel(status) {
    return Object.fromEntries(STATUS_OPTIONS)[status] || status || "草稿"
  },

  _sourceLabel(source) {
    return Object.fromEntries(SOURCE_OPTIONS)[source] || source || "手动"
  },

  async _applyManagementFilters() {
    const read = (id) => document.getElementById(id)?.value?.trim() || ""
    this._filters = {
      ...SCENE_FILTER_DEFAULTS,
      status: read("scene-filter-status"),
      source: read("scene-filter-source"),
      workflow_id: read("scene-filter-workflow-id"),
      needs_review: read("scene-filter-needs-review"),
      boundary_status: read("scene-filter-boundary-status"),
      phase: read("scene-filter-phase"),
      phase1a_fallback: Boolean(document.getElementById("scene-filter-phase1a-fallback")?.checked),
      skip: 0,
    }
    await this._loadWorkbench()
    await router.refresh()
  },

  async _resetManagementFilters() {
    this._filters = { ...SCENE_FILTER_DEFAULTS }
    this._advancedFiltersOpen = false
    await this._loadWorkbench()
    await router.refresh()
  },

  _toggleAdvancedFilters() {
    this._advancedFiltersOpen = !this._advancedFiltersOpen
    router.refresh()
  },

  async _changePage(delta) {
    const newSkip = this._filters.skip + delta * this._filters.limit
    if (newSkip < 0) return
    if (newSkip >= this._total) return
    this._filters.skip = newSkip
    this._selectedFusionSceneIds = new Set()
    await this._loadWorkbench()
    await router.refresh()
  },

  _renderAutoExtractProgress() {
    if (!this._autoExtractProgress) return ""
    const rangeText = this._autoExtractMeta
      ? `范围: 章节 ${this._autoExtractMeta.start_chapter || 1}-${this._autoExtractMeta.end_chapter || 10}`
      : "范围: 所选章节"
    return `<div style="margin-bottom:8px;">${renderWorkflowCard(this._autoExtractProgress, {
      title: "场景（scene）自动提取",
      destinationLabel: rangeText,
    })}</div>`
  },

  _renderCrossChapterProgress() {
    if (!this._crossChapterProgress) return ""
    const result = this._crossChapterProgress.raw?.result || {}
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
    const suggestionHtml = this._crossChapterProgress.done && suggestions.length ? `
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center;">
        <span style="color:var(--text-dim);font-size:12px;">${esc(suggestions.length)} 条建议可查看</span>
        <button class="btn btn-sm btn-primary" data-action="show-cross-chapter-suggestions">查看建议</button>
      </div>
    ` : ""
    return `<div style="margin-bottom:8px;">${renderWorkflowCard(this._crossChapterProgress, {
      title: "跨章 Scene 识别",
      destinationLabel: "完成后可选择建议并保存融合 Scene",
    })}${suggestionHtml}</div>`
  },

  _stopAutoExtractPolling() {
    if (this._autoExtractPoller?.stop) this._autoExtractPoller.stop()
    this._autoExtractPoller = null
  },

  _stopCrossChapterPolling() {
    if (this._crossChapterPoller?.stop) this._crossChapterPoller.stop()
    this._crossChapterPoller = null
  },

  _startAutoExtractPolling(taskId) {
    this._stopAutoExtractPolling()
    this._autoExtractPoller = pollTaskProgress({
      taskId,
      workflowType: "scene_auto_extraction",
      apiClient: api,
      onUpdate: (progress) => {
        this._autoExtractProgress = progress
        router.renderCurrentView()
      },
      onDone: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._autoExtractTaskId = null
        toast("场景（scene）自动提取完成", "success")
        await this._loadWorkbench()
        router.refresh()
      },
      onFailed: async (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._autoExtractTaskId = null
        toast(`场景（scene）自动提取失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  _showSceneAutoExtractForm() {
    const formHtml = `
      <div class="form-group">
        <label>起始章节</label>
        <input class="form-input" id="scene-auto-extract-start" type="number" min="1" value="1" />
      </div>
      <div class="form-group">
        <label>结束章节</label>
        <input class="form-input" id="scene-auto-extract-end" type="number" min="1" value="10" />
      </div>
      <label style="display:flex;gap:8px;align-items:center;font-size:12px;color:var(--text-body);margin-top:8px;">
        <input id="scene-auto-extract-high-quality" type="checkbox" />
        更高质量 <span style="color:var(--text-dim);">需要标准提取约8倍时间</span>
      </label>
    `
    showModal("场景（scene）自动提取", formHtml, [{
      text: "开始提取",
      class: "btn-primary",
      handler: async () => {
        const start = parseInt(document.getElementById("scene-auto-extract-start")?.value || "1", 10)
        const end = parseInt(document.getElementById("scene-auto-extract-end")?.value || "10", 10)
        const highQuality = !!document.getElementById("scene-auto-extract-high-quality")?.checked
        if (end < start) { toast("结束章节必须 ≥ 起始章节", "warning"); return }
        try {
          const result = await api.imports.startStage(
            "scenes",
            state.currentProjectId,
            start,
            end,
            false,
            highQuality,
          )
          this._autoExtractTaskId = result.task_id
          this._autoExtractMeta = { start_chapter: start, end_chapter: end }
          this._autoExtractProgress = normalizeTaskProgress({
            ...result,
            task_type: "scene_auto_extraction",
            meta: this._autoExtractMeta,
          }, "scene_auto_extraction")
          persistActiveWorkflow({
            taskId: result.task_id,
            workflowType: "scene_auto_extraction",
            label: "场景（scene）自动提取",
            projectId: state.currentProjectId,
            view: "scene",
            meta: { ...this._autoExtractMeta, highQuality },
          })
          closeModal()
          toast(`场景（scene）自动提取任务已提交：${result.task_id || ""}`, "success")
          this._startAutoExtractPolling(result.task_id)
          router.renderCurrentView()
        } catch (err) {
          toast(err.message || "提交失败", "error")
        }
      },
    }])
  },

  async _startCrossChapterDetection() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const result = await api.outline.detectCrossChapterScenes({
        novel_id: state.currentProjectId,
      })
      this._crossChapterTaskId = result.task_id
      this._crossChapterProgress = normalizeTaskProgress({
        ...result,
        task_type: "scene_cross_chapter_detection",
      }, "scene_cross_chapter_detection")
      persistActiveWorkflow({
        taskId: result.task_id,
        workflowType: "scene_cross_chapter_detection",
        label: "跨章 Scene 识别",
        projectId: state.currentProjectId,
        view: "scene",
      })
      toast("跨章 Scene 识别任务已提交", "success")
      this._startCrossChapterPolling(result.task_id)
      router.renderCurrentView()
    } catch (err) {
      toast(err.message || "提交失败", "error")
    }
  },

  _startCrossChapterPolling(taskId) {
    this._stopCrossChapterPolling()
    this._crossChapterPoller = pollTaskProgress({
      taskId,
      workflowType: "scene_cross_chapter_detection",
      apiClient: api,
      onUpdate: (progress) => {
        this._crossChapterProgress = progress
        router.renderCurrentView()
      },
      onDone: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._crossChapterTaskId = null
        this._crossChapterProgress = progress
        toast("跨章 Scene 识别完成", "success")
        router.renderCurrentView()
      },
      onFailed: (progress) => {
        clearActiveWorkflow(progress.taskId || taskId)
        this._crossChapterTaskId = null
        this._crossChapterProgress = progress
        toast(`跨章 Scene 识别失败: ${progress.errorMessage || "未知错误"}`, "error")
        router.renderCurrentView()
      },
    })
  },

  _recoverCrossChapterWorkflow() {
    const workflow = recoverActiveWorkflows(state.currentProjectId)
      .find((item) => item.workflowType === "scene_cross_chapter_detection")
    if (!workflow?.taskId) return
    this._crossChapterTaskId = workflow.taskId
    this._crossChapterProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: "scene_cross_chapter_detection",
      status: "running",
      meta: workflow.meta || {},
    }, "scene_cross_chapter_detection")
    this._startCrossChapterPolling(workflow.taskId)
  },

  _showCrossChapterSuggestions() {
    const result = this._crossChapterProgress?.raw?.result || {}
    const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
    if (!suggestions.length) {
      toast("暂无跨章 Scene 建议", "info")
      return
    }
    const rows = suggestions.map((item, index) => {
      const span = Array.isArray(item.chapter_span) ? item.chapter_span.join("-") : "-"
      const trace = (item.scan_trace || []).map((step) => `${step.action}: ${step.reason || ""}`).join(" / ")
      return `
        <label class="scene-fusion-suggestion" style="display:block;margin-bottom:12px;border:1px solid var(--border);padding:8px;border-radius:6px;">
          <input type="radio" name="cross-chapter-suggestion" value="${esc(index)}" ${index === 0 ? "checked" : ""} />
          <strong>${esc(item.proposed_scene?.title || "跨章融合建议")}</strong>
          <div style="color:var(--text-dim);font-size:12px;">章节 ${esc(span)} · 置信度 ${esc(item.confidence ?? "-")} · ${esc(item.stop_reason || "")}</div>
          <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
          <details style="margin-top:6px;"><summary>扫描轨迹</summary><p>${esc(trace || "无")}</p></details>
        </label>
      `
    }).join("")
    showModal("跨章 Scene 建议", rows, [{
      text: "打开 AI 融合草稿",
      class: "btn-primary",
      handler: async () => {
        const selected = document.querySelector('input[name="cross-chapter-suggestion"]:checked')?.value
        const suggestion = suggestions[Number(selected || 0)]
        if (!suggestion) return
        closeModal()
        const sourceSceneIds = suggestion.source_scene_ids || []
        this._showPrimaryScenePicker(sourceSceneIds)
      },
    }])
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "scene-auto-extract": () => this._showSceneAutoExtractForm(),
      "detect-cross-chapter-scenes": () => this._startCrossChapterDetection(),
      "show-cross-chapter-suggestions": () => this._showCrossChapterSuggestions(),
      "filter-health": (_e, _t, ctx) => {
        this._activeHealth = this._activeHealth === ctx.id ? null : ctx.id
        router.renderCurrentView()
      },
      "apply-scene-filters": () => this._applyManagementFilters(),
      "reset-scene-filters": () => this._resetManagementFilters(),
      "toggle-advanced-scene-filters": () => this._toggleAdvancedFilters(),
      "prev-scene-page": () => this._changePage(-1),
      "next-scene-page": () => this._changePage(1),
      "select-workbench-scene": (_e, _t, ctx) => {
        if (!ctx.id) return
        this._mobileDetailOpen = true
        router.navigate("scene", ctx.id)
      },
      "edit-workbench-scene": (_e, _t, ctx) => {
        if (!ctx.id) return
        this._mobileDetailOpen = true
        router.navigate("scene", ctx.id)
      },
      "organize-workbench-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "open-writing-scene": (_e, _t, ctx) => {
        const scene = ctx.id ? this._findScene(ctx.id) : null
        if (scene) this._openWritingForScene(scene)
      },
      "assign-unassigned-chapter": (_e, _t, ctx) => ctx.chapter && this._assignChapter(ctx.chapter),
      "save-scene-detail": (_e, _t, ctx) => ctx.id && this._saveSceneDetails(ctx.id),
      "mark-scene-reviewed": (_e, _t, ctx) => ctx.id && this._markSceneReviewed(ctx.id),
      "mark-scene-unreviewed": (_e, _t, ctx) => ctx.id && this._markSceneUnreviewed(ctx.id),
      "toggle-fusion-selection": (e, t, ctx) => {
        e.stopPropagation()
        this._toggleFusionSelection(ctx.id, t.checked)
      },
      "select-visible-fusion-scenes": () => this._selectVisibleFusionScenes(),
      "clear-fusion-selection": () => this._clearFusionSelection(),
      "start-selected-merge": () => this._startSelectedMerge(),
      "start-ai-fusion-draft": () => this._startManualFusion(),
      "start-manual-fusion": () => this._startManualFusion(),
      "start-merge-scene": (_e, _t, ctx) => ctx.id && this._startMerge(ctx.id),
      "start-split-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "close-scene-detail": () => {
        this._mobileDetailOpen = false
        router.renderCurrentView()
      },
    })

    bindActionMenus()
  },
}

router.registerView("scene", sceneWorkbenchView)
window.sceneWorkbenchView = sceneWorkbenchView
export default sceneWorkbenchView
