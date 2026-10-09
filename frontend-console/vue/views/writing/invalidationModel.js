/**
 * invalidationModel.js — P2-C C4 失效提示与重算入口的纯模型层。
 *
 * 输入形态对齐 C1 契约（backend/modules/evolution/consumption.py 的
 * `receipt_public_view`）：保存响应可选 `invalidation` 字段
 * `{affected: [{consumer, scene_id, scene_index, dimension, reason, basis}],
 *   unknown_scope, receipt_id, invalidated, unsupported, coverage_note,
 *   recompute_options, diagnostics, nothing_to_do}`。重算请求/响应形态对齐
 * C3 落地的真实端点（backend/modules/writing/api.py /writing/recompute*，
 * schemas 的 WritingRecompute* 家族，extra=forbid）。本文件只做作者语言
 * 投影与请求组装，不发请求、不碰 DOM。
 *
 * 回执历史口径：服务端已经留档可查（`GET /writing/recompute/receipts`），
 * 刷新或离开再回来都能看到已完成回执；本模块的本地列表仍是**会话内即时
 * 记录**（同页会话、按 novel 隔离、按 operation_id 去重），用于 adopt 成功
 * 后立刻补上服务端尚未返回的那一条，两者由 mergeServerRecomputeReceipts
 * 合并后同源展示（同一 operation_id 以服务端为准）。同一 operation_id 的重放
 * 只回放回执、不产生新的域写入。
 */

const CONSUMER_LABELS = Object.freeze({
  evidence_chapter_index: "章节证据索引",
  canonical_chapter_index: "正史章节索引",
  interaction_source_cache: "对话来源缓存",
  assistant_suggestion_validity: "助手建议有效性",
  evolution_runs: "演化理解任务",
  story_state: "场景派生状态",
  story_scene_projections: "场景派生投影",
  scene_event_order: "场景事件顺序",
  story_scene_checkpoint: "场景状态存档",
  scene_lens: "场景证据镜头",
  prose_generation: "正文重生成",
  world_knowledge: "世界书理解",
  map_atlas: "地图集",
})

const REASON_LABELS = Object.freeze({
  anchored_chapter_edited: "依赖的这一章被修改",
  offset_window_hit: "改动落在它依赖的段落里",
  offset_window_miss: "与这次修改无关",
  content_mode_mismatch: "它读取的是另一版本的内容",
  conservative_expansion_unregistered: "依赖未登记，按保守方式标记",
  unregistered_consumer: "这类内容尚未接入依赖登记",
})

const UNKNOWN_SCOPE_NOTE = "部分影响范围待核实：系统按保守方式标记了更多可能受影响的内容，重算前会再核对。"

export const RECOMPUTE_SCOPES = Object.freeze([
  Object.freeze({
    kind: "reload_evidence",
    label: "重读证据",
    costNote: "成本低：只重新读取证据和章节索引，不调用模型，也不改任何内容。",
    effectNote: "适合先让资料对上当前稿；场景状态与正文都不会变。",
  }),
  Object.freeze({
    kind: "rebuild_derived_state",
    label: "重建派生状态",
    costNote: "成本中等：重算场景的状态存档与投影，可能触发已登记的检查任务。",
    effectNote: "旧结果与确认历史都会保留，可随时回看。",
  }),
  Object.freeze({
    kind: "regenerate_prose",
    label: "重生成正文",
    costNote: "成本高：调用模型重写正文，消耗生成额度，只在你的明确选择下执行。",
    effectNote: "会产生新草稿版本，须经你确认采用；旧稿与人工修改保留。",
  }),
])

const RECOMPUTE_SCOPE_BY_KIND = Object.freeze(
  Object.fromEntries(RECOMPUTE_SCOPES.map((scope) => [scope.kind, scope])),
)

export function recomputeScopeChoice(kind) {
  return RECOMPUTE_SCOPE_BY_KIND[kind] || null
}

function consumerLabel(consumer) {
  return CONSUMER_LABELS[consumer] || "相关内容"
}

