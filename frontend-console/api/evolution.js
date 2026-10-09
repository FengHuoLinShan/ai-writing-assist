/**
 * api/evolution.js — api.evolution 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 *
 * P2-C C4：改稿失效后的重算封装。端点为 C3 落地的真实契约（归属 writing
 * 编排，backend/modules/writing/api.py 的 /writing/recompute*）：预览零正史
 * 写入；执行=adopt（重验来源指纹，漂移 409 recompute_source_drift 并保留
 * 当前稿）。取消即不调用 adopt（预览无服务端状态，零正史副作用）。
 *
 * F7 之后待重算状态与已完成回执都由服务端留档、可跨会话回读：
 * `pendingInvalidations` 查尚未消解的失效提示（重算覆盖该章后自动消解），
 * `recomputeReceipts` 查已完成回执；两者都是只读 GET，本地会话记录只作
 * 合并与即时补充（见 invalidationModel.js 的口径注记）。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const evolution = {
    panorama: (novelId, sceneId) => request(withQuery("/evolution/panorama", { novel_id: novelId, scene_id: sceneId }), { cache: "no-store" }),
    ledger: (novelId, options) => request(withQuery("/evolution/ledger", { novel_id: novelId, ...options }), { cache: "no-store" }),
    ledgerEntry: (novelId, entryId, revision) => request(withQuery(`/evolution/ledger/${encodeURIComponent(entryId)}`, { novel_id: novelId, revision }), { cache: "no-store" }),
    ledgerEvidence: (novelId, entryId, index, revision) => request(withQuery(`/evolution/ledger/${encodeURIComponent(entryId)}/evidence/${index}`, { novel_id: novelId, revision }), { cache: "no-store" }),
    ledgerDecision: (novelId, entryId, body) => post(withQuery(`/evolution/ledger/${encodeURIComponent(entryId)}/decision`, { novel_id: novelId }), body),
    status: (novelId) => request(withQuery("/evolution/reading", { novel_id: novelId }), { cache: "no-store" }),
    targets: (novelId, runKey, options) => request(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/targets`, { novel_id: novelId, ...options }), { cache: "no-store" }),
    proposals: (novelId, runKey, offset = 0) => request(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/proposals`, { novel_id: novelId, offset }), { cache: "no-store" }),
    switchEngine: (novelId, body) => post(withQuery("/evolution/engine", { novel_id: novelId }), body),
    preview: (novelId, body) => post(withQuery("/evolution/reading/preview", { novel_id: novelId }), body),
    start: (novelId, body) => post(withQuery("/evolution/reading", { novel_id: novelId }), body),
    resume: (novelId, runKey) => post(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/resume`, { novel_id: novelId })),
    // 重算预览：POST /writing/recompute（WritingRecomputeRequest，extra=forbid：
    // 仅 novel_id/operation_id/scope/targets/baseline_receipt_digest）。
    recomputePreview: (novelId, payload) => post(withQuery("/writing/recompute", { novel_id: novelId }), payload),
    // 重算执行（adopt）：POST /writing/recompute/{operation_id}/adopt，body 另带
    // confirmed=true 与预览返回的 expected_source_digest（来源漂移 → 409）。
    recomputeExecute: (novelId, operationId, payload) => post(
      withQuery(`/writing/recompute/${encodeURIComponent(operationId)}/adopt`, { novel_id: novelId }),
      payload,
    ),
    // 尚未消解的失效提示：GET /writing/invalidations（重算覆盖该章后消解）。
    // withQuery 会跳过 null/空值，chapterIndex 为空时自然不带该 query。
    pendingInvalidations: (novelId, { chapterIndex = null, limit = null } = {}) => request(
      withQuery("/writing/invalidations", {
        novel_id: novelId,
        chapter_index: Number.isInteger(chapterIndex) ? chapterIndex : null,
        limit: Number.isInteger(limit) ? limit : null,
      }),
      { cache: "no-store" },
    ),
    // 已完成重算回执：GET /writing/recompute/receipts（倒序，服务端留档可跨会话查）。
    recomputeReceipts: (novelId, { limit = null } = {}) => request(
      withQuery("/writing/recompute/receipts", {
        novel_id: novelId,
        limit: Number.isInteger(limit) ? limit : null,
      }),
      { cache: "no-store" },
    ),
};
