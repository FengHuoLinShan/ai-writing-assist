/**
 * api/auth.js — api.auth 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  post,
  apiContractHelpers,
  API_BASE_URL,
  _setAuthMode,
} from "./_shared.js"

export const auth = {
    async config() {
      const config = await request("/auth/config", { cache: "no-store" })
      _setAuthMode(config.auth_mode || "local")
      return config
    },
    me: () => request("/auth/me", {
      cache: "no-store",
      _suppressAccountInvalidation: true,
    }),
    anonymousRp: (payload) => post("/auth/anonymous-rp", payload, { cache: "no-store", _suppressAccountInvalidation: true }),
    requestEmailCode: (email) =>
      post("/auth/email/request-code", { email }, { cache: "no-store" }),
    verifyEmail: (payload) =>
      post("/auth/email/verify", payload, { cache: "no-store" }),
    demoLogin: (payload) =>
      post("/auth/demo-login", payload, { cache: "no-store" }),
    requestReauthEmailCode: (email) =>
      post("/auth/reauth/email/request-code", { email }, { cache: "no-store" }),
    verifyReauthEmail: (payload) =>
      post("/auth/reauth/email/verify", payload, { cache: "no-store" }),
    logout: () => post("/auth/logout", undefined, {
      cache: "no-store",
      _suppressAccountInvalidation: true,
    }),
    deletion: () => request("/account/deletion", { cache: "no-store" }),
    requestDeletion: () =>
      post("/account/deletion", undefined, { cache: "no-store" }),
    cancelDeletion: () =>
      request("/account/deletion", { method: "DELETE", cache: "no-store" }),
    wechatStartUrl(config, purpose = "login") {
      const host = API_BASE_URL.slice(0, -4)
      if (purpose === "reauth") return `${host}/api/auth/reauth/wechat/start`
      const query = apiContractHelpers.queryString({ accept_terms: true, accept_privacy: true })
      return `${host}/api/auth/wechat/start${query}`
    },
};
