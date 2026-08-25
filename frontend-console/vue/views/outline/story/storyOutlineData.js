/**
 * storyOutlineData — 小说总纲模块的数据层。
 *
 * 两个导出：
 * - loadStoryOutlineProps(projectId)：island 预取用，返回扁平 props 对象。
 * - storyOutlineTaskManager：模块级任务管理器（轮询/恢复/取消/关闭），
 *   不挂组件生命周期，island load() → recover()，onLeave → stop()。
 */
import { reactive } from "vue"
import { getApi, getAppState, getRouter, getToast } from "../../../bridge/index.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../../../../shared/workflowProgress.js"

// ---- 常量 ----

const STORY_OUTLINE_TASK_TYPE = "story_outline_generate"
const STORY_OUTLINE_ACTION = "outline.story_outline.generate"
const HISTORY_LIMIT = 20

const SOURCE_LABELS = {
  manual: "手工创建",
  ai_generated: "AI 生成后采用",
  restored: "从历史版本采用",
}

export { SOURCE_LABELS, STORY_OUTLINE_TASK_TYPE, STORY_OUTLINE_ACTION, HISTORY_LIMIT }

// ---- 工具函数 ----

export function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

/** 把服务端版本或本地未完成草稿收窄为编辑器可安全修改的字段。 */
export function editableStoryOutlineContent(raw = {}) {
  const text = (value) => typeof value === "string" ? value : ""
  const objects = (value) => Array.isArray(value)
    ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item))
    : []
  const strings = (value) => Array.isArray(value) ? value.filter((item) => typeof item === "string") : []
  const core = raw?.creative_core && typeof raw.creative_core === "object"
    ? raw.creative_core
    : {}

  return {
    title: text(raw?.title),
    creative_core: {
      premise: text(core.premise),
      tone_and_reader_promise: text(core.tone_and_reader_promise),
      story_engine: text(core.story_engine),
      ending_direction: text(core.ending_direction),
    },
    outline_markdown: text(raw?.outline_markdown),
    major_storylines: objects(raw?.major_storylines).map((item) => ({
      name: text(item.name),
      narrative_function: text(item.narrative_function),
      trajectory: text(item.trajectory),
      intersections: strings(item.intersections),
      resolution_direction: text(item.resolution_direction),
    })),
    macro_movements: objects(raw?.macro_movements).map((item) => ({
      name: text(item.name),
      story_state_change: text(item.story_state_change),
      advanced_storylines: strings(item.advanced_storylines),
    })),
    open_decisions: objects(raw?.open_decisions).map((item) => ({
      question: text(item.question),
      why_it_matters: text(item.why_it_matters),
      options: strings(item.options),
    })),
  }
}

export function idempotencyKey() {
  let token
  if (typeof globalThis.crypto?.randomUUID === "function") {
    token = globalThis.crypto.randomUUID()
  } else {
    if (typeof globalThis.crypto?.getRandomValues !== "function") {
      throw new Error("当前浏览器无法安全生成操作标识，请更换浏览器后重试")
    }
    const bytes = new Uint8Array(16)
    globalThis.crypto.getRandomValues(bytes)
    token = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")
  }
  return `story-outline-${token}`.slice(0, 128)
}

/** 小说总纲 payload 的纯同步校验规则。 */
const STORY_OUTLINE_CONTENT_FIELDS = [
  "title",
  "creative_core",
  "outline_markdown",
  "major_storylines",
  "macro_movements",
  "open_decisions",
]

function assertPlainObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}的内容格式不正确`)
  }
}

function assertExactKeys(value, allowedKeys, label) {
  assertPlainObject(value, label)
  const extras = Object.keys(value).filter((key) => !allowedKeys.includes(key))
  if (extras.length) throw new Error(`${label}包含未支持字段：${extras.join("、")}`)
}

function requiredText(value, label) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label}不能为空`)
  return value.trim()
}

function stringList(value, label) {
  if (!Array.isArray(value)) throw new Error(`${label}必须是列表`)
  return value.map((item, index) => requiredText(item, `${label}第 ${index + 1} 项`))
}

