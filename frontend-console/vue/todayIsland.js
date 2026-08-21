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
import { readWritingPointer } from "./views/writing/writingSession.js"

const WORKFLOW_LIMIT = 3
const SUGGESTION_PAGE_LIMIT = 50

function listItems(value) {
  return Array.isArray(value) ? value : Array.isArray(value?.items) ? value.items : []
}

function attentionSuggestionIds(summary) {
  return new Set(listItems(summary?.attention?.items)
    .filter((item) => ["world_suggestion", "world_adoption"].includes(item?.target?.kind))
    .map((item) => item.target.suggestion_id)
    .filter(Boolean))
}

function isProjectedDecision(continuation, suggestionIds) {
  if (continuation?.destination === "world_suggestion_review") {
    return suggestionIds.has(continuation.route.suggestion_id)
  }
  if (continuation?.destination === "world_adoption_review") {
    return suggestionIds.has(continuation.route.package_id)
  }
  return false
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
    key: `generate:${pointer.route.source_page_id || "project"}:${pointer.route.target}:${pointer.route.preset || "custom"}:${pointer.route.checkpoint_id || "local"}`,
    destination: "generate",
    route: pointer.route,
    title: pointer.route.preset === "world_core" ? "继续让灵感生长" : labels[pointer.route.target],
    description: pointer.route.checkpoint_id
      ? "从已保存的作者决定摘要继续；不会重放过时的 AI 聊天正文。"
      : "恢复本机未发送输入与对话；打开后不会自动发起生成。",
  }
}

function adoptionContinuation(item) {
  return {
    key: `world-adoption:${item.id}`,
    destination: "world_adoption_review",
    route: { package_id: item.id },
    title: item.source_module === "imports" ? "审阅深度导入设定" : "审阅世界核心采纳包",
    description: "先看清流水线已写入与本次确认将写入；确认后对象、关系和世界书页才会一起提交。",
  }
}

async function loadPendingSuggestions(api, projectId, suggestionId = null, reviewGroup = "generation_center") {
  let skip = 0
  let firstPage = []
  while (true) {
    const result = await api.world.listSuggestions({
      novel_id: projectId,
      source_module: "world",
      review_group: reviewGroup,
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

function resolveCreativeContinuation(pointer, projectId, draftsResult, suggestionsResult, adoptionResult, warn) {
  if (!pointer) return null
  if (pointer.destination === "generate") {
    const key = generateSessionKey(projectId, pointer.route.source_page_id, pointer.route.target, pointer.route.preset)
    if (!pointer.route.checkpoint_id) return hasGenerateSession(key, { notify: warn }) ? generateContinuation(pointer) : null
    if (adoptionResult.status === "rejected") return generateContinuation(pointer)
    const checkpoint = listItems(adoptionResult.value).find((item) => item.id === pointer.route.checkpoint_id)
    return ["world_core_checkpoint", "world_design_checkpoint"].includes(checkpoint?.target_type) ? generateContinuation(pointer) : null
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
  const writingPointer = readWritingPointer(projectId)
  const pointedSuggestionId = pointer?.destination === "world_suggestion_review"
    ? pointer.route.suggestion_id
    : null
  const pointedCheckpointId = pointer?.destination === "generate" ? pointer.route.checkpoint_id || null : null
  const [summaryResult, draftsResult, suggestionsResult, adoptionResult] = await Promise.allSettled([
    api.projects.getWorkspaceSummary(projectId, {
      focus_chapter_index: writingPointer?.chapter,
      focus_scene_id: writingPointer?.sceneId,
    }),
    api.world?.listBibleDrafts ? api.world.listBibleDrafts(projectId) : Promise.resolve({ items: [] }),
    api.world?.listSuggestions
      ? loadPendingSuggestions(api, projectId, pointedSuggestionId)
      : Promise.resolve({ items: [] }),
    api.world?.listSuggestions
      ? loadPendingSuggestions(api, projectId, pointedCheckpointId, "world_adoption")
      : Promise.resolve({ items: [] }),
  ])
  const resolvedCreativeContinuation = resolveCreativeContinuation(pointer, projectId, draftsResult, suggestionsResult, adoptionResult, warn)
  if (pointer && !resolvedCreativeContinuation) {
    clearCreativeContinuation(projectId)
    continuationWarning = "上次世界设定创作位置已失效，已清除该入口；请从当前正文、工作稿或建议重新选择。"
  }
  const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null
  const projectedSuggestionIds = attentionSuggestionIds(summary)
  const creativeContinuation = isProjectedDecision(resolvedCreativeContinuation, projectedSuggestionIds)
    ? null
    : resolvedCreativeContinuation
  const firstDraft = listItems(draftsResult.status === "fulfilled" ? draftsResult.value : null)
    .map((item) => draftContinuation(item)).find(Boolean)
  const firstSuggestion = listItems(suggestionsResult.status === "fulfilled" ? suggestionsResult.value : null)
    .filter((item) => item.target_type === "world_bible_page_draft")
    .map((item) => suggestionContinuation(item)).find(Boolean)
  const firstCheckpoint = listItems(adoptionResult.status === "fulfilled" ? adoptionResult.value : null)
    .find((item) => ["world_design_checkpoint", "world_core_checkpoint"].includes(item.target_type))
  const firstPackage = listItems(adoptionResult.status === "fulfilled" ? adoptionResult.value : null)
    .find((item) => item.target_type === "world_adoption_package")
  const checkpointContinuation = firstCheckpoint ? generateContinuation({ route: {
    source_page_id: null,
    target: "core_entity",
    preset: "world_core",
    checkpoint_id: firstCheckpoint.id,
  } }) : null
  const worldContinuations = [firstPackage ? adoptionContinuation(firstPackage) : null, checkpointContinuation, firstDraft, firstSuggestion]
    .filter((item) => item && !isProjectedDecision(item, projectedSuggestionIds))
  const stored = recoverActiveWorkflows(projectId)
    .sort((left, right) => String(right.updatedAt || right.createdAt || "").localeCompare(String(left.updatedAt || left.createdAt || "")))
    .slice(0, WORKFLOW_LIMIT)
  const workflows = (await Promise.all(
    stored.map((workflow) => loadWorkflow(api, workflow, projectId)),
  )).filter(Boolean)

  return {
    project,
    summary,
    workflows,
    creativeContinuation,
    worldContinuations,
    continuationWarning,
    worldLoadError: draftsResult.status === "rejected" || suggestionsResult.status === "rejected" || adoptionResult.status === "rejected"
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
