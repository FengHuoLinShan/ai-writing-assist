/**
 * api/collaboration.js — api.collaboration 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const collaboration = {
    understanding: (novelId) => request(withQuery("/collaboration/understanding", { novel_id: novelId })),
    understandingHistory: (novelId, id) => request(withQuery(`/collaboration/understanding/${encodeURIComponent(id)}/history`, { novel_id: novelId })),
    correctUnderstanding: (novelId, id, body) => post(withQuery(`/collaboration/understanding/${encodeURIComponent(id)}`, { novel_id: novelId }), body),
    resources: (novelId, params = {}) => request(withQuery("/collaboration/resources", { novel_id: novelId, ...params }), { cache: "no-store" }),
    importScope: (novelId, body) => post(withQuery("/collaboration/import-scope", { novel_id: novelId }), body),
    updateGrant: (novelId, id, body) => request(withQuery(`/collaboration/cases/${encodeURIComponent(id)}/grant`, { novel_id: novelId }), { method: "PUT", body: JSON.stringify(body) }),
    resume: (novelId, id) => post(withQuery(`/collaboration/runs/${encodeURIComponent(id)}/resume`, { novel_id: novelId })),
    rebase: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/rebase`, { novel_id: novelId }), body),
    revert: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/revert`, { novel_id: novelId }), body),
    capabilities: (novelId) => request(withQuery("/collaboration/capabilities", { novel_id: novelId }), { cache: "no-store" }),
    cases: (novelId) => request(withQuery("/collaboration/cases", { novel_id: novelId }), { cache: "no-store" }),
    createCase: (novelId, body) => post(withQuery("/collaboration/cases", { novel_id: novelId }), body),
    getCase: (novelId, id) => request(withQuery(`/collaboration/cases/${encodeURIComponent(id)}`, { novel_id: novelId }), { cache: "no-store" }),
    runs: (novelId, id) => request(withQuery(`/collaboration/cases/${encodeURIComponent(id)}/runs`, { novel_id: novelId }), { cache: "no-store" }),
    updateGoal: (novelId, id, body) => request(withQuery(`/collaboration/cases/${encodeURIComponent(id)}/goal`, { novel_id: novelId }), { method: "PUT", body: JSON.stringify(body) }),
    submit: (novelId, id, body) => post(withQuery(`/collaboration/cases/${encodeURIComponent(id)}/runs`, { novel_id: novelId }), body),
    run: (novelId, id) => request(withQuery(`/collaboration/runs/${encodeURIComponent(id)}`, { novel_id: novelId }), { cache: "no-store" }),
    stop: (novelId, id) => post(withQuery(`/collaboration/runs/${encodeURIComponent(id)}/stop`, { novel_id: novelId })),
    workspaces: (novelId, id) => request(withQuery(`/collaboration/cases/${encodeURIComponent(id)}/workspaces`, { novel_id: novelId }), { cache: "no-store" }),
    diff: (novelId, id) => request(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/diff`, { novel_id: novelId }), { cache: "no-store" }),
    test: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/test`, { novel_id: novelId }), body),
    seal: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/seal`, { novel_id: novelId }), body),
    merge: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/merge`, { novel_id: novelId }), body),
    fork: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/fork`, { novel_id: novelId }), body),
    edit: (novelId, id, body) => post(withQuery(`/collaboration/workspaces/${encodeURIComponent(id)}/revisions`, { novel_id: novelId }), body),
};
