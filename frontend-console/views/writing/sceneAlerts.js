/**
 * Scene 驾驶舱确定性警报。
 *
 * 这里只组合当前编辑缓冲区、Scene 卡、地图摘要和已有冲突检查；
 * 不调用 LLM、不持久化结果，也不生成修改建议。
 */

const SEVERITY_ORDER = ["high", "medium", "low", "info"]

export function buildSceneAlerts({
  scene,
  chapterIndex,
  content = "",
  mapSummary = null,
  mapError = null,
  latestCheck = null,
  checkError = null,
  checkLoading = false,
  draftId = null,
  versionNumber = null,
  isDirty = false,
} = {}) {
  if (!scene) return []

  const alerts = [
    ...structureAlerts(scene, chapterIndex),
    ...proseAlerts(scene, chapterIndex, content),
    ...mapAlerts(mapSummary, mapError),
    ...checkAlerts(latestCheck, {
      content,
      draftId,
      versionNumber,
      isDirty,
      checkError,
      checkLoading,
    }),
  ]

  return alerts.sort((left, right) => (
    SEVERITY_ORDER.indexOf(left.severity) - SEVERITY_ORDER.indexOf(right.severity)
  ))
}

export function summarizeSceneAlerts(alerts = []) {
  const counts = { high: 0, medium: 0, low: 0, info: 0 }
  for (const alert of alerts) {
    if (alert?.severity in counts) counts[alert.severity] += 1
  }
  const actionableCount = counts.high + counts.medium + counts.low
  const highestSeverity = SEVERITY_ORDER.find((severity) => counts[severity] > 0) || "info"
  return {
    counts,
    actionableCount,
    highestSeverity,
    hasStaleCheck: alerts.some((alert) => alert?.stale === true),
  }
}

export function sceneTextForChapter(scene, chapterIndex, content = "") {
  return sceneTextScope(scene, chapterIndex, content).text
}

function sceneTextScope(scene, chapterIndex, content = "") {
  const source = String(content || "")
  const chunks = (scene?.scene_chunks || []).filter((chunk) => (
    String(chunk?.chapter_index ?? chunk?.chapter_id ?? "") === String(chapterIndex ?? "")
  ))
  const ranges = chunks.map((chunk) => {
    const start = Number(chunk?.start_pos ?? chunk?.start_offset)
    const end = Number(chunk?.end_pos ?? chunk?.end_offset)
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null
    const safeStart = Math.max(0, start)
    const safeEnd = Math.min(source.length, end)
    return safeEnd > safeStart ? [safeStart, safeEnd] : null
  }).filter(Boolean)

  if (!chunks.length) return { text: source, available: true }
  if (!ranges.length) return { text: "", available: false }
  return {
    text: ranges.map(([start, end]) => source.slice(start, end)).join("\n"),
    available: true,
  }
}

function structureAlerts(scene, chapterIndex) {
  const alerts = []
  const structureMeta = scene?.structure_meta && typeof scene.structure_meta === "object"
    ? scene.structure_meta
    : {}
  const health = new Set([
    ...(Array.isArray(scene.health) ? scene.health : []),
    ...(Array.isArray(scene.health_flags) ? scene.health_flags : []),
  ])
  const addMissing = (field, label, severity) => {
    const status = semanticFieldStatus(scene, field)
    if (status === "not_applicable") return
    if (status === "uncertain") {
      alerts.push(alert(`structure-${field}`, severity, "结构", `Scene 的${label}仍待确认`))
      return
    }
    if (hasText(scene?.[field])) return
    alerts.push(alert(`structure-${field}`, severity, "结构", `Scene 尚未配置${label}`))
  }

  addMissing("goal", "目标", "medium")
  addMissing("core_conflict", "核心冲突", "low")
  addMissing("emotional_beat", "情绪节拍", "low")
  if (!hasText(scene?.pov_character_id) && !hasText(scene?.pov_character?.id)) {
    alerts.push(alert("structure-pov", "low", "结构", "Scene 尚未配置 POV 人物"))
  }
  if (
    scene?.needs_review === true ||
    structureMeta.needs_review === true ||
    health.has("unreviewed") ||
    health.has("needs_review")
  ) {
    alerts.push(alert("structure-review", "medium", "结构", "Scene 尚未完成人工复核"))
  }
  if (
    scene?.needs_organize === true ||
    structureMeta.needs_organize === true ||
    health.has("needs_organize")
  ) {
    alerts.push(alert("structure-organize", "medium", "结构", "Scene 已标记为待整理"))
  }
  if (!sceneMapsToChapter(scene, chapterIndex)) {
    alerts.push(alert("structure-chapter-map", "medium", "结构", "Scene 尚未映射到当前章节"))
  }
  return alerts
}