function scopeLabel(entry, fallbackChapterIndex) {
  if (entry.scene_index != null) return `场景 ${entry.scene_index}`
  if (entry.dimension) return `${consumerLabel(entry.consumer)} · ${entry.dimension}`
  if (entry.chapter_index != null) return `第 ${entry.chapter_index} 章`
  if (fallbackChapterIndex != null) return `第 ${fallbackChapterIndex} 章`
  return "本章相关内容"
}

function normalizeEntry(entry, fallbackChapterIndex) {
  const consumer = String(entry?.consumer || "")
  return {
    key: `${consumer}:${entry?.scene_index ?? entry?.chapter_index ?? ""}:${entry?.dimension ?? ""}:${entry?.reason ?? ""}`,
    consumer,
    consumerLabel: consumerLabel(consumer),
    scopeLabel: scopeLabel(entry, fallbackChapterIndex),
    reason: String(entry?.reason || ""),
    reasonLabel: REASON_LABELS[entry?.reason] || "依赖这次修改",
    basis: entry?.basis === "unknown" ? "unknown" : "known",
    note: typeof entry?.note === "string" ? entry.note : "",
  }
}

/**
 * 保存响应 `invalidation` 视图 → 作者语言提示模型。
 *
 * 零打扰口径：字段缺失、非对象、`nothing_to_do` 或完全没有任何
 * 失效信号（无 affected、无 unknown_scope、无 invalidated、无
 * unsupported）时返回 `null`，编辑器不显示任何内容。
 */
export function normalizeInvalidationNotice(raw, { chapterIndex = null } = {}) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  if (raw.nothing_to_do === true) return null
  const affected = Array.isArray(raw.affected) ? raw.affected : []
  const invalidated = Array.isArray(raw.invalidated) ? raw.invalidated : []
  const unsupported = Array.isArray(raw.unsupported) ? raw.unsupported : []
  const hasUnknownScope = raw.unknown_scope === true
  if (!affected.length && !hasUnknownScope && !invalidated.length && !unsupported.length) return null
  const editedChapterIndex = raw.chapter_index ?? chapterIndex
  const entries = affected
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => normalizeEntry(entry, editedChapterIndex))
  const sceneIndexes = [...new Set(
    affected
      .map((entry) => (Number.isInteger(entry?.scene_index) ? entry.scene_index : null))
      .filter((value) => value != null),
  )].sort((a, b) => a - b)
  const options = (Array.isArray(raw.recompute_options) && raw.recompute_options.length
    ? raw.recompute_options
    : RECOMPUTE_SCOPES.map((scope) => ({ kind: scope.kind }))
  )
    .map((option) => option?.kind)
    .filter((kind) => RECOMPUTE_SCOPE_BY_KIND[kind])
  const headlineParts = []
  if (editedChapterIndex != null) headlineParts.push(`这次修改让第 ${editedChapterIndex} 章起的场景状态需要更新`)
  else headlineParts.push("这次修改让部分场景状态需要更新")
  if (sceneIndexes.length) headlineParts.push(`（涉及场景 ${sceneIndexes.join("、")}）`)
  return {
    receiptId: typeof raw.receipt_id === "string" && raw.receipt_id ? raw.receipt_id : null,
    chapterIndex: editedChapterIndex != null ? Number(editedChapterIndex) : null,
    headline: `${headlineParts.join("")}。`,
    hasUnknownScope,
    unknownScopeNote: hasUnknownScope ? UNKNOWN_SCOPE_NOTE : "",
    entries,
    invalidatedLabels: invalidated.map((item) => (
      typeof item?.label === "string" && item.label ? item.label : consumerLabel(item?.consumer)
    )),
    unsupportedLabels: unsupported.map((item) => consumerLabel(item?.consumer)),
    coverageNote: typeof raw.coverage_note === "string" ? raw.coverage_note : "",
    recomputeOptions: options,
    sceneIndexes,
    earliestSceneIndex: Number.isInteger(raw?.diagnostics?.earliest_affected_scene_index)
      ? raw.diagnostics.earliest_affected_scene_index
      : null,
  }
}

