/**
 * api/interactionForecasts.js — api.interactionForecasts 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  post,
} from "./_shared.js"

export const interactionForecasts = {
    resume: (journeyId, id) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/runs/${encodeURIComponent(id)}/resume`),
    capabilities: (journeyId) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/capabilities`, { cache: "no-store" }),
    feed: (journeyId, body) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/feed`, body),
    evaluate: (journeyId, body) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/evaluate`, body),
    run: (journeyId, id) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/runs/${encodeURIComponent(id)}`, { cache: "no-store" }),
    operation: (journeyId, id) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/operations/${encodeURIComponent(id)}`, { cache: "no-store" }),
    cancel: (journeyId, id) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/runs/${encodeURIComponent(id)}/cancel`),
    prefill: (journeyId, id, body) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/candidates/${encodeURIComponent(id)}/prefill`, body),
    decide: (journeyId, id, body) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/forecasts/candidates/${encodeURIComponent(id)}/decision`, body),
};
