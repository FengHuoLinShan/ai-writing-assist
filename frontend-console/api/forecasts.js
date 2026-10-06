/**
 * api/forecasts.js — api.forecasts 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const forecasts = {
    activity: (novelId, body) => post(withQuery("/assistant/forecasts/activity", { novel_id: novelId }), body),
    resume: (novelId, id) => post(withQuery(`/assistant/forecasts/runs/${id}/resume`, { novel_id: novelId })),
    capabilities: (novelId) => request(withQuery("/assistant/forecasts/capabilities", { novel_id: novelId }), { cache: "no-store" }),
    policy: (novelId) => request(withQuery("/assistant/forecasts/policy", { novel_id: novelId }), { cache: "no-store" }),
    savePolicy: (novelId, body) => request(withQuery("/assistant/forecasts/policy", { novel_id: novelId }), { method: "PUT", body: JSON.stringify(body) }),
    feed: (novelId, body) => post(withQuery("/assistant/forecasts/feed", { novel_id: novelId }), body),
    evaluate: (novelId, body) => post(withQuery("/assistant/forecasts/evaluate", { novel_id: novelId }), body),
    run: (novelId, runId) => request(withQuery(`/assistant/forecasts/runs/${encodeURIComponent(runId)}`, { novel_id: novelId }), { cache: "no-store" }),
    cancel: (novelId, runId) => post(withQuery(`/assistant/forecasts/runs/${encodeURIComponent(runId)}/cancel`, { novel_id: novelId })),
    decide: (novelId, id, body) => post(withQuery(`/assistant/forecasts/candidates/${encodeURIComponent(id)}/decision`, { novel_id: novelId }), body),
    prepare: (novelId, id, body) => post(withQuery(`/assistant/forecasts/candidates/${encodeURIComponent(id)}/prepare`, { novel_id: novelId }), body),
    operation: (novelId, id) => request(withQuery(`/assistant/forecasts/operations/${encodeURIComponent(id)}`, { novel_id: novelId }), { cache: "no-store" }),
    recheck: (novelId, id, operationId) => post(withQuery(`/assistant/forecasts/candidates/${encodeURIComponent(id)}/recheck`, { novel_id: novelId }), { operation_id: operationId }),
};
