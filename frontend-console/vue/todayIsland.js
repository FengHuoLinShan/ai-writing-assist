import { clearActiveWorkflow, normalizeTaskProgress, recoverActiveWorkflows } from "../shared/workflowProgress.js"
import { getApi, getAppState, getRouter } from "./bridge/index.js"
import { mountIsland } from "./mountIsland.js"
import TodayView from "./views/today/TodayView.vue"
import {
  clearCreativeContinuation,
  generateSessionKey,
  hasGenerateSession,
  readCreativeContinuation,
} from "./views/generate/generateSession.js"

const WORKFLOW_LIMIT = 3
const SUGGESTION_PAGE_LIMIT = 50

function listItems(value) {
  return Array.isArray(value) ? value : Array.isArray(value?.items) ? value.items : []
}

function draftContinuation(draft) {
  if (typeof draft?.id !== "string" || !draft.id) return null
  const title = typeof draft.title === "string" && draft.title.trim() ? draft.title.trim() : "未命名世界书页面"
  return {
    key: `world_bible_draft:${draft.id}`,
    destination: "world_bible_draft",
    route: { draft_id: draft.id, page_id: draft.page_id || null },
    title: `继续《${title}》工作稿`,
    description: "打开服务器保存的世界书工作稿；正式页面尚未变化。",
  }
}

function suggestionContinuation(suggestion) {
  if (typeof suggestion?.id !== "string" || !suggestion.id) return null
  const payload = suggestion?.payload_json || {}
  const rawTitle = payload.page?.title || payload.name
  const title = typeof rawTitle === "string" && rawTitle.trim() ? rawTitle.trim() : "世界书页面"
  return {
    key: `world_suggestion_review:${suggestion.id}`,
    destination: "world_suggestion_review",
    route: { suggestion_id: suggestion.id },
    title: `审查《${title}》建议`,
    description: "进入待处理建议；采用前不会修改正式设定。",
  }
}

function generateContinuation(pointer) {
  const labels = {
    core_entity: "继续世界对象共创",
    world_bible_page: "继续完善世界书页面",
    world_bible_new_page: "继续创作世界书新页",
  }
  return {
    key: `generate:${pointer.route.source_page_id || "project"}:${pointer.route.target}`,
    destination: "generate",
    route: pointer.route,
    title: labels[pointer.route.target],
    description: "恢复本机未发送输入与对话；打开后不会自动发起生成。",
  }
}

async function loadPendingSuggestions(api, projectId, suggestionId = null) {
  let skip = 0
  let firstPage = []
  while (true) {
    const result = await api.world.listSuggestions({
      novel_id: projectId,
      source_module: "world",
      review_group: "generation_center",
      status: "pending",
      skip,
      limit: SUGGESTION_PAGE_LIMIT,
    })
    const items = listItems(result)
    if (skip === 0) firstPage = items
    const pointed = suggestionId ? items.find((item) => item.id === suggestionId) : null
    if (pointed) {
      return { items: firstPage.some((item) => item.id === pointed.id) ? firstPage : [...firstPage, pointed] }
    }
    const total = Number(result?.total)
    if (
      !suggestionId
      || !items.length
      || items.length < SUGGESTION_PAGE_LIMIT
      || (Number.isFinite(total) && skip + items.length >= total)
    ) return { items: firstPage }
    skip += items.length
  }
}

function resolveCreativeContinuation(pointer, projectId, draftsResult, suggestionsResult, warn) {
  if (!pointer) return null
  if (pointer.destination === "generate") {
    const key = generateSessionKey(projectId, pointer.route.source_page_id, pointer.route.target)
    return hasGenerateSession(key, { notify: warn }) ? generateContinuation(pointer) : null
  }
  if (pointer.destination === "world_bible_draft") {
    if (draftsResult.status === "rejected") {
      return draftContinuation({ id: pointer.route.draft_id, page_id: pointer.route.page_id })
    }
    const draft = listItems(draftsResult.value).find((item) => item.id === pointer.route.draft_id)
    return draft ? draftContinuation(draft) : null
  }
  if (suggestionsResult.status === "rejected") {
    return suggestionContinuation({ id: pointer.route.suggestion_id })
  }
  const suggestion = listItems(suggestionsResult.value).find((item) => item.id === pointer.route.suggestion_id)
  return suggestion?.target_type === "world_bible_page_draft" ? suggestionContinuation(suggestion) : null
}

