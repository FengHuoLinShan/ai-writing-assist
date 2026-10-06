/**
 * api/localAgent.js — api.localAgent 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
} from "./_shared.js"

export const localAgent = {
    receipts: (novelId, taskId) => request(withQuery(`/local-agent/tasks/${taskId}/receipts`, { novel_id: novelId }), { cache: "no-store" }),
    download: (novelId) => request(withQuery("/local-agent/companion/download", { novel_id: novelId }), { cache: "no-store", _responseType: "blob" }),
    pending: (novelId) => request(withQuery("/local-agent/tasks/pending", { novel_id: novelId }), { cache: "no-store" }),
    devices: (novelId) => request(withQuery("/local-agent/devices", { novel_id: novelId }), { cache: "no-store" }),
    pair: (novelId, name) => post("/local-agent/devices/pair", { novel_id: novelId, name }),
    revoke: (novelId, deviceId) => request(withQuery(`/local-agent/devices/${deviceId}`, { novel_id: novelId }), { method: "DELETE" }),
    executor: (novelId) => request(withQuery("/local-agent/executor", { novel_id: novelId }), { cache: "no-store" }),
    select: (novelId, kind, deviceId) => request("/local-agent/executor", { method: "PUT", body: JSON.stringify({ novel_id: novelId, kind, device_id: deviceId || null }) }),
    approve: (novelId, taskId) => post(`/local-agent/tasks/${taskId}/approve`, { novel_id: novelId, acknowledge_full_host_access: true }),
};