function proseAlerts(scene, chapterIndex, content) {
  const alerts = []
  const requiredPhrases = semanticFieldStatus(scene, "must_happen") == null
    ? splitRulePhrases(scene?.must_happen)
    : []
  const forbiddenPhrases = semanticFieldStatus(scene, "must_not_happen") == null
    ? splitRulePhrases(scene?.must_not_happen)
    : []
  if (!requiredPhrases.length && !forbiddenPhrases.length) return alerts

  const scope = sceneTextScope(scene, chapterIndex, content)
  if (!scope.available) {
    return [alert(
      "prose-scope-unavailable",
      "low",
      "正文",
      "当前 Scene 正文范围不可用，已跳过 must/must_not 字面检查",
    )]
  }
  const sceneText = normalizeForLiteralMatch(scope.text)

  for (const [index, phrase] of requiredPhrases.entries()) {
    if (!sceneText.includes(normalizeForLiteralMatch(phrase))) {
      alerts.push({
        ...alert(`prose-required-${index}`, "medium", "正文", `未检测到必须发生项「${phrase}」`),
        detail: "仅按当前 Scene 正文字面匹配，不代表剧情语义上一定缺失。",
      })
    }
  }
  for (const [index, phrase] of forbiddenPhrases.entries()) {
    if (sceneText.includes(normalizeForLiteralMatch(phrase))) {
      alerts.push({
        ...alert(`prose-forbidden-${index}`, "high", "正文", `检测到禁止发生项「${phrase}」`),
        detail: "仅按当前 Scene 正文字面匹配，请结合上下文人工确认。",
      })
    }
  }
  return alerts
}

function semanticFieldStatus(scene, field) {
  const meta = scene?.structure_meta
  if (!meta || typeof meta !== "object") return null
  const source = String(scene?.source || "")
  const origin = String(meta.semantic_origin || "")
  const trusted = source === "deep_import"
    || source === "manual_fusion"
    || ["phase1b_enrichment", "phase1c_synthesis", "author_reviewed_fusion"].includes(origin)
  if (!trusted) return null
  const statuses = meta.semantic_field_statuses && typeof meta.semantic_field_statuses === "object"
    ? meta.semantic_field_statuses
    : (meta.phase1b_field_statuses || {})
  const status = field === "core_conflict"
    ? (statuses[field] || meta.core_conflict_status)
    : statuses[field]
  return ["present", "not_applicable", "uncertain"].includes(status) ? status : null
}

function mapAlerts(mapSummary, mapError) {
  if (mapError) {
    return [alert("map-unavailable", "low", "地图", "地图风险摘要暂不可用")]
  }
  const alerts = []
  const entries = [
    ...(Array.isArray(mapSummary?.risks) ? mapSummary.risks : []),
    ...(Array.isArray(mapSummary?.warnings) ? mapSummary.warnings : []),
  ]
  const seen = new Set()
  for (const [index, entry] of entries.entries()) {
    const message = mapWarningMessage(entry)
    if (!message || seen.has(message)) continue
    seen.add(message)
    alerts.push(alert(
      `map-${entry?.code || index}`,
      entry?.level === "info" ? "low" : "medium",
      "地图",
      message,
    ))
  }
  return alerts
}