async function loadWorkflow(api, workflow, projectId) {
  try {
    const task = await api.tasks.get(workflow.taskId, projectId)
    const progress = normalizeTaskProgress(task, workflow.workflowType)
    if (progress.done || progress.cancelled) {
      clearActiveWorkflow(workflow.taskId)
      return null
    }
    return {
      ...progress,
      view: workflow.view || null,
    }
  } catch {
    return {
      taskId: workflow.taskId,
      workflowType: workflow.workflowType || "task",
      view: workflow.view || null,
      status: "unknown",
      statusLabel: "状态暂不可用",
      percent: null,
      failed: false,
      stateUnknown: true,
    }
  }
}

export async function loadTodayProps() {
  const state = getAppState()
  const api = getApi()
  const projectId = state?.currentProjectId || null
  const project = state?.currentProject || null
  if (!projectId) {
    return {
      project: null,
      summary: null,
      workflows: [],
      creativeContinuation: null,
      worldContinuations: [],
      continuationWarning: null,
      worldLoadError: null,
      loadError: "请先选择一部作品。",
    }
  }

  let continuationWarning = null
  const warn = (_code, message) => { continuationWarning = message }
  const pointer = readCreativeContinuation(projectId, { notify: warn })
  const pointedSuggestionId = pointer?.destination === "world_suggestion_review"
    ? pointer.route.suggestion_id
    : null
  const [summaryResult, draftsResult, suggestionsResult] = await Promise.allSettled([
    api.projects.getWorkspaceSummary(projectId),
    api.world?.listBibleDrafts ? api.world.listBibleDrafts(projectId) : Promise.resolve({ items: [] }),
    api.world?.listSuggestions
      ? loadPendingSuggestions(api, projectId, pointedSuggestionId)
      : Promise.resolve({ items: [] }),
  ])
  const creativeContinuation = resolveCreativeContinuation(pointer, projectId, draftsResult, suggestionsResult, warn)
  if (pointer && !creativeContinuation) {
    clearCreativeContinuation(projectId)
    continuationWarning = "上次世界设定创作位置已失效，已清除该入口；请从当前正文、工作稿或建议重新选择。"
  }
  const firstDraft = listItems(draftsResult.status === "fulfilled" ? draftsResult.value : null)
    .map((item) => draftContinuation(item)).find(Boolean)
  const firstSuggestion = listItems(suggestionsResult.status === "fulfilled" ? suggestionsResult.value : null)
    .filter((item) => item.target_type === "world_bible_page_draft")
    .map((item) => suggestionContinuation(item)).find(Boolean)
  const worldContinuations = [firstDraft, firstSuggestion].filter(Boolean)
  const stored = recoverActiveWorkflows(projectId)
    .sort((left, right) => String(right.updatedAt || right.createdAt || "").localeCompare(String(left.updatedAt || left.createdAt || "")))
    .slice(0, WORKFLOW_LIMIT)
  const workflows = (await Promise.all(
    stored.map((workflow) => loadWorkflow(api, workflow, projectId)),
  )).filter(Boolean)

  return {
    project,
    summary: summaryResult.status === "fulfilled" ? summaryResult.value : null,
    workflows,
    creativeContinuation,
    worldContinuations,
    continuationWarning,
    worldLoadError: draftsResult.status === "rejected" || suggestionsResult.status === "rejected"
      ? "部分世界设定暂时无法加载；已保存内容不会受影响。"
      : null,
    loadError: summaryResult.status === "rejected"
      ? (summaryResult.reason?.message || "作品概览暂时无法加载。")
      : null,
  }
}

export function registerTodayIsland() {
  const router = getRouter()
  if (!router) {
    console.error("todayIsland: router 尚未就绪，island 注册跳过")
    return null
  }
  const island = mountIsland({
    viewName: "today",
    component: TodayView,
    load: loadTodayProps,
  })
  router.registerView("today", island)
  return island
}

registerTodayIsland()