export function validateStoryOutlineContent(raw) {
  assertExactKeys(raw, STORY_OUTLINE_CONTENT_FIELDS, "总纲")

  assertExactKeys(raw.creative_core, [
    "premise",
    "tone_and_reader_promise",
    "story_engine",
    "ending_direction",
  ], "创意核心")
  const content = {
    title: requiredText(raw.title, "标题"),
    creative_core: {
      premise: requiredText(raw.creative_core.premise, "核心前提"),
      tone_and_reader_promise: requiredText(
        raw.creative_core.tone_and_reader_promise,
        "基调与读者承诺",
      ),
      story_engine: requiredText(raw.creative_core.story_engine, "故事引擎"),
      ending_direction: raw.creative_core.ending_direction == null
        || String(raw.creative_core.ending_direction).trim() === ""
        ? null
        : requiredText(raw.creative_core.ending_direction, "结局方向"),
    },
    outline_markdown: requiredText(raw.outline_markdown, "总纲正文"),
    major_storylines: raw.major_storylines,
    macro_movements: raw.macro_movements,
    open_decisions: raw.open_decisions,
  }

  if (!Array.isArray(content.major_storylines)) throw new Error("主要剧情线必须是列表")
  content.major_storylines = content.major_storylines.map((item, index) => {
    const label = `主要剧情线第 ${index + 1} 项`
    assertExactKeys(item, ["name", "narrative_function", "trajectory", "intersections", "resolution_direction"], label)
    return {
      name: requiredText(item.name, `${label}名称`),
      narrative_function: requiredText(item.narrative_function, `${label}叙事功能`),
      trajectory: requiredText(item.trajectory, `${label}轨迹`),
      intersections: stringList(item.intersections, `${label}交汇点`),
      resolution_direction: requiredText(item.resolution_direction, `${label}收束方向`),
    }
  })

  if (!Array.isArray(content.macro_movements)) throw new Error("故事推进必须是列表")
  content.macro_movements = content.macro_movements.map((item, index) => {
    const label = `故事推进第 ${index + 1} 项`
    assertExactKeys(item, ["name", "story_state_change", "advanced_storylines"], label)
    const advanced = stringList(item.advanced_storylines, `${label}推进剧情线`)
    return {
      name: requiredText(item.name, `${label}名称`),
      story_state_change: requiredText(item.story_state_change, `${label}状态变化`),
      advanced_storylines: advanced,
    }
  })
  if (!Array.isArray(content.open_decisions)) throw new Error("待决定问题必须是列表")
  content.open_decisions = content.open_decisions.map((item, index) => {
    const label = `待决定问题第 ${index + 1} 项`
    assertExactKeys(item, ["question", "why_it_matters", "options"], label)
    const options = stringList(item.options, `${label}选项`)
    return {
      question: requiredText(item.question, `${label}问题`),
      why_it_matters: requiredText(item.why_it_matters, `${label}作用`),
      options,
    }
  })
  return content
}

export function validateStoryOutlineTaskResult(raw) {
  assertExactKeys(raw, [
    ...STORY_OUTLINE_CONTENT_FIELDS,
    "managed_llm_steps",
    "apply_status",
    "applied_revision_id",
  ], "小说总纲任务结果")
  return validateStoryOutlineContent(Object.fromEntries(
    STORY_OUTLINE_CONTENT_FIELDS.map((field) => [field, raw[field]]),
  ))
}

// ---- 模块级任务管理器 ----

/**
 * storyOutlineTaskManager — 总纲生成轮询的模块级单例。
 *
 * 语义对齐 vanilla：
 * - recover() ← _recoverTask（接收时已有 lifecycle / scope 守卫，此处不重复）
 * - adopt()  ← submitGeneration 后半段
 * - stop()   ← _stopTaskPolling + _stopTaskPolling 调 poller.stop()
 * - cancel() ← _cancelTask（含 confirmAsync）
 * - dismiss() ← _dismissTask
 *
 * terminal 事件通过 setOnTerminal 注册回调，由 composable 挂载。
 */
