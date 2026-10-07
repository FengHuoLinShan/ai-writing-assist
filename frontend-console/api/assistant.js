/**
 * api/assistant.js — api.assistant 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const assistant = {
    editorialPolicy: (novelId) => request(withQuery("/assistant/editorial/policy", { novel_id: novelId }), { cache: "no-store" }),
    saveEditorialPolicy: (novelId, policy, expectedGeneration) => request("/assistant/editorial/policy", { method: "PUT", body: JSON.stringify({ novel_id: novelId, policy, expected_generation: expectedGeneration }) }),
    editorialReviews: (novelId) => request(withQuery("/assistant/editorial/reviews", { novel_id: novelId }), { cache: "no-store" }),
    editorialReview: (novelId, id) => request(withQuery(`/assistant/editorial/reviews/${encodeURIComponent(id)}`, { novel_id: novelId }), { cache: "no-store" }),
    submitEditorialReview: (body) => post("/assistant/editorial/reviews", body),
    resumeEditorialReview: (novelId, id) => post(withQuery(`/assistant/editorial/reviews/${encodeURIComponent(id)}/resume`, { novel_id: novelId })),
    stopEditorialReview: (novelId, id) => post(withQuery(`/assistant/editorial/reviews/${encodeURIComponent(id)}/stop`, { novel_id: novelId })),
    editorialIssues: (novelId) => request(withQuery("/assistant/editorial/issues", { novel_id: novelId }), { cache: "no-store" }),
    decideEditorialIssue: (id, body) => request(`/assistant/editorial/issues/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) }),
    recheckEditorialIssue: (id, body) => post(`/assistant/editorial/issues/${encodeURIComponent(id)}/recheck`, body),
    capabilities: (novelId) => request(withQuery("/assistant/capabilities", { novel_id: novelId }), { cache: "no-store" }),
    sessions: (novelId, params = {}) => request(withQuery("/assistant/sessions", { ...params, novel_id: novelId }), { cache: "no-store" }),
    createSession: (novelId, title = "项目助手") => post("/assistant/sessions", { novel_id: novelId, title }),
    session: (novelId, sessionId) => request(withQuery(`/assistant/sessions/${sessionId}`, { novel_id: novelId }), { cache: "no-store" }),
    messages: (novelId, sessionId, params = {}) => request(withQuery(`/assistant/sessions/${sessionId}/messages`, { ...params, novel_id: novelId }), { cache: "no-store" }),
    submit: (sessionId, payload) => post(`/assistant/sessions/${sessionId}/turns`, payload),
    submitTeam: (sessionId, payload) => post(`/assistant/sessions/${sessionId}/team-runs`, payload),
    selectPlan: (runId, payload) => post(`/assistant/runs/${runId}/select-plan`, payload),
    collaboration: (novelId, runId) => request(withQuery(`/assistant/runs/${runId}/collaboration`, { novel_id: novelId }), { cache: "no-store" }),
    run: (novelId, runId) => request(withQuery(`/assistant/runs/${runId}`, { novel_id: novelId }), { cache: "no-store" }),
    stop: (novelId, runId) => post(withQuery(`/assistant/runs/${runId}/stop`, { novel_id: novelId })),
    resume: (runId, payload) => post(`/assistant/runs/${runId}/resume`, payload),
    decide: (batchId, payload) => post(`/assistant/batches/${batchId}/decide`, payload),
    recheck: (batchId, payload) => post(`/assistant/batches/${batchId}/recheck`, payload),
    carePolicy: (novelId) => request(withQuery("/assistant/policy", { novel_id: novelId }), { cache: "no-store" }),
    saveCarePolicy: (novelId, policy) => request("/assistant/policy", { method: "PUT", body: JSON.stringify({ novel_id: novelId, policy }) }),
    careNotices: (novelId) => request(withQuery("/assistant/notices", { novel_id: novelId }), { cache: "no-store" }),
    recheckCareNotice: (novelId, noticeId, operationId) => post(withQuery(`/assistant/notices/${encodeURIComponent(noticeId)}/recheck`, { novel_id: novelId }), { operation_id: operationId }),
    decideCareNotice: (novelId, noticeId, disposition) => post(`/assistant/notices/${encodeURIComponent(noticeId)}/decide`, { novel_id: novelId, ...disposition }),
};
