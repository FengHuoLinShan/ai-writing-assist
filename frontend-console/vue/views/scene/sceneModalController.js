import {
  getApi,
  getAppState,
  getCloseModal,
  getEsc,
  getShowModalHtml,
  getToast,
} from "../../bridge/index.js"
import { createReferencePicker } from "../../../shared/referencePicker.js"
import { confirmAsync } from "../../../shared/confirmAsync.js"
import {
  SOURCE_OPTIONS,
  STATUS_OPTIONS,
  TAG_OPTIONS,
  sceneChapterLabel,
  sceneSourceLabel,
  sceneStatusLabel,
} from "./sceneModel.js"

const REVIEW_FIELDS = [
  ["title", "标题"],
  ["goal", "目标"],
  ["core_conflict", "核心冲突"],
  ["emotional_beat", "情感节奏"],
  ["must_happen", "必须发生"],
  ["must_not_happen", "禁止发生"],
  ["narrative_tag", "叙事标签"],
  ["pov_character_id", "视角人物"],
  ["chapter_ids", "章节映射"],
]

function formatValue(value) {
  if (Array.isArray(value)) return value.map((item) => typeof item === "object" ? JSON.stringify(item) : String(item)).join("；")
  if (value && typeof value === "object") return JSON.stringify(value)
  return value == null ? "" : String(value)
}