export const storyOutlineTaskManager = (() => {
  const state = reactive({
    taskId: null,
    meta: null,
    progress: null,
    taskNotice: null,
    cancelPending: false,
  })

  let poller = null
  let _onTerminal = null
  let activeProjectId = null
  // 终态快照在组件重挂载后仍可重放：router 会在 onEnter 取数完成后
  // 才卸载旧 island，任务可能恰好在这个窗口终结。
  let lastTerminal = null

  /** 注册终态回调：(type, progress, task, state) => void */
  function setOnTerminal(handler) {
    _onTerminal = handler
    if (!handler) lastTerminal = null
    if (_onTerminal && lastTerminal && state.taskId === lastTerminal.progress?.taskId) {
      const event = lastTerminal
      _onTerminal(event.type, event.progress, event.task, state)
    }
    return () => {
      if (_onTerminal === handler) _onTerminal = null
    }
  }

  function dispatchTerminal(type, progress, task) {
    lastTerminal = { type, progress, task }
    if (_onTerminal) {
      _onTerminal(type, progress, task, state)
    }
  }

  function stop() {
    if (poller?.stop) poller.stop()
    poller = null
  }

  function _startPolling(taskId, projectId) {
    stop()
    activeProjectId = projectId
    const api = getApi()
    poller = pollTaskProgress({
      taskId,
      workflowType: STORY_OUTLINE_TASK_TYPE,
      novelId: projectId,
      apiClient: api,
      onUpdate: (progress, task) => {
        if (!_scopeIsCurrent(taskId, projectId)) return
        if (!_taskMatches(task, projectId)) {
          _rejectRecoveredTask(taskId, "恢复记录与当前项目或故事总览生成动作不匹配，已停止恢复。")
          return
        }
        if (progress.stateUnknown && /(不存在|not found)/i.test(progress.errorMessage || "")) {
          _rejectRecoveredTask(taskId, "原故事总览生成任务已过期或被清理，请重新生成。")
          return
        }
        state.progress = progress
      },
      onDone: (progress, task) => {
        if (!_scopeIsCurrent(taskId, projectId)) return
        if (!_taskMatches(task, projectId)) {
          _rejectRecoveredTask(taskId, "任务结果与当前项目或故事总览生成动作不匹配，未加载预览。")
          return
        }
        poller = null
        state.progress = progress
        dispatchTerminal("done", progress, task)
      },
      onFailed: (progress) => {
        if (!_scopeIsCurrent(taskId, projectId)) return
        poller = null
        state.progress = progress
        dispatchTerminal("failed", progress, null)
      },
    })
  }

  function _scopeIsCurrent(taskId, projectId) {
    return (
      state.taskId === taskId
      && activeProjectId === projectId
      && getAppState()?.currentProjectId === projectId
    )
  }

  function _taskMatches(task, projectId) {
    if (!task) return true
    return (
      task.task_type === STORY_OUTLINE_TASK_TYPE
      && task.meta?.action === STORY_OUTLINE_ACTION
      && task.meta?.novel_id === projectId
    )
  }

  function _rejectRecoveredTask(taskId, message) {
    stop()
    clearActiveWorkflow(taskId)
    if (state.taskId !== taskId) return
    state.taskId = null
    state.meta = null
    state.progress = null
    state.taskNotice = message
    state.cancelPending = false
    lastTerminal = null
  }

  /**
   * 提交成功后接管任务。
   * @param {object} result — generateStoryOutline 返回值
   * @param {object} meta   — task meta 元数据
   * @param {string} projectId
  */
  function adopt(result, meta, projectId, { attach = true } = {}) {
    persistActiveWorkflow({
      taskId: result.task_id,
      workflowType: STORY_OUTLINE_TASK_TYPE,
      label: "AI 故事总览",
      projectId,
      view: "outline",
      meta: meta || undefined,
    })
    if (!attach) return
    lastTerminal = null
    if (activeProjectId && activeProjectId !== projectId) resetMemoryScope()
    state.taskId = result.task_id
    state.meta = meta || state.meta || null
    state.cancelPending = false
    state.taskNotice = null
    state.progress = normalizeTaskProgress({
      ...result,
      task_type: STORY_OUTLINE_TASK_TYPE,
      meta: state.meta || {},
    }, STORY_OUTLINE_TASK_TYPE)
    _startPolling(result.task_id, projectId)
  }

  function prepare(taskId, meta, projectId) {
    if (!taskId || !projectId) return false
    persistActiveWorkflow({ taskId, workflowType: STORY_OUTLINE_TASK_TYPE, label: "AI 故事总览", projectId, view: "outline", meta: meta || undefined })
    return true
  }

  function resetMemoryScope() {
    stop()
    state.taskId = null
    state.meta = null
    state.progress = null
    state.taskNotice = null
    state.cancelPending = false
    activeProjectId = null
    lastTerminal = null
  }

  /**
   * island load() 调用：从 localStorage 恢复未终结任务。
   */
  function recover(projectId) {
    if (activeProjectId && activeProjectId !== projectId) resetMemoryScope()
    if (state.taskId && state.progress && !state.progress.terminal && activeProjectId === projectId) return
    const workflows = recoverActiveWorkflows(projectId)
    const matched = workflows
      .filter((item) => (
        item.workflowType === STORY_OUTLINE_TASK_TYPE
        && item.projectId === projectId
        && item.meta?.action === STORY_OUTLINE_ACTION
        && item.meta?.novel_id === projectId
      ))
      .sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || "")))[0]
    if (!matched?.taskId) return
    state.taskId = matched.taskId
    state.meta = { ...(matched.meta || {}) }
    state.progress = normalizeTaskProgress({
      task_id: matched.taskId,
      task_type: STORY_OUTLINE_TASK_TYPE,
      status: "pending",
      meta: matched.meta || {},
    }, STORY_OUTLINE_TASK_TYPE)
    _startPolling(matched.taskId, projectId)
  }

  /**
   * 取消任务（含用户确认门槛，由调用方处理）。
   * resolve true 表示已发起取消（服务器不一定立即生效）。
   */
  async function cancel(projectId) {
    const taskId = state.taskId
    if (!taskId || !projectId || state.cancelPending) return false
    stop()
    state.cancelPending = true
    try {
      await getApi().tasks.cancel(taskId, projectId)
      // 立即设置为取消态（对齐 vanilla _cancelTask 不依赖轮询 onFailed）
      state.cancelPending = false
      state.progress = normalizeTaskProgress({
        task_id: taskId,
        task_type: STORY_OUTLINE_TASK_TYPE,
        status: "cancelled",
        result: { message: "任务已取消" },
        meta: state.meta || {},
      }, STORY_OUTLINE_TASK_TYPE)
      state.taskNotice = "故事总览生成已取消，没有创建新版本。"
      return true
    } catch (err) {
      if (state.taskId === taskId) {
        state.cancelPending = false
        _startPolling(taskId, projectId)
      }
      getToast()(err.message || "取消任务失败", "error")
      return false
    }
  }

  /** 关闭已终结的任务。 */
  function dismiss() {
    if (state.taskId) clearActiveWorkflow(state.taskId)
    stop()
    state.taskId = null
    state.meta = null
    state.progress = null
    state.taskNotice = null
    state.cancelPending = false
    activeProjectId = null
    lastTerminal = null
  }

  return { state, stop, recover, prepare, adopt, cancel, dismiss, setOnTerminal, resetMemoryScope }
})()

