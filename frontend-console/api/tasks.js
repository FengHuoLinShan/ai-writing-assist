/**
 * api/tasks.js — api.tasks 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  post,
  contractFetch,
  apiContractHelpers,
} from "./_shared.js"

  // ============================================================
  // 任务（异步操作）
  // ============================================================

export const tasks = {
    async submit(taskType, meta = {}) {
      return post("/tasks", { task_type: taskType, meta })
    },

    async get(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      const params = { _ts: Date.now() }
      if (resolvedNovelId) params.novel_id = resolvedNovelId
      const query = apiContractHelpers.queryString(params)
      return request(`/tasks/${taskId}${query}`)
    },

    async cancel(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      return contractFetch("tasks.cancel", { taskId }, { novel_id: resolvedNovelId })
    },

    async retry(taskId, novelId = null) {
      const resolvedNovelId = novelId || globalThis.appState?.currentProjectId
      return contractFetch("tasks.retry", { taskId }, { novel_id: resolvedNovelId })
    },
};
