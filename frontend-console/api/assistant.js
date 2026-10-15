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
    reviseEditorialIssues: (body) => post("/assistant/editorial/issues/revise", body),
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
    unifiedNotices: (novelId, { sceneId = null, chapterIndex = null, signal } = {}) => request(
      withQuery("/assistant/unified-notices", {
        novel_id: novelId,
        scene_id: sceneId,
        chapter_index: Number.isInteger(chapterIndex) ? chapterIndex : null,
      }),
      { cache: "no-store", signal },
    ),
    setUnifiedNoticeDisposition: (body) => post("/assistant/unified-notices/dispositions", body),
    setUnifiedNoticeCategoryMute: (novelId, sourceId, category, expectedRowVersion, muted) => request(
      `/assistant/unified-notices/category-mutes/${encodeURIComponent(sourceId)}/${encodeURIComponent(category)}`,
      {
        method: muted ? "PUT" : "DELETE",
        body: JSON.stringify({ novel_id: novelId, expected_row_version: expectedRowVersion }),
      },
    ),
    // ============================================================
    // 引导流程（ADR-0032）：服务端确定性编排；前端只渲染停点与推进。
    // ============================================================
    guidedFlowStart: (body) => post("/assistant/flows", body),
    guidedFlowLatest: (novelId, flowId) => request(withQuery("/assistant/flows/latest", { novel_id: novelId, flow_id: flowId }), { cache: "no-store" }),
    guidedFlowActive: (novelId) => request(withQuery("/assistant/flows/active", { novel_id: novelId }), { cache: "no-store" }),
    guidedFlow: (novelId, runId) => request(withQuery(`/assistant/flows/${encodeURIComponent(runId)}`, { novel_id: novelId }), { cache: "no-store" }),
    guidedFlowAdvance: (runId, body) => post(`/assistant/flows/${encodeURIComponent(runId)}/advance`, body),
    guidedFlowSettings: (runId, body) => post(`/assistant/flows/${encodeURIComponent(runId)}/settings`, body),
    guidedFlowAbandon: (novelId, runId) => post(withQuery(`/assistant/flows/${encodeURIComponent(runId)}/abandon`, { novel_id: novelId })),
    goalCapabilities: (novelId) => request(withQuery("/assistant/goals/capabilities", { novel_id: novelId }), { cache: "no-store" }),
    activeGoal: (novelId) => request(withQuery("/assistant/goals/active", { novel_id: novelId }), { cache: "no-store" }),
    recentGoals: (novelId) => request(withQuery("/assistant/goals/recent", { novel_id: novelId }), { cache: "no-store" }),
    goal: (novelId, runId) => request(withQuery(`/assistant/goals/${encodeURIComponent(runId)}`, { novel_id: novelId }), { cache: "no-store" }),
    startGoal: (body) => post("/assistant/goals", body),
    approveGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/approve`, { novel_id: novelId }), body),
    advanceGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/advance`, { novel_id: novelId }), body),
    approveGoalStep: (novelId, runId, stepId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}/approve`, { novel_id: novelId }), body),
    pauseGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/pause`, { novel_id: novelId }), body),
    resumeGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/resume`, { novel_id: novelId }), body),
    cancelGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/cancel`, { novel_id: novelId }), body),
    replanGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/replan`, { novel_id: novelId }), body),
    restoreGoal: (novelId, runId, body) => post(withQuery(`/assistant/goals/${encodeURIComponent(runId)}/restore`, { novel_id: novelId }), body),
};