/**
 * 组装重算请求基础体（对齐 WritingRecomputeRequest，extra=forbid：
 * 仅 novel_id/operation_id/scope/targets/baseline_receipt_digest，
 * **不含** mode/confirmed）。`regenerate_prose` 必须锚定章。
 */
export function recomputeRequestPayload({
  novelId,
  scope,
  notice,
  operationId,
}) {
  const choice = RECOMPUTE_SCOPE_BY_KIND[scope]
  if (!novelId || !choice || !notice || !operationId) return null
  const chapterIndex = notice.chapterIndex
  let targets
  if (scope === "rebuild_derived_state" && Array.isArray(notice.sceneIndexes) && notice.sceneIndexes.length) {
    targets = notice.sceneIndexes.map((sceneIndex) => ({ scene_index: sceneIndex }))
  } else {
    if (chapterIndex == null) return null
    targets = [{ chapter_index: chapterIndex }]
  }
  if (!targets.length) return null
  return {
    novel_id: novelId,
    operation_id: operationId,
    scope,
    targets,
    baseline_receipt_digest: notice.receiptId || null,
  }
}

/**
 * 组装执行（adopt）请求体：预览的同一操作内容 + 作者确认 + 预览返回的
 * 来源指纹（服务端重验，漂移 409 recompute_source_drift 并保留当前稿）。
 */
export function recomputeAdoptPayload({ novelId, scope, notice, operationId, expectedSourceDigest }) {
  const base = recomputeRequestPayload({ novelId, scope, notice, operationId })
  if (!base) return null
  return {
    ...base,
    confirmed: true,
    expected_source_digest: typeof expectedSourceDigest === "string" && expectedSourceDigest
      ? expectedSourceDigest
      : null,
  }
}

function targetAnchorLabel(target) {
  if (Number.isInteger(target?.scene_index)) return `场景 ${target.scene_index}`
  if (Number.isInteger(target?.chapter_index)) return `第 ${target.chapter_index} 章`
  return null
}

function sourceChapters(sourceState) {
  const chapters = sourceState?.chapters && typeof sourceState.chapters === "object"
    ? sourceState.chapters
    : {}
  const mapped = {}
  for (const [key, value] of Object.entries(chapters)) {
    if (!value || typeof value !== "object") continue
    mapped[key] = {
      version: Number.isInteger(value.version_number) ? value.version_number : null,
      fingerprint: typeof value.content_hash === "string" ? value.content_hash : "",
    }
  }
  return mapped
}

/** 预览响应（WritingRecomputePreviewResponse）→ 只读展示模型（零正史写入）。 */
export function normalizeRecomputePreview(raw, { scope } = {}) {
  if (!raw || typeof raw !== "object") return null
  const kind = raw.scope || scope
  const choice = RECOMPUTE_SCOPE_BY_KIND[kind]
  if (!choice) return null
  const targets = (Array.isArray(raw.targets) ? raw.targets : [])
    .map(targetAnchorLabel)
    .filter(Boolean)
  const actions = (Array.isArray(raw.actions) ? raw.actions : [])
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({
      key: `${item.action}:${item.scene_index ?? item.chapter_index ?? index}`,
      detail: typeof item.detail === "string" ? item.detail : "",
      anchorLabel: targetAnchorLabel(item) || "",
    }))
    .filter((item) => item.detail)
  return {
    scope: kind,
    label: choice.label,
    costNote: typeof raw.cost === "string" && raw.cost ? raw.cost : choice.costNote,
    effectNote: typeof raw.write_effect === "string" && raw.write_effect
      ? raw.write_effect
      : choice.effectNote,
    covers: (Array.isArray(raw.covers) ? raw.covers : []).map(consumerLabel),
    executable: raw.executable !== false,
    actions,
    targets,
    sourceDigest: typeof raw.source_digest === "string" ? raw.source_digest : null,
    sourceChapters: sourceChapters(raw.source_state),
  }
}

