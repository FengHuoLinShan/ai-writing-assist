/**
 * RAG 检索 payload / 结果处理纯逻辑 — 从 ragView 移植。
 * 数据来源由 DOM 读取改为表单状态对象；校验/截断/高亮语义保持一致。
 */
import { RAG_RESULT_FETCH_LIMIT } from "./routeState.js"

/**
 * 规范章节范围，供表单提交和 URL 恢复共用。空端点保持可选；非空端点必须是正整数。
 */
export function normalizeChapterRange(chapterFrom, chapterTo) {
  const normalizeEndpoint = (raw, label) => {
    const value = String(raw ?? "").trim()
    if (!value) return { value: null }
    const parsed = Number(value)
    if (!/^\d+$/.test(value) || !Number.isSafeInteger(parsed) || parsed < 1) {
      return { error: `${label}必须是大于等于 1 的整数` }
    }
    return { value: parsed }
  }
  const from = normalizeEndpoint(chapterFrom, "起始章")
  if (from.error) return { error: from.error }
  const to = normalizeEndpoint(chapterTo, "结束章")
  if (to.error) return { error: to.error }
  if (from.value != null && to.value != null && from.value > to.value) {
    return { error: "起始章不能大于结束章" }
  }
  return { chapterFrom: from.value, chapterTo: to.value }
}

/**
 * 对应 _buildEvidencePayload：由表单状态构造证据检索 payload。
 * @param {object} form - {query, searchKind, contentMode, visibilityMode, chapterFrom,
 *   chapterTo, cutoffChapter, cutoffSceneId, cutoffOffset, characterId, scopes, includePending,
 *   currentSceneId}
 * @param {string} projectId
 * @returns {{payload?: object, error?: string}} 校验失败返回 error 文案（warning）
 */
export function buildEvidencePayload(form, projectId) {
  const chapterRange = normalizeChapterRange(form.chapterFrom, form.chapterTo)
  if (chapterRange.error) return { error: chapterRange.error }
  const integer = (raw) => {
    const parsed = Number(raw)
    return Number.isInteger(parsed) && parsed >= 1 ? parsed : null
  }
  const mode = form.visibilityMode || "author"
  const cutoffChapter = integer(form.cutoffChapter)
  const cutoffOffsetRaw = String(form.cutoffOffset ?? "").trim()
  const cutoffOffsetValue = Number(cutoffOffsetRaw)
  const cutoffOffset = cutoffOffsetRaw
    && Number.isInteger(cutoffOffsetValue)
    && cutoffOffsetValue >= 0
    ? cutoffOffsetValue
    : null
  const characterId = form.characterId || null

  if ((mode === "reader" || mode === "character") && cutoffChapter == null) {
    return { error: "读者/角色视角必须设置可见截止章" }
  }
  if (mode === "character" && !characterId) {
    return { error: "角色视角必须选择人物" }
  }

  return {
    payload: {
      novel_id: projectId,
      query: form.query,
      search_kind: form.searchKind || "smart",
      content_mode: form.contentMode || "canonical",
      visibility: {
        mode,
        cutoff_chapter: cutoffChapter,
        cutoff_scene_id: form.cutoffSceneId || null,
        cutoff_offset: cutoffOffset,
        character_id: characterId,
      },
      scopes: form.scopes?.length ? form.scopes : ["manuscript"],
      include_pending_objects: Boolean(form.includePending),
      chapter_from: chapterRange.chapterFrom,
      chapter_to: chapterRange.chapterTo,
      context_scene_id: mode === "author" ? (form.currentSceneId || null) : null,
      top_k: RAG_RESULT_FETCH_LIMIT,
    },
  }
}

/** 对应 _normalizeEvidenceHit。 */
export function normalizeEvidenceHit(item = {}) {
  return {
    ...item,
    kind: item.kind || (item.source_type === "chapter_text" ? "manuscript" : item.source_type || "unknown"),
    title: item.title || (item.chapter_index ? `第 ${item.chapter_index} 章` : `来源：${item.source_type || "unknown"}`),
    snippet: item.snippet || item.text || item.summary || item.content || "",
    score: item.score ?? item.similarity ?? null,
    scene_refs: item.scene_refs || [],
    parent_scene_contexts: item.parent_scene_contexts || item.scene_refs || [],
    object_refs: item.object_refs || [],
    index_fresh: item.index_fresh !== false,
    match_count: Number(item.match_count) > 0 ? Number(item.match_count) : 1,
    match_basis: item.match_basis === "occurrence" ? "occurrence" : "chunk",
    writing_relevance: item.writing_relevance || {},
  }
}

