/**
 * api/evolution.js — api.evolution 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const evolution = {
    status: (novelId) => request(withQuery("/evolution/reading", { novel_id: novelId }), { cache: "no-store" }),
    targets: (novelId, runKey, options) => request(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/targets`, { novel_id: novelId, ...options }), { cache: "no-store" }),
    proposals: (novelId, runKey, offset = 0) => request(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/proposals`, { novel_id: novelId, offset }), { cache: "no-store" }),
    switchEngine: (novelId, body) => post(withQuery("/evolution/engine", { novel_id: novelId }), body),
    preview: (novelId, body) => post(withQuery("/evolution/reading/preview", { novel_id: novelId }), body),
    start: (novelId, body) => post(withQuery("/evolution/reading", { novel_id: novelId }), body),
    resume: (novelId, runKey) => post(withQuery(`/evolution/reading/${encodeURIComponent(runKey)}/resume`, { novel_id: novelId })),
};