/** 执行回执（WritingRecomputeOutcomeResponse）→ 作者语言结果。 */
export function normalizeRecomputeOutcome(raw) {
  if (!raw || typeof raw !== "object") return null
  const choice = RECOMPUTE_SCOPE_BY_KIND[raw.scope]
  const results = raw.results && typeof raw.results === "object" ? raw.results : {}
  return {
    operationId: typeof raw.operation_id === "string" ? raw.operation_id : "",
    scope: raw.scope || "",
    label: choice ? choice.label : "重算",
    domainWritePerformed: raw.domain_write_performed !== false,
    handledCount: Object.keys(results).length,
  }
}

// ============================================================
// 本地会话回执记录（口径见文件头注记：服务端留档可查，本地只补 adopt 刚
// 完成、尚未回读的那一条；同一 operation_id 以服务端为准）
// ============================================================

const RECOMPUTE_RECEIPT_LIMIT = 20

const sessionRecomputeReceipts = []

export function rememberRecomputeReceipt(novelId, outcome, { at = null } = {}) {
  if (!novelId || !outcome?.operationId) return
  if (sessionRecomputeReceipts.some((item) => (
    item.novelId === novelId && item.operationId === outcome.operationId
  ))) return
  sessionRecomputeReceipts.unshift({
    novelId,
    operationId: outcome.operationId,
    label: outcome.label,
    scope: outcome.scope,
    domainWritePerformed: outcome.domainWritePerformed,
    handledCount: outcome.handledCount,
    rememberedAt: at || new Date().toISOString(),
  })
  if (sessionRecomputeReceipts.length > RECOMPUTE_RECEIPT_LIMIT) {
    sessionRecomputeReceipts.length = RECOMPUTE_RECEIPT_LIMIT
  }
}

/** 服务端回执（`WritingRecomputeReceiptItem`）→ 本地同形记录。 */
function serverReceiptRecord(item) {
  const operationId = typeof item?.operation_id === "string" ? item.operation_id : ""
  if (!operationId) return null
  const choice = recomputeScopeChoice(item?.scope)
  const handledCount = Number.isInteger(item?.handled_count) ? item.handled_count : 0
  return {
    operationId,
    label: choice ? choice.label : "重算",
    scope: typeof item?.scope === "string" ? item.scope : "",
    domainWritePerformed: true,
    handledCount,
    rememberedAt: typeof item?.completed_at === "string" && item.completed_at
      ? item.completed_at
      : null,
    source: "server",
  }
}

function sortReceiptsByRecency() {
  // 无时间戳（服务端未记完成时间）排在最后：它们是更早/无时间可依的记录。
  sessionRecomputeReceipts.sort((left, right) => {
    const leftTime = left.rememberedAt || ""
    const rightTime = right.rememberedAt || ""
    if (leftTime === rightTime) return 0
    if (!leftTime) return 1
    if (!rightTime) return -1
    return leftTime < rightTime ? 1 : -1
  })
}

/**
 * 把服务端回执并入本地列表（同一 operation_id 服务端为准）。
 *
 * 合并而非替换：本地可能还留着服务端尚未返回的最新一条（adopt 刚刚成功）。
 * 不入列的脏数据直接丢弃，返回并入条数便于调用方决定是否刷新展示。
 */
export function mergeServerRecomputeReceipts(novelId, rawItems) {
  if (!novelId || !Array.isArray(rawItems)) return 0
  const incoming = rawItems
    .map(serverReceiptRecord)
    .filter(Boolean)
  if (!incoming.length) return 0
  for (const item of incoming) {
    const existingIndex = sessionRecomputeReceipts.findIndex((record) => (
      record.novelId === novelId && record.operationId === item.operationId
    ))
    const record = { novelId, ...item }
    // 服务端为主：同一 operation_id 用它覆盖本地同名的即时记录（时间以服务端为准）
    if (existingIndex >= 0) sessionRecomputeReceipts[existingIndex] = record
    else sessionRecomputeReceipts.push(record)
  }
  sortReceiptsByRecency()
  if (sessionRecomputeReceipts.length > RECOMPUTE_RECEIPT_LIMIT) {
    sessionRecomputeReceipts.length = RECOMPUTE_RECEIPT_LIMIT
  }
  return incoming.length
}

