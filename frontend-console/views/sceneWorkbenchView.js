import { bindWorkspaceClick } from "../shared/viewHelper.js"

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
  _activeHealth: null,

  async onEnter() {
    this._loading = true
    this._workbench = null
    if (!state.currentProjectId) {
      this._loading = false
      return
    }
    try {
      this._workbench = await api.outline.getSceneWorkbench(
        state.currentProjectId,
        state.currentSubView || null
      )
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

  onLeave() {},

  async render() {
    if (this._loading) return '<div class="loading">加载中...</div>'
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }
    if (!this._workbench) {
      return '<div class="empty-state"><p>场景工作台暂不可用。</p></div>'
    }

    const selected = this._selectedSceneItem()
    const narrow = typeof window !== "undefined" && window.innerWidth < 720
    const detail = this._renderDetail(selected, narrow)
    const html = `
      <div class="scene-workbench ${narrow ? "is-narrow" : ""}">
        <section class="scene-workbench__organize">
          ${this._renderHealthFilters()}
          ${this._renderSceneList()}
        </section>
        ${narrow ? "" : `<aside class="scene-workbench__detail">${detail}</aside>`}
        ${narrow && selected ? `<div class="scene-workbench-drawer">${detail}</div>` : ""}
      </div>
    `
    setTimeout(() => this._bindEvents(), 0)
    return html
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

  _renderSceneRow(item, selectedId) {
    const scene = item.scene || {}
    const selected = selectedId === scene.id ? "is-selected" : ""
    const health = (item.health || []).map((key) => {
      const label = this._healthLabel(key)
      return `<span class="scene-health-chip">${esc(label)}</span>`
    }).join("")
    return `
      <article class="scene-workbench-row ${selected}" data-id="${esc(scene.id)}">
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
          <button class="btn btn-sm" data-action="edit-workbench-scene" data-id="${esc(scene.id)}">编辑</button>
          <button class="btn btn-sm" data-action="organize-workbench-scene" data-id="${esc(scene.id)}">整理</button>
          <button class="btn btn-sm" data-action="open-writing-scene" data-id="${esc(scene.id)}">打开写作</button>
        </div>
      </article>
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
          <div><strong>关联资产</strong><span>剧情线 / 伏笔 / 揭示 / 地图摘要将在整理预览中展示</span></div>
          <div><strong>来源与复核</strong><span>${esc(this._sourceLabel(scene.source))} · ${esc(this._statusLabel(scene.status))}</span></div>
        </section>
        <div class="scene-detail-actions">
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
    showModal("拆分 Scene 影响预览", this._renderPreview(preview), [
      { text: "取消", class: "", handler: () => closeModal() },
      {
        text: "确认拆分",
        class: "btn-primary",
        handler: async () => {
          await api.outline.splitScene(state.currentProjectId, {
            ...request,
            confirmed: true,
          })
          toast("Scene 已拆分", "success")
          closeModal()
          await router.refresh()
        },
      },
    ])
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

  _bindEvents() {
    bindWorkspaceClick(this, {
      "filter-health": (_e, _t, ctx) => {
        this._activeHealth = this._activeHealth === ctx.id ? null : ctx.id
        router.renderCurrentView()
      },
      "select-workbench-scene": (_e, _t, ctx) => ctx.id && router.navigate("scene", ctx.id),
      "edit-workbench-scene": (_e, _t, ctx) => ctx.id && router.navigate("scene", ctx.id),
      "organize-workbench-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "open-writing-scene": (_e, _t, ctx) => {
        const scene = ctx.id ? this._findScene(ctx.id) : null
        if (scene) this._openWritingForScene(scene)
      },
      "assign-unassigned-chapter": (_e, _t, ctx) => ctx.chapter && this._assignChapter(ctx.chapter),
      "save-scene-detail": (_e, _t, ctx) => ctx.id && this._saveSceneDetails(ctx.id),
      "start-merge-scene": (_e, _t, ctx) => ctx.id && this._startMerge(ctx.id),
      "start-split-scene": (_e, _t, ctx) => ctx.id && this._startSplit(ctx.id),
      "close-scene-detail": () => router.navigate("scene", null),
    })
  },
}

router.registerView("scene", sceneWorkbenchView)
window.sceneWorkbenchView = sceneWorkbenchView
export default sceneWorkbenchView