function checkAlerts(check, current) {
  if (current.checkError) {
    return [alert("check-unavailable", "low", "最近校验", String(current.checkError))]
  }
  if (current.checkLoading && !check) return []
  if (!check) {
    return [alert("check-missing", "info", "最近校验", "当前 Scene 尚无规则检查记录")]
  }

  const alerts = []
  const staleReason = checkStaleReason(check, current)
  if (staleReason) {
    alerts.push({
      ...alert("check-stale", "medium", "最近校验", staleReason),
      stale: true,
    })
  }

  const openItems = Array.isArray(check.items)
    ? check.items.filter((item) => (item?.status || "open") === "open")
    : []
  const summary = check.summary_json || {}
  const highCount = openItems.length
    ? openItems.filter((item) => item?.severity === "high").length
    : Number(summary.open_high_count || 0)
  const mediumCount = openItems.filter((item) => item?.severity === "medium").length
  const lowCount = openItems.filter((item) => item?.severity === "low").length

  if (highCount > 0) {
    alerts.push(alert("check-high", "high", "最近校验", `仍有 ${highCount} 项未处理高严重度问题`))
  }
  if (mediumCount > 0) {
    alerts.push(alert("check-medium", "medium", "最近校验", `仍有 ${mediumCount} 项未处理中严重度问题`))
  }
  if (lowCount > 0) {
    alerts.push(alert("check-low", "low", "最近校验", `仍有 ${lowCount} 项未处理低严重度提示`))
  }

  if (check.ai_review_status === "failed") {
    alerts.push(alert("check-ai-failed", "medium", "最近校验", "AI 深度校验失败，可在检查详情中重试"))
  } else if (check.ai_review_status === "running") {
    alerts.push(alert("check-ai-running", "info", "最近校验", "AI 深度校验仍在运行"))
  } else if (check.ai_review_status === "partial") {
    alerts.push(alert("check-ai-partial", "low", "最近校验", "AI 深度校验仅完成部分结果"))
  }

  if (!highCount && !mediumCount && !lowCount && !staleReason) {
    alerts.push(alert("check-clear", "info", "最近校验", "最近一次规则检查无未处理项"))
  }
  return alerts
}

function checkStaleReason(check, { content, draftId, versionNumber, isDirty }) {
  if (isDirty) return "正文已有未保存修改，最近校验已过期"
  const checkedDraftId = check?.draft_id ?? check?.scope?.draft_id ?? null
  const checkedVersionNumber = check?.version_number ?? check?.scope?.version_number ?? null
  if (draftId != null && checkedDraftId != null && String(checkedDraftId) !== String(draftId)) {
    return "最近校验对应其他工作稿，已过期"
  }
  if (draftId == null && checkedDraftId != null) {
    return "最近校验绑定了已保存工作稿，当前正文无法核对"
  }
  if (draftId != null && checkedDraftId == null) {
    return "最近校验未记录正文版本，建议重新运行规则检查"
  }
  if (
    versionNumber != null &&
    checkedVersionNumber != null &&
    Number(checkedVersionNumber) !== Number(versionNumber)
  ) {
    return `最近校验基于 v${checkedVersionNumber}，当前为 v${versionNumber}`
  }
  if (versionNumber == null && checkedVersionNumber != null) {
    return "最近校验绑定了已保存版本，当前正文无法核对"
  }
  if (versionNumber != null && checkedVersionNumber == null) {
    return "最近校验未记录正文版本，建议重新运行规则检查"
  }
  const currentCodePoints = Array.from(String(content || ""))
  const rawCharCount = check?.scope?.content_char_count
  const checkedCharCount = rawCharCount == null ? Number.NaN : Number(rawCharCount)
  if (Number.isFinite(checkedCharCount) && checkedCharCount !== currentCodePoints.length) {
    return "当前正文长度已变化，最近校验已过期"
  }
  if (
    typeof check?.scope?.content_excerpt === "string" &&
    check.scope.content_excerpt !== currentCodePoints.slice(0, 4000).join("")
  ) {
    return "当前正文内容已变化，最近校验已过期"
  }
  if (
    draftId &&
    check?.scope?.content_char_count == null &&
    typeof check?.scope?.content_excerpt !== "string"
  ) {
    return "最近校验未记录正文内容快照，建议重新运行规则检查"
  }
  return null
}

function sceneMapsToChapter(scene, chapterIndex) {
  const target = String(chapterIndex ?? "")
  if (!target) return true
  if ((scene?.chapter_ids || []).some((id) => String(id) === target)) return true
  return (scene?.scene_chunks || []).some((chunk) => (
    String(chunk?.chapter_index ?? chunk?.chapter_id ?? "") === target
  ))
}

function splitRulePhrases(value) {
  if (!hasText(value)) return []
  return String(value).split(/[；;，,\n。]+/).map((part) => part.trim()).filter(Boolean)
}

function normalizeForLiteralMatch(value) {
  return String(value || "").replace(/\s+/g, "").toLocaleLowerCase()
}

function mapWarningMessage(value) {
  if (typeof value === "string") return value
  if (!value || typeof value !== "object") return ""
  if (value.message) return String(value.message)
  const messages = {
    scene_without_map_context: "当前 Scene 暂无地图上下文",
    scene_without_location: "当前 Scene 暂无主地点",
    character_cross_map: "人物上一场在其他地图，需确认移动合理性",
  }
  return messages[value.code] || "已有地图空间连续性风险记录"
}

function alert(id, severity, source, message) {
  return { id, severity, source, message }
}

function hasText(value) {
  return value != null && String(value).trim().length > 0
}
