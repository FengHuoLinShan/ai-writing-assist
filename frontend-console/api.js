/**
 * API 封装 — 与后端 REST API 通信（组装层）
 *
 * 基础 URL 可配置，统一错误处理，超时控制。
 * 所有函数返回 Promise<Object>。
 *
 * AO-13 拆分：各命名空间位于 api/<domain>.js，共享请求底座位于
 * api/_shared.js。本文件只按原有键序组装出与拆分前完全一致的 api
 * 对象并导出到全局；新增方法请加入对应领域模块。
 */

import {
  _clearAccessToken,
  _setAccessToken,
  reportFrontendError,
  request,
} from "./api/_shared.js"
import { clearCache, healthCheck } from "./api/core.js"
import { evolution } from "./api/evolution.js"
import { forecasts } from "./api/forecasts.js"
import { collaboration } from "./api/collaboration.js"
import { assistant } from "./api/assistant.js"
import { localAgent } from "./api/localAgent.js"
import { auth } from "./api/auth.js"
import { projects } from "./api/projects.js"
import { interactionForecasts } from "./api/interactionForecasts.js"
import { interactions } from "./api/interactions.js"
import { world } from "./api/world.js"
import { rag } from "./api/rag.js"
import { context } from "./api/context.js"
import { writing } from "./api/writing.js"
import { generate } from "./api/generate.js"
import { imports } from "./api/imports.js"
import { outline } from "./api/outline.js"
import { story } from "./api/story.js"
import { tasks } from "./api/tasks.js"
import { settingsApi } from "./api/settings.js"

const api = {
  evolution,
  forecasts,
  collaboration,
  setAccessToken: _setAccessToken,
  clearAccessToken: _clearAccessToken,
  reportFrontendError,
  assistant,
  localAgent,
  auth,
  projects,
  interactionForecasts,
  interactions,
  world,
  rag,
  context,
  writing,
  generate,
  healthCheck,
  imports,
  outline,
  story,
  clearCache,
  tasks,
  // 底层请求入口（测试用，业务代码优先使用领域方法）
  request,
}

// Settings API — 全局默认 + 项目覆盖 + effective 视图（D1-D25 见 spec）
api.settings = settingsApi

// 导出到全局
window.api = api