export function parentSceneContexts(hit = {}) {
  return (hit.parent_scene_contexts || hit.scene_refs || []).filter((ref) => (
    ref?.target_type === "outline_scene" && ref.scene_index != null
  ))
}

export function parentSceneLabel(ref = {}) {
  const index = ref.scene_index ?? "-"
  const title = ref.scene_title || ref.target_name
  return title && title !== `Scene ${index}`
    ? `场景 ${index} · ${title}`
    : `场景 ${index}`
}

const SCOPE_LABELS = { manuscript: "正文", world: "世界对象", outline: "结构" }

/** 对应 _advancedFilterSummary（characters/scenes 用于标签解析）。 */
export function advancedFilterSummary(filterState = {}, { characters = [], scenes = [] } = {}) {
  const summary = []
  const chapterFrom = Number(filterState.chapterFrom) || null
  const chapterTo = Number(filterState.chapterTo) || null
  if (chapterFrom && chapterTo) summary.push(`第 ${chapterFrom}–${chapterTo} 章`)
  else if (chapterFrom) summary.push(`第 ${chapterFrom} 章起`)
  else if (chapterTo) summary.push(`截至第 ${chapterTo} 章`)

  const visibilityMode = filterState.visibilityMode || "author"
  if (visibilityMode === "reader") summary.push("读者视角")
  if (visibilityMode === "character") {
    const character = characters.find((item) => (
      (item.id || item.entity_id) === filterState.characterId
    ))
    summary.push(character?.name ? `角色视角：${character.name}` : "角色视角")
  }
  if (filterState.cutoffChapter) summary.push(`可见至第 ${filterState.cutoffChapter} 章`)
  if (filterState.cutoffSceneId) {
    const scene = scenes.find((item) => item.id === filterState.cutoffSceneId)
    summary.push(scene?.title ? `可见至 ${scene.title}` : "已设置场景截止点")
  }
  if (filterState.cutoffOffset != null && filterState.cutoffOffset !== "") {
    summary.push(`章内位置 ${filterState.cutoffOffset}`)
  }

  const scopes = Array.isArray(filterState.scopes) ? filterState.scopes : ["manuscript"]
  if (scopes.length !== 1 || scopes[0] !== "manuscript") {
    summary.push(`范围：${scopes.map((scope) => SCOPE_LABELS[scope] || scope).join("、")}`)
  }
  if (filterState.includePending) summary.push("含待处理对象")
  return summary
}

/** 对应 _renderSearchError 的文案推断。 */
export function searchErrorReason(error) {
  const message = String(error?.message || "").toLowerCase()
  const status = Number(error?.status || error?.statusCode)
  const timeout = message.includes("超时") || message.includes("timeout")
  const missingInterface = message.includes("证据检索接口不可用")
  const unavailable = [502, 503, 504].includes(status)
    || message.includes("network")
    || message.includes("网络")
    || message.includes("暂时不可用")
  if (missingInterface) return "证据检索接口不可用，本次未展示未经校验的旧索引结果。"
  if (timeout) return "请求等待时间过长，可能是索引繁忙或连接暂时不可用。"
  if (unavailable) return "检索服务暂时不可用，可以稍后重试。"
  return "本次检索请求未能完成，可以使用原条件重试。"
}

/**
 * 关键词高亮（对应 _highlightSnippet）：返回三段文本，模板用 <mark> 渲染，
 * 不产生 HTML 字符串（遵守 v-html 禁令）。
 */
export function highlightParts(text, query) {
  const source = String(text || "").slice(0, 500)
  const needle = String(query || "")
  if (!needle) return { before: source, mark: "", after: "" }
  const index = source.toLocaleLowerCase().indexOf(needle.toLocaleLowerCase())
  if (index < 0) return { before: source, mark: "", after: "" }
  return {
    before: source.slice(0, index),
    mark: source.slice(index, index + needle.length),
    after: source.slice(index + needle.length),
  }
}

export const HIT_KIND_LABELS = { manuscript: "正文", world_object: "世界对象", outline_asset: "结构" }

export function hitKindLabel(kind) {
  return HIT_KIND_LABELS[kind] || kind
}

/** 对应 _renderSearchResults 的计数文案。 */
export function resultCountLabel(total, hits, visibleCount) {
  const chapterResultCount = hits.filter((hit) => hit.chapter_index).length
  const resultLabel = chapterResultCount === hits.length ? "个章节结果" : "条结果"
  return `找到 ${total} ${resultLabel} · 已显示 ${visibleCount}`
}