// ---- island 预取 ----

/**
 * loadStoryOutlineProps — 对应 vanilla onEnter 的四路并行预取。
 *
 * 返回的扁平 props 写入 island mount，OutlineStoryTab 通过 defineProps 接收。
 *
 * @param {string|null} projectId
 * @returns {Promise<object>} 扁平 props 对象
 *
 * 返回 key 清单：
 *   projectId, current, history, historyTotal, characters, entities,
 *   loadError, assetLoadError
 */
export async function loadStoryOutlineProps(projectId, { recoverTask = true } = {}) {
  const api = getApi()
  const router = getRouter()

  const props = {
    projectId: projectId || null,
    current: null,
    history: [],
    historyTotal: 0,
    characters: [],
    entities: [],
    loadError: null,
    assetLoadError: null,
  }

  if (!projectId) return props

  // 工作流恢复（模块级 manager，轮询不挂组件生命周期）
  if (recoverTask) storyOutlineTaskManager.recover(projectId)

  const [currentResult, historyResult, charactersResult, entitiesResult] = await Promise.allSettled([
    api.outline.getStoryOutline(projectId),
    api.outline.listStoryOutlineRevisions(projectId, 0, HISTORY_LIMIT),
    api.world.listCharacters({ novel_id: projectId, skip: 0, limit: 50 }),
    api.world.listEntities({
      novel_id: projectId,
      display_state: "active",
      skip: 0,
      limit: 50,
      view_mode: "normal",
    }),
  ])

  if (currentResult.status === "fulfilled" && historyResult.status === "fulfilled") {
    props.current = currentResult.value || { current_revision_id: null, revision: null }
    props.history = historyResult.value?.items || []
    props.historyTotal = Number(historyResult.value?.total ?? props.history.length) || 0
  } else {
    const reason = currentResult.status === "rejected"
      ? currentResult.reason
      : historyResult.reason
    props.loadError = reason?.message || "故事总览加载失败"
  }

  props.characters = charactersResult.status === "fulfilled"
    ? charactersResult.value?.items || charactersResult.value || []
    : []
  props.entities = entitiesResult.status === "fulfilled"
    ? entitiesResult.value?.items || entitiesResult.value || []
    : []

  if (charactersResult.status === "rejected" || entitiesResult.status === "rejected") {
    props.assetLoadError = "可选人物或世界对象未完全加载，仍可不选资产直接生成。"
  }

  return props
}
