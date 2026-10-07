/**
 * api/settings.js — api.settings 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  put,
  deleteRequest,
  contractFetch,
  contractJson,
} from "./_shared.js"

// Settings API — 全局默认 + 项目覆盖 + effective 视图（D1-D25 见 spec）

export const settingsApi = {
  // 全局 LLM 默认（不含 Key）
  listGlobalLLMDefaults: () => contractFetch("settings.listGlobalLLMDefaults"),
  updateGlobalLLMDefaults: (payload) =>
    contractJson("settings.updateGlobalLLMDefaults", {}, {}, payload),
  listLLMConnections: () => contractFetch("settings.listLLMConnections"),
  getImageConnection: () => contractFetch("settings.getImageConnection"),
  connectImageProvider: (apiKey) => contractJson("settings.connectImageProvider", {}, {}, { api_key: apiKey }),
  clearImageProvider: () => contractFetch("settings.clearImageProvider"),
  connectLLMProvider: (providerId, apiKey) =>
    contractJson(
      "settings.connectLLMProvider",
      { providerId },
      {},
      { api_key: apiKey },
    ),
  activateLLMProvider: (providerId) =>
    contractFetch("settings.activateLLMProvider", { providerId }),
  clearLLMProvider: (providerId) =>
    deleteRequest(`/account/settings/llm-connections/${providerId}`),
  updateSecondaryModels: (models) =>
    put("/account/settings/llm-defaults/secondary-models", { models }),
  listLLMDefaults: () => request("/account/settings/llm-defaults", { cache: "no-store" }),
  listLLMBalances: () => contractFetch("settings.listLLMBalances"),

  // 全局作者偏好
  listGlobalAuthorPrefs: () => request("/account/settings/author-preferences"),
  updateGlobalAuthorPrefs: (payload) => put("/account/settings/author-preferences", payload),

  // 引用此默认的项目聚合（D18/D19）
  listProjectsUsingDefaults: (params = {}) =>
    request(withQuery("/account/settings/projects-using-defaults", params)),

  // 调试端点：通知客户端刷新（D16）
  refreshSettings: () => post("/account/settings/refresh"),

  // 项目级作者偏好覆盖
  getProjectAuthorPrefs: (projectId) =>
    contractFetch("settings.getProjectAuthorPrefs", { projectId }),
  updateProjectAuthorPrefs: (projectId, payload) =>
    contractJson("settings.updateProjectAuthorPrefs", { projectId }, {}, payload),
  resetProjectAuthorPrefsField: (projectId, field) =>
    deleteRequest(`/projects/${projectId}/author-preferences/field/${field}`),

  // 项目 effective 视图（含 source 标签）
  getEffectiveLLMSettings: (projectId) =>
    contractFetch("settings.getEffectiveLLMSettings", { projectId }),
  getEffectiveAuthorPrefs: (projectId) =>
    request(`/projects/${projectId}/effective-author-preferences`),

  // 项目 LLM 字段级 reset
  resetLLMSettingsField: (projectId, field) =>
    deleteRequest(`/projects/${projectId}/llm-settings/field/${field}`),
};
