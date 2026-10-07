/**
 * api/interactions.js — api.interactions 命名空间（AO-13 自 api.js 按命名空间拆分）。
 * 方法体自 api.js 原样移动，行为不变；请求底座见 ./_shared.js。
 */

import {
  request,
  withQuery,
  post,
  uploadInteractionSource,
  contractPath,
  contractFetch,
  contractJson,
  streamSse,
  _cookieValue,
} from "./_shared.js"

export const interactions = {
    demoSource: () => request("/demo/rp-source", { cache: "no-store", _suppressAccountInvalidation: true }),
    listDemoJourneys: (params = {}) => request(withQuery("/interactions/demo-journeys", params), { cache: "no-store", _suppressAccountInvalidation: true }),
    createDemoJourney: (payload) => post("/interactions/demo-journeys", payload, { cache: "no-store", _suppressAccountInvalidation: true }),
    listSources() {
      return contractFetch(
        "interactions.listSources",
        {},
        {},
        { cache: "no-store" },
      )
    },
    previewSourceImport(payload, onProgress = null, options = {}) {
      return uploadInteractionSource(
        "/interactions/sources/import-preview",
        payload,
        onProgress,
        options,
      )
    },
    importSource(payload, onProgress = null, options = {}) {
      return uploadInteractionSource(
        "/interactions/sources/import",
        payload,
        onProgress,
        options,
      )
    },
    refreshSource(revisionId) {
      return contractFetch("interactions.refreshSource", { revisionId })
    },
    listOpenings(params = {}) {
      return contractFetch("interactions.listOpenings", {}, params, { cache: "no-store" })
    },
    fetchOpeningImage(openingId) {
      return contractFetch("interactions.fetchOpeningImage", { openingId }, {}, { cache: "no-store", _responseType: "blob" })
    },
    startOpening(openingId, payload) {
      return contractJson("interactions.startOpening", { openingId }, {}, payload)
    },
    sourceFromProject(payload) {
      return contractJson(
        "interactions.sourceFromProject",
        {},
        {},
        payload,
      )
    },
    getSource(revisionId) {
      return contractFetch(
        "interactions.getSource",
        { revisionId },
        {},
        { cache: "no-store" },
      )
    },
    resolveSourceAmbiguity(revisionId, ambiguityKey, choiceKey) {
      return contractJson(
        "interactions.resolveSourceAmbiguity",
        { revisionId, ambiguityKey },
        {},
        { choice_key: choiceKey },
      )
    },
    listSourceAnchors(revisionId, params = {}) {
      return contractFetch(
        "interactions.listSourceAnchors",
        { revisionId },
        params,
        { cache: "no-store" },
      )
    },
    matchSourceAnchors(revisionId, payload) {
      return contractJson(
        "interactions.matchSourceAnchors",
        { revisionId },
        {},
        payload,
      )
    },
    listSourceObjects(revisionId, params = {}) {
      return contractFetch(
        "interactions.listSourceObjects",
        { revisionId },
        params,
        { cache: "no-store" },
      )
    },
    listJourneys(params = {}) {
      return contractFetch("interactions.listJourneys", {}, params, {
        cache: "no-store",
      })
    },
    createJourney(payload) {
      return contractJson("interactions.createJourney", {}, {}, payload)
    },
    getJourney(journeyId, options = {}) {
      return contractFetch(
        "interactions.getJourney",
        { journeyId },
        {},
        { cache: "no-store", ...options },
      )
    },
    updateJourneySource(journeyId, payload) {
      return contractJson(
        "interactions.updateJourneySource",
        { journeyId },
        {},
        payload,
      )
    },
    getJourneyReferences(journeyId) {
      return contractFetch(
        "interactions.getJourneyReferences",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    updateJourneyReferences(journeyId, payload) {
      return contractJson(
        "interactions.updateJourneyReferences",
        { journeyId },
        {},
        payload,
      )
    },
    getMessages(journeyId, params = {}) {
      return contractFetch(
        "interactions.getMessages",
        { journeyId },
        params,
        { cache: "no-store" },
      )
    },
    getPathIndex(journeyId) {
      return contractFetch(
        "interactions.getPathIndex",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    sendMessage(journeyId, payload) {
      return contractJson(
        "interactions.sendMessage",
        { journeyId },
        {},
        payload,
      )
    },
    continueFromNode(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.continueFromNode",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    regenerate(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.regenerate",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    editUserMessage(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.editUserMessage",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    selectBranch(journeyId, nodeId, payload) {
      return contractJson(
        "interactions.selectBranch",
        { journeyId, nodeId },
        {},
        payload,
      )
    },
    listBranches(journeyId, nodeId) {
      return contractFetch(
        "interactions.listBranches",
        { journeyId, nodeId },
        {},
        { cache: "no-store" },
      )
    },
    getTree(journeyId) {
      return contractFetch(
        "interactions.getTree",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    getAttempt(journeyId, attemptId) {
      return contractFetch(
        "interactions.getAttempt",
        { journeyId, attemptId },
        {},
        { cache: "no-store" },
      )
    },
    streamAttempt(journeyId, attemptId, offset = 0, options = {}) {
      return streamSse(contractPath(
        "interactions.streamAttempt",
        { journeyId, attemptId },
        { offset },
      ), options)
    },
    streamDemoAttempt(journeyId, attemptId, apiKey, options = {}) {
      const csrfToken = _cookieValue("aaw_demo_rp_csrf") || _cookieValue("aaw_csrf")
      return streamSse(
        `/interactions/journeys/${encodeURIComponent(journeyId)}/attempts/${encodeURIComponent(attemptId)}/stream`,
        {
          ...options,
          method: "POST",
          suppressAccountInvalidation: true,
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-Demo-RP-Session": "1",
            "X-DeepSeek-API-Key": String(apiKey || ""),
            ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
          },
        },
      )
    },
    stopAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.stopAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    keepAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.keepAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    continueAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.continueAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    retryAttempt(journeyId, attemptId, payload) {
      return contractJson(
        "interactions.retryAttempt",
        { journeyId, attemptId },
        {},
        payload,
      )
    },
    updateModes(journeyId, payload) {
      return contractJson(
        "interactions.updateModes",
        { journeyId },
        {},
        payload,
      )
    },
    heartbeat(journeyId) {
      return contractFetch(
        "interactions.heartbeat",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    leaveJourney(journeyId) {
      return contractFetch(
        "interactions.leaveJourney",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    updateTitle(journeyId, payload) {
      return contractJson(
        "interactions.updateTitle",
        { journeyId },
        {},
        payload,
      )
    },
    getOverview(journeyId) {
      return contractFetch(
        "interactions.getOverview",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    carePolicy: (journeyId) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/care/policy`, { cache: "no-store" }),
    saveCarePolicy: (journeyId, policy) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/care/policy`, { method: "PUT", body: JSON.stringify(policy) }),
    careNotices: (journeyId) => request(`/interactions/journeys/${encodeURIComponent(journeyId)}/care/notices`, { cache: "no-store" }),
    recheckCareNotice: (journeyId, noticeId, operationId) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/care/notices/${encodeURIComponent(noticeId)}/recheck`, { operation_id: operationId }),
    decideCareNotice: (journeyId, noticeId, disposition) => post(`/interactions/journeys/${encodeURIComponent(journeyId)}/care/notices/${encodeURIComponent(noticeId)}/decide`, disposition),
    updateOverview(journeyId, payload) {
      return contractJson(
        "interactions.updateOverview",
        { journeyId },
        {},
        payload,
      )
    },
    retryOverview(journeyId) {
      return contractFetch(
        "interactions.retryOverview",
        { journeyId },
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    listGenerationRecords(journeyId) {
      return contractFetch(
        "interactions.listGenerationRecords",
        { journeyId },
        {},
        { cache: "no-store" },
      )
    },
    archiveJourney(journeyId) {
      return contractJson(
        "interactions.archiveJourney",
        { journeyId },
        {},
        { confirmed: true },
      )
    },
    getPreferences() {
      return contractFetch(
        "interactions.getPreferences",
        {},
        {},
        { cache: "no-store" },
      )
    },
    acknowledgeSeeSeaNotice() {
      return contractFetch(
        "interactions.acknowledgeSeeSeaNotice",
        {},
        {},
        { method: "POST", cache: "no-store" },
      )
    },
    restoreJourney(journeyId) {
      return contractFetch(
        "interactions.restoreJourney",
        { journeyId },
        {},
        { method: "POST" },
      )
    },
    deleteJourney(journeyId, titleConfirmation) {
      return contractJson(
        "interactions.deleteJourney",
        { journeyId },
        {},
        { title_confirmation: titleConfirmation },
      )
    },
    exportJourney(journeyId, params = {}) {
      return contractFetch(
        "interactions.exportJourney",
        { journeyId },
        params,
        { cache: "no-store" },
      )
    },
};