export function createSceneModalController({
  projectId,
  getItems,
  getSuggestions,
  refresh,
  selectScene,
  clearSelection,
}) {
  const api = getApi()
  const toast = getToast()
  const esc = getEsc()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  let disposed = false
  let generation = 0
  let mergePicker = null
  let fusionPreviewPending = false
  let fusionPreviewSequence = 0
  let fusionSavePending = false
  let activeReview = null

  const owns = (ownerGeneration = generation) => (
    !disposed
    && ownerGeneration === generation
    && getAppState()?.currentProjectId === projectId
    && getAppState()?.currentView === "outline"
    && getAppState()?.currentSubView === "scenes"
  )
  const items = () => getItems?.() || []
  const findItem = (id) => items().find((item) => item.scene?.id === id) || null
  const findScene = (id) => findItem(id)?.scene || null

  function destroyPicker() {
    mergePicker?.destroy?.()
    mergePicker = null
  }

  function dispose() {
    disposed = true
    generation += 1
    fusionPreviewSequence += 1
    destroyPicker()
    activeReview = null
  }

  function renderImpact(preview) {
    const warnings = (preview?.warnings || []).map((item) => `<li>${esc(item)}</li>`).join("")
    return `
      <div class="scene-impact-preview">
        <div><strong>操作</strong><span>${esc(preview?.operation || "")}</span></div>
        <div><strong>章节映射变化</strong><pre>${esc(JSON.stringify(preview?.chapter_mapping_change || {}, null, 2))}</pre></div>
        <div><strong>字段变化</strong><pre>${esc(JSON.stringify(preview?.field_changes || {}, null, 2))}</pre></div>
        <div><strong>关联剧情线</strong><span>${esc(preview?.related_threads?.count ?? 0)} 条</span></div>
        <div><strong>关联伏笔 / 揭示</strong><span>${esc(preview?.related_foreshadowing?.count ?? 0)} / ${esc(preview?.related_reveals?.count ?? 0)}</span></div>
        <div><strong>地图摘要影响</strong><span>${esc(preview?.map_summary_impact?.message || "无")}</span></div>
        ${warnings ? `<ul>${warnings}</ul>` : ""}
      </div>`
  }

  async function previewMerge(targetSceneId, sourceSceneIds) {
    const ownerGeneration = ++generation
    let preview
    try {
      preview = await api.outline.previewSceneMerge(projectId, {
        target_scene_id: targetSceneId,
        source_scene_ids: sourceSceneIds,
      })
    } catch (err) {
      if (owns(ownerGeneration)) toast(err.message || "场景合并预览失败", "error")
      return false
    }
    if (!owns(ownerGeneration)) return false
    showModalHtml("合并场景影响预览", renderImpact(preview), [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "确认合并",
        class: "btn-primary",
        handler: async () => {
          if (!owns(ownerGeneration)) {
            closeModal()
            toast("项目或页面已切换，未执行场景合并", "warning")
            return false
          }
          try {
            await api.outline.mergeScenes(projectId, {
              target_scene_id: targetSceneId,
              source_scene_ids: sourceSceneIds,
              confirmed: true,
            })
            closeModal()
            clearSelection?.()
            toast("场景已合并", "success")
            await refresh?.()
            return true
          } catch (err) {
            toast(`场景合并失败：${err.message || "未知错误"}`, "error")
            return false
          }
        },
      },
    ])
    return true
  }

  function startMerge(targetSceneId) {
    destroyPicker()
    const target = findScene(targetSceneId)
    if (!target) return false
    const ownerGeneration = generation
    showModalHtml("选择要合并的场景", `
      <p>选择要合并到<strong>「${esc(target.title || "当前场景")}」</strong>中的另一个场景。</p>
      <div id="scene-merge-reference-picker"></div>
      <p class="form-help">可按标题、目标或冲突搜索；历史场景和当前场景不会出现在结果中。</p>
    `, [
      { text: "取消", class: "", handler: () => { destroyPicker(); closeModal() } },
      {
        text: "预览合并影响",
        class: "btn-primary",
        handler: async () => {
          if (!owns(ownerGeneration)) return false
          const sourceId = mergePicker?.getRefs?.()?.[0]?.id
          if (!sourceId) {
            toast("请选择要合并的场景", "warning")
            return false
          }
          destroyPicker()
          closeModal()
          await previewMerge(targetSceneId, [sourceId])
          return false
        },
      },
    ], { size: "large" })
    const root = document.getElementById("scene-merge-reference-picker")
    if (!root) return false
    mergePicker = createReferencePicker({
      root,
      projectId,
      sources: [{
        kind: "scene",
        label: "场景",
        search: async (query, { projectId: searchProjectId, limit }) => {
          if (!owns(ownerGeneration) || searchProjectId !== projectId) return []
          const data = await api.outline.getSceneWorkbench(projectId, null, {
            q: query || undefined,
            view_mode: "normal",
            skip: 0,
            limit,
          })
          if (!owns(ownerGeneration)) return []
          return (data?.items || [])
            .map((entry) => entry.scene || entry)
            .filter((scene) => scene.id !== targetSceneId && scene.status !== "deprecated")
            .map((scene) => ({
              id: scene.id,
              label: scene.title || "未命名场景",
              description: [sceneChapterLabel(scene), scene.goal || scene.core_conflict].filter(Boolean).join(" · "),
              status: sceneStatusLabel(scene),
            }))
        },
      }],
      placeholder: "搜索场景标题、目标或冲突",
    })
    return true
  }

  function startSelectedMerge(sceneIds) {
    const selected = sceneIds.map(findScene).filter(Boolean)
    if (selected.length < 2) {
      toast("请至少选择 2 个场景再合并", "warning")
      return false
    }
    showModalHtml("选择合并目标", `
      <p>目标场景将保留，其他场景的章节映射会合并到目标中。</p>
      ${selected.map((scene, index) => `
        <label class="scene-picker-card">
          <input type="radio" name="merge-target-scene" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""} />
          <strong>${esc(scene.title || "未命名场景")}</strong><span>${esc(sceneChapterLabel(scene))}</span>
        </label>`).join("")}
    `, [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "预览合并影响",
        class: "btn-primary",
        handler: async () => {
          const targetId = document.querySelector('input[name="merge-target-scene"]:checked')?.value
          if (!targetId) return false
          closeModal()
          await previewMerge(targetId, sceneIds.filter((id) => id !== targetId))
          return false
        },
      },
    ])
    return true
  }

  function editor(field, label, value, prefix = "scene-fusion") {
    const id = `${prefix}-${field}`
    if (field === "narrative_tag") {
      const current = value || "draft"
      return `<select class="form-select" id="${esc(id)}">${TAG_OPTIONS.map(([key, text]) => `<option value="${esc(key)}" ${key === current ? "selected" : ""}>${esc(text)}</option>`).join("")}</select>`
    }
    if (field === "chapter_ids") return `<input class="form-input" id="${esc(id)}" value="${esc(formatValue(value))}" readonly />`
    if (field === "title" || field === "pov_character_id") return `<input class="form-input" id="${esc(id)}" value="${esc(value || "")}" />`
    return `<textarea class="form-textarea" id="${esc(id)}" rows="4">${esc(value || "")}</textarea>`
  }

  function referenceCell(values) {
    if (!values?.length) return '<span class="scene-draft-review-empty">无来源证据</span>'
    return values.map((entry) => {
      const value = entry?.value ?? entry?.summary ?? entry
      const source = entry?.scene_title || entry?.source_label || "来源场景"
      const text = formatValue(value)
      return `<article class="scene-draft-ref"><strong>${esc(source)}</strong><p>${esc(text || "未提供")}</p></article>`
    }).join("")
  }

  function reviewTable(headers, rows) {
    return `
      <section class="scene-draft-review-shell" aria-label="场景字段对比">
      <label class="scene-draft-review-filter"><input type="checkbox" data-action="filter-draft-review-differences" /> 仅看初始差异</label>
      <p data-role="draft-review-filter-note" class="writing-form-hint" hidden></p>
      <table class="scene-draft-review-grid"><thead><tr>${headers.map((item) => `<th>${esc(item)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table>
      </section>`
  }

  function bindReviewFilter() {
    const body = document.getElementById("modal-body")
    const filter = body?.querySelector('[data-action="filter-draft-review-differences"]')
    const rows = Array.from(body?.querySelectorAll(".scene-draft-review-row") || [])
    const note = body?.querySelector('[data-role="draft-review-filter-note"]')
    const apply = () => {
      let hidden = 0
      rows.forEach((row) => {
        row.hidden = Boolean(filter?.checked) && row.dataset.difference !== "true" && row.dataset.noEvidence !== "true"
        if (row.hidden) hidden += 1
      })
      if (note) {
        note.hidden = !hidden
        note.textContent = hidden ? `已隐藏 ${hidden} 个无差异字段；这些字段仍会随草稿保存。` : ""
      }
    }
    filter?.addEventListener("change", apply)
    apply()
  }

  function readFusionDraft() {
    const draft = activeReview?.draft_scene || activeReview?.fused_scene || {}
    const value = (id, fallback = null) => document.getElementById(id)?.value?.trim() || fallback
    const chapterText = value("scene-fusion-chapter_ids", (draft.chapter_ids || []).join(",")) || ""
    return {
      title: value("scene-fusion-title", draft.title || null),
      goal: value("scene-fusion-goal", draft.goal || null),
      core_conflict: value("scene-fusion-core_conflict", draft.core_conflict || null),
      emotional_beat: value("scene-fusion-emotional_beat", draft.emotional_beat || null),
      must_happen: value("scene-fusion-must_happen", draft.must_happen || null),
      must_not_happen: value("scene-fusion-must_not_happen", draft.must_not_happen || null),
      narrative_function: value("scene-fusion-narrative_function", draft.narrative_function || null),
      narrative_tag: value("scene-fusion-narrative_tag", draft.narrative_tag || "draft") || "draft",
      pov_character_id: value("scene-fusion-pov_character_id", draft.pov_character_id || null),
      chapter_ids: chapterText.split(/[,，;；、\s]+/).map((item) => item.trim()).filter(Boolean),
      structure_meta: {
        ...(draft.structure_meta || {}),
        draft_review_mode: activeReview?.mode || "fusion",
        primary_scene_id: activeReview?.primary_scene_id || null,
        confidence: activeReview?.confidence ?? null,
        draft_review_warnings: activeReview?.warnings || [],
        draft_review_conflicts: activeReview?.conflicts || [],
      },
    }
  }

  async function saveFusion(mode, sourceSceneIds) {
    if (fusionSavePending || !owns()) return false
    fusionSavePending = true
    document.querySelectorAll("#modal-footer button, #modal-body [data-action='confirm-fusion-deprecation']").forEach((button) => { button.disabled = true })
    const payload = {
      source_scene_ids: sourceSceneIds,
      primary_scene_id: activeReview?.primary_scene_id || null,
      mode,
      ...(activeReview?.suggestion_id ? { suggestion_id: activeReview.suggestion_id } : {}),
      ...(mode === "discard" ? {} : { fused_scene: readFusionDraft() }),
    }
    try {
      const result = await api.outline.saveSceneFusion(projectId, payload)
      closeModal()
      clearSelection?.()
      toast(result?.status === "discarded" ? "融合结果已放弃" : "融合场景已保存", "success")
      await refresh?.()
      return true
    } catch (err) {
      toast(err.message || "场景融合保存失败", "error")
      return false
    } finally {
      fusionSavePending = false
      document.querySelectorAll("#modal-footer button, #modal-body [data-action='confirm-fusion-deprecation']").forEach((button) => { button.disabled = false })
    }
  }

  function showFusionPreview(preview, sourceSceneIds) {
    const draft = preview?.draft_scene || preview?.fused_scene || {}
    activeReview = { ...preview, draft_scene: draft, source_scene_ids: sourceSceneIds, request_project_id: projectId }
    const refs = preview?.field_references || {}
    const fields = [...REVIEW_FIELDS.slice(0, 6), ["narrative_function", "叙事功能"], ...REVIEW_FIELDS.slice(6)]
    const rows = fields.map(([field, label]) => {
      const values = refs[field] || []
      const distinct = new Set([formatValue(draft[field]), ...values.map((entry) => formatValue(entry?.value ?? entry))])
      return `<tr class="scene-draft-review-row" data-difference="${distinct.size > 1}" data-no-evidence="${values.length === 0}">
        <th scope="row">${esc(label)}</th><td data-label="AI 建议">${editor(field, label, draft[field])}</td><td data-label="来源场景">${referenceCell(values)}</td>
      </tr>`
    }).join("")
    const sourceLabels = sourceSceneIds.map((id) => findScene(id)?.title || id)
    const body = `<div class="scene-fusion-preview">
      <div class="scene-fusion-preview__meta"><div><strong>主场景</strong><span>${esc(findScene(preview?.primary_scene_id)?.title || "未指定")}</span></div>
      <div><strong>来源场景</strong><span>${esc(sourceLabels.join("、"))}</span></div></div>
      ${reviewTable(["字段", "AI 建议", "来源场景"], rows)}
      <section data-role="fusion-deprecation-confirm" class="scene-draft-deprecation-confirm" hidden>
        <p>将把以下原场景移入历史：${esc(sourceLabels.join("、"))}</p>
        <button class="btn" data-action="cancel-fusion-deprecation">返回编辑</button>
        <button class="btn btn-danger" data-action="confirm-fusion-deprecation">确认将 ${sourceSceneIds.length} 个原场景移入历史并保存</button>
      </section>
    </div>`
    showModalHtml("场景 AI 建议预览", body, [
      { text: "放弃融合结果", class: "", handler: () => saveFusion("discard", sourceSceneIds) },
      { text: "继续编辑融合结果后再保存", class: "btn-primary", handler: () => saveFusion("keep_originals", sourceSceneIds) },
      {
        text: `将 ${sourceSceneIds.length} 个原场景移入历史并保存`,
        class: "btn-danger",
        handler: () => {
          const section = document.querySelector('[data-role="fusion-deprecation-confirm"]')
          if (section) section.hidden = false
          return false
        },
      },
    ], { size: "large" })
    bindReviewFilter()
    document.querySelector('[data-action="cancel-fusion-deprecation"]')?.addEventListener("click", () => {
      const section = document.querySelector('[data-role="fusion-deprecation-confirm"]')
      if (section) section.hidden = true
    })
    document.querySelector('[data-action="confirm-fusion-deprecation"]')?.addEventListener("click", () => {
      void saveFusion("deprecate_originals", sourceSceneIds)
    })
  }

  async function previewFusion(sourceSceneIds, primarySceneId, suggestionId = null) {
    if (fusionPreviewPending) {
      toast("场景融合建议正在生成，请稍候", "info")
      return false
    }
    const ownerGeneration = generation
    const requestSequence = ++fusionPreviewSequence
    fusionPreviewPending = true
    let preview
    try {
      preview = await api.outline.previewSceneFusion(projectId, {
        source_scene_ids: sourceSceneIds,
        primary_scene_id: primarySceneId,
        ...(suggestionId ? { suggestion_id: suggestionId } : {}),
      })
    } catch (err) {
      if (owns(ownerGeneration) && requestSequence === fusionPreviewSequence) toast(err.message || "场景融合建议生成失败", "error")
      return false
    } finally {
      if (requestSequence === fusionPreviewSequence) fusionPreviewPending = false
    }
    if (!owns(ownerGeneration) || requestSequence !== fusionPreviewSequence) return false
    showFusionPreview({ ...preview, primary_scene_id: primarySceneId, suggestion_id: suggestionId }, sourceSceneIds)
    return true
  }

  function startFusion(sceneIds, suggestionId = null) {
    const selected = sceneIds.map(findScene).filter(Boolean)
    if (selected.length < 2) {
      toast("请至少选择 2 个场景再融合", "warning")
      return false
    }
    showModalHtml("选择主场景", `
      <p>主场景只在内容冲突时作为偏好；所有来源场景的正文都会参与。</p>
      ${selected.map((scene, index) => `<label class="scene-picker-card"><input type="radio" name="fusion-primary-scene" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""}/><strong>${esc(scene.title || "未命名场景")}</strong><span>${esc(sceneChapterLabel(scene))}</span></label>`).join("")}
    `, [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "生成 AI 融合建议",
        class: "btn-primary",
        handler: async () => {
          const primary = document.querySelector('input[name="fusion-primary-scene"]:checked')?.value
          if (!primary) return false
          await previewFusion(sceneIds, primary, suggestionId)
          return false
        },
      },
    ])
    return true
  }

  function splitDraftRows(preview) {
    const drafts = preview?.draft_scenes || []
    const refs = preview?.field_references || {}
    return REVIEW_FIELDS.map(([field, label]) => {
      const evidence = refs[field] || []
      const distinct = new Set([formatValue(drafts[0]?.[field]), formatValue(drafts[1]?.[field]), ...evidence.map((entry) => formatValue(entry?.value ?? entry))])
      return `<tr class="scene-draft-review-row" data-difference="${distinct.size > 1}" data-no-evidence="${evidence.length === 0}">
        <th scope="row">${esc(label)}</th><td data-label="原场景">${referenceCell(evidence)}</td>
        <td data-label="建议 A">${editor(field, label, drafts[0]?.[field], "scene-split-0")}</td>
        <td data-label="建议 B">${editor(field, label, drafts[1]?.[field], "scene-split-1")}</td>
      </tr>`
    }).join("")
  }

  function readSplitDrafts() {
    return [0, 1].map((index) => {
      const result = {}
      for (const [field] of REVIEW_FIELDS.filter(([key]) => key !== "chapter_ids")) {
        const value = document.getElementById(`scene-split-${index}-${field}`)?.value?.trim() || ""
        result[field] = field === "narrative_tag" ? (value || "draft") : (value || null)
      }
      return result
    })
  }

  async function previewSplit(sceneId, splitChapterIndex) {
    const ownerGeneration = generation
    let preview
    try {
      preview = await api.outline.previewSceneSplit(projectId, {
        source_scene_id: sceneId,
        split_chapter_index: splitChapterIndex,
      })
    } catch (err) {
      if (owns(ownerGeneration)) toast(err.message || "拆分预览生成失败", "error")
      return false
    }
    if (!owns(ownerGeneration)) return false
    const impact = preview?.chapter_mapping_change?.after || {}
    showModalHtml("场景拆分预览", `<div class="scene-fusion-preview">
      ${reviewTable(["字段", "原场景", "建议 A", "建议 B"], splitDraftRows(preview))}
      <section class="scene-split-impact-summary" aria-label="拆分影响摘要"><h3>影响摘要</h3>
        <p>章节映射：${esc(Object.entries(impact).map(([id, ids]) => `${id}: ${(ids || []).join("、") || "无"}`).join("；") || "以表格为准")}</p>
        <p>关联剧情线：${esc(preview?.related_threads?.count ?? 0)} 条</p>
        <p>关联伏笔 / 揭示：${esc(preview?.related_foreshadowing?.count ?? 0)} / ${esc(preview?.related_reveals?.count ?? 0)}</p>
      </section></div>`, [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "确认拆分",
        class: "btn-primary",
        handler: async () => {
          if (!owns(ownerGeneration)) return false
          try {
            await api.outline.splitScene(projectId, {
              source_scene_id: sceneId,
              split_chapter_index: splitChapterIndex,
              draft_scenes: readSplitDrafts(),
              confirmed: true,
            })
            closeModal()
            toast("场景已拆分", "success")
            await refresh?.()
            return true
          } catch (err) {
            toast(`场景拆分失败：${err.message || "未知错误"}`, "error")
            return false
          }
        },
      },
    ], { size: "large" })
    bindReviewFilter()
    return true
  }

  function startSplit(sceneId) {
    const scene = findScene(sceneId)
    const chapters = [...new Set((scene?.chapter_ids || []).map(Number).filter((item) => Number.isInteger(item) && item > 0))].sort((a, b) => a - b)
    if (!scene) {
      toast("场景不存在或已变化，请刷新后重试", "warning")
      return false
    }
    if (chapters.length < 2) {
      toast("该场景至少需要关联两个章节才能按章节拆分", "info")
      return false
    }
    const defaultBoundary = chapters[1]
    const partition = (boundary) => ({ retained: chapters.filter((item) => item < boundary), created: chapters.filter((item) => item >= boundary) })
    const summary = (boundary) => {
      const parts = partition(boundary)
      return `<p><strong>保留在原场景：</strong>${esc(parts.retained.map((item) => `第 ${item} 章`).join("、"))}</p><p><strong>进入新场景：</strong>${esc(parts.created.map((item) => `第 ${item} 章`).join("、"))}</p>`
    }
    showModalHtml("拆分场景", `<div class="scene-split-setup">
      <p>当前场景：<strong>${esc(scene.title || "未命名场景")}</strong></p>
      <label class="writing-form-field"><span>新场景的起始章节</span><select id="scene-split-chapter-index">${chapters.slice(1).map((chapter) => `<option value="${chapter}" ${chapter === defaultBoundary ? "selected" : ""}>从第 ${chapter} 章起创建新场景</option>`).join("")}</select></label>
      <div id="scene-split-partition" class="scene-split-impact-summary" aria-live="polite">${summary(defaultBoundary)}</div>
      <p id="scene-split-setup-error" class="form-error" role="alert"></p></div>`, [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "生成拆分预览",
        class: "btn-primary",
        handler: async () => {
          const boundary = Number(document.getElementById("scene-split-chapter-index")?.value)
          const parts = partition(boundary)
          if (!parts.retained.length || !parts.created.length) return false
          await previewSplit(sceneId, boundary)
          return false
        },
      },
    ])
    const select = document.getElementById("scene-split-chapter-index")
    select?.addEventListener("change", () => {
      const target = document.getElementById("scene-split-partition")
      if (target) target.innerHTML = summary(Number(select.value))
    })
    return true
  }

  function showAssignChapters(sceneId, unassigned = []) {
    const scene = findScene(sceneId)
    if (!scene) return false
    const current = new Set((scene.chapter_ids || []).map(String))
    const available = [...new Set([...current, ...unassigned.map(String)])].sort((a, b) => Number(a) - Number(b))
    if (!available.length) {
      toast("当前没有可整理的章节", "info")
      return false
    }
    showModalHtml("移动 / 关联章节", available.map((chapter) => `<label class="selection-checkbox"><input type="checkbox" name="scene-assign-chapter" value="${esc(chapter)}" ${current.has(chapter) ? "checked" : ""}/><span>第 ${esc(chapter)} 章</span></label>`).join(""), [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "保存章节映射",
        class: "btn-primary",
        handler: async () => {
          const chapterIds = Array.from(document.querySelectorAll('input[name="scene-assign-chapter"]:checked')).map((input) => String(input.value)).sort((a, b) => Number(a) - Number(b))
          await api.outline.updateSceneWorkbenchMapping(projectId, sceneId, { chapter_ids: [...new Set(chapterIds)] })
          closeModal()
          toast("章节映射已更新", "success")
          await refresh?.()
          return true
        },
      },
    ])
    return true
  }

  function assignChapter(chapterIndex) {
    const scenes = items().map((item) => item.scene).filter(Boolean)
    if (!scenes.length) {
      toast("当前没有可关联的场景", "warning")
      return false
    }
    showModalHtml(`分配第 ${chapterIndex} 章`, scenes.map((scene, index) => `<label class="scene-picker-card"><input type="radio" name="assign-target-scene" value="${esc(scene.id)}" ${index === 0 ? "checked" : ""}/><strong>${esc(scene.title || "未命名场景")}</strong><span>${esc(sceneChapterLabel(scene))}</span></label>`).join(""), [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "确认分配",
        class: "btn-primary",
        handler: async () => {
          const sceneId = document.querySelector('input[name="assign-target-scene"]:checked')?.value
          const scene = findScene(sceneId)
          if (!scene) return false
          const chapterIds = [...new Set([...(scene.chapter_ids || []), String(chapterIndex)])].sort((a, b) => Number(a) - Number(b))
          await api.outline.updateSceneWorkbenchMapping(projectId, sceneId, { chapter_ids: chapterIds })
          closeModal()
          toast("章节已分配", "success")
          await refresh?.()
          return true
        },
      },
    ])
    return true
  }

  function confirmSourceMapping(sceneId, fingerprint) {
    if (!fingerprint) {
      toast("正文定位已变化，请刷新后重试", "warning")
      return false
    }
    showModalHtml("确认章节级正文定位", '<p>确认后，该场景仍只保留章节级定位，不会伪造更精确的正文位置。</p>', [
      { text: "取消", class: "", handler: closeModal },
      {
        text: "确认仅按章节关联",
        class: "btn-primary",
        handler: async () => {
          try {
            await api.outline.reviewSceneSourceMappings(projectId, { items: [{ scene_id: sceneId, expected_fingerprint: fingerprint }], decision: "accept_chapter_only", confirmed: true })
            closeModal()
            toast("已确认章节级正文定位", "success")
            await refresh?.()
            return true
          } catch (err) {
            toast(err.message || "正文定位确认失败", "error")
            return false
          }
        },
      },
    ])
    return true
  }

  function organizeMapping(sceneId, unassigned) {
    showModalHtml("整理场景正文范围", "<p>选择要处理的动作。</p>", [
      { text: "移动章节", class: "", handler: () => { closeModal(); showAssignChapters(sceneId, unassigned) } },
      { text: "合并", class: "", handler: () => { closeModal(); startMerge(sceneId) } },
      { text: "拆分", class: "btn-primary", handler: () => { closeModal(); startSplit(sceneId) } },
    ])
  }

  async function dismissSuggestions(ids, message = "已忽略场景建议") {
    const safeIds = [...new Set(ids)].filter(Boolean).slice(0, 100)
    if (!safeIds.length) return false
    try {
      await api.outline.dismissFusionSuggestions(projectId, { suggestion_ids: safeIds, confirmed: true })
      closeModal()
      toast(message, "success")
      await refresh?.()
      return true
    } catch (err) {
      toast(err.message || "处理建议失败", "error")
      return false
    }
  }

  function dismissAllSuggestions() {
    const suggestions = (getSuggestions?.() || []).filter((item) => item.suggestion_kind !== "replacement")
    const ids = suggestions.map((item) => item.id).filter(Boolean).slice(0, 100)
    if (!ids.length) {
      toast("暂无可忽略的场景融合建议", "info")
      return false
    }
    showModalHtml("忽略场景融合建议", `<p>将忽略 ${ids.length} 条融合或分开建议；需要单独检查的场景替换建议不会被忽略。</p>`, [
      { text: "取消", class: "", handler: closeModal },
      { text: `确认忽略 ${ids.length} 条`, class: "btn-primary", handler: () => dismissSuggestions(ids) },
    ])
    return true
  }

  function showReplacementSuggestion(suggestion) {
    const drafts = suggestion?.proposed_scene?.draft_scenes || []
    const fields = REVIEW_FIELDS.filter(([field]) => !["pov_character_id", "chapter_ids"].includes(field))
    showModalHtml("场景替换检查", `<p>原场景会继续保留，只有明确采用后才会进入历史。</p><section><h4>受保护的原场景</h4>${(suggestion.source_scene_ids || []).map((id) => `<p>${esc(findScene(id)?.title || "原场景")}</p>`).join("")}</section><section><h4>新整理候选</h4>${drafts.map((draft, index) => `<article class="scene-replacement-draft" data-index="${index}"><h4>新候选 ${index + 1} · 章节 ${esc((draft.chapter_ids || []).join("、") || "-")}</h4>${fields.map(([field, label]) => `<label class="scene-detail-field scene-detail-field--wide"><span>${esc(label)}</span><textarea class="form-textarea" data-replacement-field="${esc(field)}">${esc(draft[field] || "")}</textarea></label>`).join("")}</article>`).join("")}</section>`, [
      { text: "保留原场景", class: "", handler: () => dismissSuggestions([suggestion.id], "已保留原场景") },
      { text: "采用新场景，原场景移入历史", class: "btn-primary", handler: () => applyReplacement(suggestion, false) },
      { text: "编辑后采用，原场景移入历史", class: "btn-primary", handler: () => applyReplacement(suggestion, true) },
    ])
  }

  async function applyReplacement(suggestion, edited) {
    const confirmed = await confirmAsync("采用新场景后，原场景将移入历史；正文和追踪信息会保留。", edited ? "确认编辑后采用" : "确认采用并移入历史")
    if (!confirmed) return false
    const draftScenes = edited ? Array.from(document.querySelectorAll(".scene-replacement-draft")).map((card) => Object.fromEntries(Array.from(card.querySelectorAll("[data-replacement-field]")).map((input) => [input.getAttribute("data-replacement-field"), input.value]))) : null
    try {
      const result = await api.outline.applySceneReplacement(projectId, { suggestion_id: suggestion.id, decision: edited ? "edit_then_replace" : "replace", confirmed: true, ...(edited ? { draft_scenes: draftScenes } : {}) })
      closeModal()
      const downstream = result?.downstream_refresh_required || []
      toast(downstream.length ? `新场景已采用，原场景已移入历史；建议按需重新整理：${downstream.join("、")}` : "新场景已采用，原场景已移入历史", "success")
      await refresh?.()
      return true
    } catch (err) {
      toast(err.message || "替换场景失败", "error")
      return false
    }
  }

  function showSuggestions(suggestionId = null) {
    const suggestions = getSuggestions?.() || []
    const direct = suggestionId ? suggestions.find((item) => item.id === suggestionId) : null
    if (direct) {
      if (direct.suggestion_kind === "replacement") return showReplacementSuggestion(direct)
      if (direct.proposed_action === "keep_separate") {
        showModalHtml("保持场景分开", "<p>确认后只更新建议状态，不修改场景内容。</p>", [{ text: "取消", class: "", handler: closeModal }, { text: "确认保持分开", class: "btn-primary", handler: () => dismissSuggestions([direct.id], "已确认场景保持分开") }])
        return true
      }
      return startFusion(direct.source_scene_ids || [], direct.id)
    }
    if (!suggestions.length) {
      toast("暂无场景融合建议", "info")
      return false
    }
    showModalHtml("场景融合建议", suggestions.map((item) => `<label class="scene-fusion-suggestion"><input type="radio" name="review-suggestion" value="${esc(item.id || "")}"/><strong>${esc(item.suggestion_kind === "replacement" ? "场景替换建议" : item.proposed_action === "keep_separate" ? "场景分开建议" : item.proposed_scene?.title || "场景融合建议")}</strong><p>${esc(item.reason || "无说明")}</p></label>`).join(""), [
      {
        text: "处理所选审查",
        class: "btn-primary",
        handler: () => {
          const id = document.querySelector('input[name="review-suggestion"]:checked')?.value
          const item = suggestions.find((candidate) => candidate.id === id)
          if (!item) { toast("请先选择一条需逐条审查的建议", "warning"); return false }
          if (item.suggestion_kind === "replacement") showReplacementSuggestion(item)
          else if (item.proposed_action === "keep_separate") dismissSuggestions([item.id], "已确认场景保持分开")
          else startFusion(item.source_scene_ids || [], item.id)
          return false
        },
      },
    ])
    return true
  }

  return {
    assignChapter,
    confirmSourceMapping,
    dismissAllSuggestions,
    dispose,
    organizeMapping,
    previewMerge,
    selectScene,
    showAssignChapters,
    showSuggestions,
    startFusion,
    startMerge,
    startSelectedMerge,
    startSplit,
  }
}