export function listRecomputeReceipts(novelId) {
  return sessionRecomputeReceipts
    .filter((item) => item.novelId === novelId)
    .map((item) => ({ ...item, key: item.operationId }))
}

export function clearRecomputeReceiptsForTests() {
  sessionRecomputeReceipts.length = 0
}

/**
 * adopt 冲突分类：409 + error 码（服务端 DomainError 响应体
 * `{error, detail, message, context}`）。`recompute_source_drift`（来源漂移，
 * 保留当前稿，context 带 current 各章版本/指纹）与
 * `recompute_scope_unsupported`（regenerate_prose 不可经本编排执行）分开；
 * SOURCE_STALE/baseline_drift 兼容保留。
 */
export function recomputeConflictKind(error) {
  if (!error || Number(error.status) !== 409) return null
  const code = typeof error.body?.error === "string" ? error.body.error : error.code
  if (code === "recompute_source_drift" || code === "SOURCE_STALE" || code === "baseline_drift" || code === "recompute_baseline_stale") {
    return "source_drift"
  }
  if (code === "recompute_scope_unsupported") return "scope_unsupported"
  return null
}

/**
 * 漂移 409 的可比较数据：预览时来源状态（source_state.chapters）vs 服务端
 * context.current（各章 draft 版本/指纹）。逐章给出「预览时第 a 版 → 当前
 * 第 b 版」；无预览状态时退化为当前版本清单。
 */
export function normalizeRecomputeDriftContext(error, { previewChapters = {} } = {}) {
  const context = error?.body?.context && typeof error.body.context === "object"
    ? error.body.context
    : {}
  const current = sourceChapters({ chapters: context.current })
  const chapterIndexes = [...new Set([
    ...Object.keys(previewChapters).map(Number),
    ...Object.keys(current).map(Number),
  ])].filter(Number.isInteger).sort((a, b) => a - b)
  const rows = chapterIndexes.map((chapterIndex) => {
    const key = String(chapterIndex)
    const before = previewChapters[key] || null
    const after = current[key] || null
    return {
      chapterIndex,
      beforeVersion: before?.version ?? null,
      afterVersion: after?.version ?? null,
      unchanged: Boolean(
        before && after
          && before.version === after.version
          && before.fingerprint === after.fingerprint,
      ),
    }
  })
  return {
    keepCurrentDraft: context.keep_current_draft === true,
    rows,
  }
}

export function driftRowLabel(row) {
  const base = `第 ${row.chapterIndex} 章`
  if (row.beforeVersion == null && row.afterVersion == null) return `${base}：版本信息暂缺`
  if (row.beforeVersion == null) return `${base}：当前为第 ${row.afterVersion} 版工作稿`
  if (row.afterVersion == null) return `${base}：预览时为第 ${row.beforeVersion} 版工作稿，当前版本暂缺`
  if (row.unchanged) return `${base}：版本未变（第 ${row.afterVersion} 版）`
  return `${base}：预览时第 ${row.beforeVersion} 版 → 当前第 ${row.afterVersion} 版`
}

/** 重算幂等键：randomUUID 优先，无 Web Crypto 时失败关闭（不降级为弱随机）。 */
export function recomputeOperationKey() {
  let token
  if (typeof globalThis.crypto?.randomUUID === "function") {
    token = globalThis.crypto.randomUUID()
  } else {
    if (typeof globalThis.crypto?.getRandomValues !== "function") {
      throw new Error("当前浏览器无法安全生成操作标识，请更换浏览器后重试")
    }
    const bytes = new Uint8Array(16)
    globalThis.crypto.getRandomValues(bytes)
    token = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")
  }
  return `recompute-${token}`.slice(0, 120)
}
