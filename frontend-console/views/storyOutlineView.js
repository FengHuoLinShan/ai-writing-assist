/**
 * 小说总纲工作台。
 *
 * 总纲是 World 之后、篇章纲与 Scene 之前的项目级结构资产。
 * AI 生成只产生可编辑 preview，明确采用后才创建新 revision。
 */
import { confirmAsync } from "../shared/confirmAsync.js"
import { renderWorkflowCard } from "../shared/progressRenderer.js"
import { bindWorkspaceClick, renderLoadingSkeleton } from "../shared/viewHelper.js"
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "../shared/workflowProgress.js"

const STORY_OUTLINE_TASK_TYPE = "story_outline_generate"
const STORY_OUTLINE_ACTION = "outline.story_outline.generate"
const HISTORY_LIMIT = 20

const SOURCE_LABELS = {
  manual: "手工创建",
  ai_generated: "AI 生成后采用",
  restored: "从历史版本采用",
}

const ARRAY_FIELD_LABELS = {
  major_storylines: "主要剧情线",
  macro_movements: "宏观推进",
  open_decisions: "开放决策",
}
const STORY_OUTLINE_CONTENT_FIELDS = [
  "title",
  "creative_core",
  "outline_markdown",
  "major_storylines",
  "macro_movements",
  "open_decisions",
]

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function idempotencyKey() {
  const token = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return `story-outline-${token}`.slice(0, 128)
}

function itemId(item) {
  return item?.entity_id || item?.id || null
}

function itemName(item, fallback) {
  return item?.name || item?.title || fallback
}

function assertPlainObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}必须是 JSON 对象`)
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
  if (!Array.isArray(value)) throw new Error(`${label}必须是 JSON 数组`)
  return value.map((item, index) => requiredText(item, `${label}第 ${index + 1} 项`))
}

function validateStoryOutlineContent(raw) {
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

  if (!Array.isArray(content.major_storylines)) throw new Error("主要剧情线必须是 JSON 数组")
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

  if (!Array.isArray(content.macro_movements)) throw new Error("宏观推进必须是 JSON 数组")
  content.macro_movements = content.macro_movements.map((item, index) => {
    const label = `宏观推进第 ${index + 1} 项`
    assertExactKeys(item, ["name", "story_state_change", "advanced_storylines"], label)
    const advanced = stringList(item.advanced_storylines, `${label}推进剧情线`)
    return {
      name: requiredText(item.name, `${label}名称`),
      story_state_change: requiredText(item.story_state_change, `${label}状态变化`),
      advanced_storylines: advanced,
    }
  })
  if (!Array.isArray(content.open_decisions)) throw new Error("开放决策必须是 JSON 数组")
  content.open_decisions = content.open_decisions.map((item, index) => {
    const label = `开放决策第 ${index + 1} 项`
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

function validateStoryOutlineTaskResult(raw) {
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

function emptyContent() {
  return {
    title: "",
    creative_core: {
      premise: "",
      tone_and_reader_promise: "",
      story_engine: "",
      ending_direction: null,
    },
    outline_markdown: "",
    major_storylines: [],
    macro_movements: [],
    open_decisions: [],
  }
}

const storyOutlineView = {
  _projectId: null,
  _lifecycle: 0,
  _loading: false,
  _loadError: null,
  _assetLoadError: null,
  _current: null,
  _history: [],
  _historyTotal: 0,
  _characters: [],
  _entities: [],
  _taskId: null,
  _taskMeta: null,
  _taskProgress: null,
  _taskPoller: null,
  _taskNotice: null,
  _cancelPending: false,
  _preview: null,
  _applyError: null,
  _restoreKeys: {},

  async onEnter() {
    const projectId = state.currentProjectId
    const lifecycle = ++this._lifecycle
    this._stopTaskPolling()
    if (this._projectId !== projectId) this._resetProjectState()
    this._projectId = projectId || null
    this._loading = Boolean(projectId)
    this._loadError = null
    this._assetLoadError = null

    if (!projectId) {
      this._loading = false
      return
    }

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
    if (!this._scopeIsCurrent(projectId, lifecycle)) return

    if (currentResult.status === "fulfilled" && historyResult.status === "fulfilled") {
      this._current = currentResult.value || { current_revision_id: null, revision: null }
      this._history = historyResult.value?.items || []
      this._historyTotal = Number(historyResult.value?.total ?? this._history.length) || 0
    } else {
      const reason = currentResult.status === "rejected"
        ? currentResult.reason
        : historyResult.reason
      this._loadError = reason?.message || "小说总纲加载失败"
      this._current = null
      this._history = []
      this._historyTotal = 0
    }

    this._characters = charactersResult.status === "fulfilled"
      ? charactersResult.value?.items || charactersResult.value || []
      : []
    this._entities = entitiesResult.status === "fulfilled"
      ? entitiesResult.value?.items || entitiesResult.value || []
      : []
    if (charactersResult.status === "rejected" || entitiesResult.status === "rejected") {
      this._assetLoadError = "可选人物或世界对象未完全加载，仍可不选资产直接生成。"
    }

    this._loading = false
    this._recoverTask(projectId)
  },

  onLeave() {
    this._lifecycle += 1
    this._stopTaskPolling()
  },

  onActivate() {
    this._bindEvents()
    if (
      this._taskId
      && !this._taskPoller
      && this._taskProgress
      && !this._taskProgress.terminal
      && this._projectId === state.currentProjectId
    ) {
      this._startTaskPolling(this._taskId, this._projectId)
    }
  },

  onDeactivate() {
    this._stopTaskPolling()
  },

  _resetProjectState() {
    this._stopTaskPolling()
    this._current = null
    this._history = []
    this._historyTotal = 0
    this._characters = []
    this._entities = []
    this._taskId = null
    this._taskMeta = null
    this._taskProgress = null
    this._taskNotice = null
    this._cancelPending = false
    this._preview = null
    this._applyError = null
    this._restoreKeys = {}
  },

  _scopeIsCurrent(projectId, lifecycle = this._lifecycle) {
    return (
      this._projectId === projectId
      && state.currentProjectId === projectId
      && lifecycle === this._lifecycle
    )
  },

  _currentRevision() {
    return this._current?.revision || null
  },

  async render() {
    if (!state.currentProjectId) {
      return '<div class="empty-state"><p>请先选择项目。</p></div>'
    }
    if (this._loading) return renderLoadingSkeleton("小说总纲加载中...")
    if (this._loadError) {
      return `
        <div class="empty-state" role="alert">
          <div class="empty-icon">!</div>
          <p>小说总纲加载失败</p>
          <p class="outline-empty-detail">${esc(this._loadError)}</p>
          <button class="btn btn-sm" data-action="reload-story-outline">重新加载</button>
        </div>
      `
    }

    return `
      <div class="story-outline-workspace">
        <section class="card" aria-labelledby="story-outline-intro-title">
          <div class="section-header">
            <div>
              <h2 id="story-outline-intro-title">小说总纲</h2>
              <p class="form-hint">位于世界设定之后、正式写作之前，用于设计至少覆盖半部小说的高层方向。
              采用总纲只会创建新的总纲 revision，不会创建篇章纲、剧情线或 Scene。</p>
            </div>
            <div class="view-header__actions">
              <button class="btn btn-sm" data-action="edit-story-outline">${this._currentRevision() ? "编辑为新版本" : "手工创建"}</button>
              <button class="btn btn-sm btn-primary" data-action="generate-story-outline" ${this._taskProgress && !this._taskProgress.terminal ? "disabled" : ""}>AI 生成总纲</button>
              <button class="btn btn-sm btn-ghost" data-action="reload-story-outline">重新加载</button>
            </div>
          </div>
          ${this._assetLoadError ? `<p class="form-error" role="status">${esc(this._assetLoadError)}</p>` : ""}
          ${this._taskNotice ? `<p class="form-error" role="alert">${esc(this._taskNotice)}</p>` : ""}
        </section>
        ${this._renderTask()}
        ${this._preview ? this._renderEditor(this._preview.content, "story-outline-preview", {
          title: "AI 总纲完整预览",
          hint: "生成结果尚未写入总纲。所有字段都可编辑；只有点击“采用为新版本”才会写入。",
          actions: `
            <button class="btn btn-sm btn-primary" data-action="apply-story-outline-preview">采用为新版本</button>
            <button class="btn btn-sm btn-ghost" data-action="discard-story-outline-preview">放弃此建议</button>
          `,
          error: this._applyError,
        }) : ""}
        ${this._renderCurrent()}
        ${this._renderHistory()}
      </div>
    `
  },

  onRendered() {
    this._bindEvents()
  },

  _renderTask() {
    if (!this._taskProgress) return ""
    const canCancel = !this._taskProgress.terminal
      && this._taskProgress.availableActions?.includes("cancel")
    const actionsHtml = canCancel
      ? `<button class="btn btn-sm btn-ghost" data-action="cancel-story-outline-task" ${this._cancelPending ? "disabled" : ""}>${this._cancelPending ? "取消中..." : "取消生成"}</button>`
      : this._taskProgress.terminal && !this._preview
        ? '<button class="btn btn-sm btn-ghost" data-action="dismiss-story-outline-task">关闭任务</button>'
        : ""
    return `<section class="outline-progress-card-wrap">${renderWorkflowCard(this._taskProgress, {
      title: "AI 小说总纲",
      destinationLabel: "完成后先进入可编辑预览",
      attentionRequired: Boolean(this._taskProgress.failed || this._taskProgress.stateUnknown),
      actionsHtml: actionsHtml ? `<div class="workflow-progress__actions">${actionsHtml}</div>` : "",
    })}</section>`
  },

  _renderCurrent() {
    const revision = this._currentRevision()
    if (!revision) {
      return `
        <section class="empty-state" aria-labelledby="story-outline-empty-title">
          <div class="empty-icon">&#128209;</div>
          <h3 id="story-outline-empty-title">尚未创建小说总纲</h3>
          <p>可以手工创建，也可以让 AI 生成一份完整可编辑的预览。</p>
        </section>
      `
    }
    return `
      <section class="card" aria-labelledby="story-outline-current-title">
        <div class="section-header">
          <div>
            <h3 id="story-outline-current-title">当前总纲 · v${esc(revision.version_number)}</h3>
            <p class="form-hint">${esc(SOURCE_LABELS[revision.source] || revision.source || "未知来源")} · ${esc(this._formatDate(revision.created_at))}</p>
          </div>
        </div>
        ${this._renderContentReadOnly(revision)}
      </section>
    `
  },

  _renderContentReadOnly(content) {
    const core = content?.creative_core || {}
    const storylineHtml = (content?.major_storylines || []).map((item) => `
      <article class="card">
        <h5>${esc(item.name)}</h5>
        <p><strong>叙事功能：</strong>${esc(item.narrative_function)}</p>
        <p><strong>轨迹：</strong>${esc(item.trajectory)}</p>
        <p><strong>交汇点：</strong>${esc((item.intersections || []).join("、") || "暂无")}</p>
        <p><strong>收束方向：</strong>${esc(item.resolution_direction)}</p>
      </article>
    `).join("")
    const movementHtml = (content?.macro_movements || []).map((item) => `
      <article class="card">
        <h5>${esc(item.name)}</h5>
        <p>${esc(item.story_state_change)}</p>
        <p><strong>推进剧情线：</strong>${esc((item.advanced_storylines || []).join("、") || "暂无")}</p>
      </article>
    `).join("")
    const decisionHtml = (content?.open_decisions || []).map((item) => `
      <article class="card">
        <h5>${esc(item.question)}</h5>
        <p>${esc(item.why_it_matters)}</p>
        <p><strong>可选方向：</strong>${esc((item.options || []).join("、") || "暂无")}</p>
      </article>
    `).join("")
    return `
      <section><h4>${esc(content?.title)}</h4></section>
      <div class="form-grid form-grid--2">
        <div class="card"><h4>核心前提</h4><p>${esc(core.premise)}</p></div>
        <div class="card"><h4>基调与读者承诺</h4><p>${esc(core.tone_and_reader_promise)}</p></div>
        <div class="card"><h4>故事引擎</h4><p>${esc(core.story_engine)}</p></div>
        <div class="card"><h4>结局方向</h4><p>${esc(core.ending_direction || "待决定")}</p></div>
      </div>
      <section><h4>高层总纲</h4><pre class="generate-markdown-pre">${esc(content?.outline_markdown)}</pre></section>
      <section><h4>主要剧情线</h4>${storylineHtml || '<p class="form-hint">暂无。</p>'}</section>
      <section><h4>宏观推进</h4>${movementHtml || '<p class="form-hint">暂无。</p>'}</section>
      <section><h4>开放决策</h4>${decisionHtml || '<p class="form-hint">暂无。</p>'}</section>
    `
  },

  _renderHistory() {
    const items = this._history.map((revision) => {
      const current = revision.id === this._current?.current_revision_id || revision.is_current
      const restored = revision.restored_from_revision_id
        ? ` · 来自历史 revision ${revision.restored_from_revision_id}`
        : ""
      return `
        <li class="card">
          <div class="section-header">
            <div>
              <strong>v${esc(revision.version_number)} · ${esc(revision.title)}</strong>
              <p class="form-hint">${esc(SOURCE_LABELS[revision.source] || revision.source || "未知来源")} · ${esc(this._formatDate(revision.created_at))}${esc(restored)}</p>
            </div>
            <div class="view-header__actions">
              ${current ? '<span class="badge badge-success">当前版本</span>' : ""}
              <button class="btn btn-sm" data-action="view-story-outline-revision" data-id="${esc(revision.id)}">查看</button>
              <button class="btn btn-sm btn-primary" data-action="restore-story-outline-revision" data-id="${esc(revision.id)}" ${current ? "disabled" : ""}>采用为新版本</button>
            </div>
          </div>
        </li>
      `
    }).join("")
    return `
      <section class="card" aria-labelledby="story-outline-history-title">
        <div class="section-header">
          <div>
            <h3 id="story-outline-history-title">修订历史 · ${esc(this._historyTotal)}</h3>
            <p class="form-hint">采用历史内容会复制其内容并创建更高版本号的新 revision，不会原地回滚或改写历史。</p>
          </div>
        </div>
        ${items ? `<ul class="item-list">${items}</ul>` : '<p class="form-hint">还没有历史版本。</p>'}
      </section>
    `
  },

  _renderEditor(content, prefix, { title, hint, actions = "", error = null } = {}) {
    const core = content?.creative_core || {}
    return `
      <section class="card" aria-labelledby="${esc(prefix)}-title">
        <div class="section-header">
          <div><h3 id="${esc(prefix)}-title">${esc(title)}</h3><p class="form-hint">${esc(hint)}</p></div>
        </div>
        <div class="form-group">
          <label for="${esc(prefix)}-title-input">标题</label>
          <input class="form-input" id="${esc(prefix)}-title-input" value="${esc(content?.title)}" />
        </div>
        <div class="form-grid form-grid--2">
          ${this._textarea(`${prefix}-premise`, "核心前提", core.premise)}
          ${this._textarea(`${prefix}-tone`, "基调与读者承诺", core.tone_and_reader_promise)}
          ${this._textarea(`${prefix}-engine`, "故事引擎", core.story_engine)}
          ${this._textarea(`${prefix}-ending`, "结局方向（可留空）", core.ending_direction || "")}
        </div>
        ${this._textarea(`${prefix}-markdown`, "高层总纲（Markdown）", content?.outline_markdown, 14)}
        <div class="form-group">
          <label for="${esc(prefix)}-major-storylines">主要剧情线（JSON 数组）</label>
          <p class="form-hint">每项字段：name、narrative_function、trajectory、intersections 字符串数组、resolution_direction。可以是 []。</p>
          <textarea class="form-textarea" id="${esc(prefix)}-major-storylines" rows="12">${esc(JSON.stringify(content?.major_storylines || [], null, 2))}</textarea>
        </div>
        <div class="form-group">
          <label for="${esc(prefix)}-macro-movements">宏观推进（JSON 数组）</label>
          <p class="form-hint">每项字段：name、story_state_change、advanced_storylines 字符串数组；它们是浏览导航摘要，不作为数据库关联键。可以是 []。</p>
          <textarea class="form-textarea" id="${esc(prefix)}-macro-movements" rows="10">${esc(JSON.stringify(content?.macro_movements || [], null, 2))}</textarea>
        </div>
        <div class="form-group">
          <label for="${esc(prefix)}-open-decisions">开放决策（JSON 数组）</label>
          <p class="form-hint">每项字段：question、why_it_matters、options 字符串数组。可以是 []。</p>
          <textarea class="form-textarea" id="${esc(prefix)}-open-decisions" rows="10">${esc(JSON.stringify(content?.open_decisions || [], null, 2))}</textarea>
        </div>
        <p id="story-outline-apply-error" class="form-error" role="alert">${esc(error || "")}</p>
        ${actions ? `<div class="form-actions">${actions}</div>` : ""}
      </section>
    `
  },

  _textarea(id, label, value, rows = 5) {
    return `
      <div class="form-group">
        <label for="${esc(id)}">${esc(label)}</label>
        <textarea class="form-textarea" id="${esc(id)}" rows="${esc(rows)}">${esc(value)}</textarea>
      </div>
    `
  },

  _collectEditor(prefix) {
    const read = (suffix) => document.getElementById(`${prefix}-${suffix}`)?.value ?? ""
    const arrays = {}
    for (const field of Object.keys(ARRAY_FIELD_LABELS)) {
      const suffix = field.replaceAll("_", "-")
      try {
        arrays[field] = JSON.parse(read(suffix))
      } catch {
        throw new Error(`${ARRAY_FIELD_LABELS[field]} JSON 格式错误`)
      }
    }
    return validateStoryOutlineContent({
      title: read("title-input"),
      creative_core: {
        premise: read("premise"),
        tone_and_reader_promise: read("tone"),
        story_engine: read("engine"),
        ending_direction: read("ending"),
      },
      outline_markdown: read("markdown"),
      ...arrays,
    })
  },

  _assetCheckboxes(items, name, fallback) {
    return items.map((item) => {
      const id = itemId(item)
      if (!id) return ""
      return `
        <label class="checkbox-label">
          <input type="checkbox" name="${esc(name)}" value="${esc(id)}" />
          <span>${esc(itemName(item, fallback))}</span>
        </label>
      `
    }).join("")
  },

  _showGenerateForm() {
    if (this._taskProgress && !this._taskProgress.terminal) {
      toast("已有小说总纲生成任务正在运行", "info")
      return
    }
    const includeCurrent = Boolean(this._currentRevision())
    const html = `
      <div class="form-group">
        <label for="story-outline-author-intent">作者意图</label>
        <textarea class="form-textarea" id="story-outline-author-intent" rows="5" placeholder="你想写一个怎样的长篇故事？"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-planned-scale">计划尺度</label>
        <textarea class="form-textarea" id="story-outline-planned-scale" rows="3" placeholder="例如：长篇、三部、预计百万字"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-coverage">覆盖描述</label>
        <textarea class="form-textarea" id="story-outline-coverage" rows="3" placeholder="例如：覆盖全书，重点先锁定前两部的方向"></textarea>
      </div>
      <fieldset class="form-group">
        <legend>可选人物（可为空；为空时自动取 Top-K，最多显式选择 12 个）</legend>
        <div class="checkbox-list">${this._assetCheckboxes(this._characters, "story-outline-character", "未命名人物") || '<span class="form-hint">暂无可选人物。</span>'}</div>
      </fieldset>
      <fieldset class="form-group">
        <legend>可选世界对象（可为空；为空时自动取 Top-K，最多显式选择 24 个）</legend>
        <div class="checkbox-list">${this._assetCheckboxes(this._entities, "story-outline-entity", "未命名对象") || '<span class="form-hint">暂无可选世界对象。</span>'}</div>
      </fieldset>
      ${includeCurrent ? `
        <label class="checkbox-label form-group">
          <input type="checkbox" id="story-outline-include-current" />
          <span>把当前总纲纳入本次生成参考</span>
        </label>
      ` : ""}
      <p class="form-hint">AI 不会预先创建篇章纲或 Scene，也不会自动采用结果。</p>
    `
    showModalHtml("AI 生成小说总纲", html, [{
      text: "生成可编辑预览",
      class: "btn-primary",
      handler: () => this._submitGeneration(),
    }], { size: "large" })
  },

  async _submitGeneration() {
    const projectId = this._projectId
    const authorIntent = document.getElementById("story-outline-author-intent")?.value?.trim() || ""
    const plannedScale = document.getElementById("story-outline-planned-scale")?.value?.trim() || ""
    const coverage = document.getElementById("story-outline-coverage")?.value?.trim() || ""
    if (!authorIntent || !plannedScale || !coverage) {
      toast("请完整填写作者意图、计划尺度和覆盖描述", "warning")
      return false
    }
    const selectedCharacterIds = [...document.querySelectorAll('input[name="story-outline-character"]:checked')]
      .map((input) => input.value)
    const selectedEntityIds = [...document.querySelectorAll('input[name="story-outline-entity"]:checked')]
      .map((input) => input.value)
    if (selectedCharacterIds.length > 12 || selectedEntityIds.length > 24) {
      toast("人物最多选 12 个，世界对象最多选 24 个", "warning")
      return false
    }
    const includeCurrent = Boolean(document.getElementById("story-outline-include-current")?.checked)
    const baseRevisionId = this._current?.current_revision_id || null
    const applyKey = idempotencyKey()
    try {
      const response = await api.outline.generateStoryOutline({
        novel_id: projectId,
        author_intent: authorIntent,
        planned_scale: plannedScale,
        coverage,
        selected_character_ids: selectedCharacterIds,
        selected_entity_ids: selectedEntityIds,
        include_current_outline: includeCurrent,
      })
      if (!response?.task_id) throw new Error("生成任务未返回任务编号")
      const meta = {
        project_id: projectId,
        novel_id: projectId,
        action: STORY_OUTLINE_ACTION,
        apply_base_revision_id: baseRevisionId,
        apply_idempotency_key: applyKey,
      }
      persistActiveWorkflow({
        taskId: response.task_id,
        workflowType: STORY_OUTLINE_TASK_TYPE,
        label: "AI 小说总纲",
        projectId,
        view: "outline",
        meta,
      })
      if (state.currentProjectId !== projectId || this._projectId !== projectId) return true
      this._taskId = response.task_id
      this._taskMeta = meta
      this._taskNotice = null
      this._preview = null
      this._applyError = null
      this._taskProgress = normalizeTaskProgress({
        ...response,
        task_type: STORY_OUTLINE_TASK_TYPE,
        meta,
      }, STORY_OUTLINE_TASK_TYPE)
      closeModal()
      toast("小说总纲生成任务已提交", "success")
      this._startTaskPolling(response.task_id, projectId)
      router.renderCurrentView()
      return true
    } catch (err) {
      toast(err.message || "提交生成任务失败", "error")
      return false
    }
  },

  _recoverTask(projectId) {
    if (this._preview || this._taskPoller) return
    const workflow = recoverActiveWorkflows(projectId)
      .filter((item) => (
        item.workflowType === STORY_OUTLINE_TASK_TYPE
        && item.projectId === projectId
        && item.meta?.action === STORY_OUTLINE_ACTION
        && item.meta?.novel_id === projectId
      ))
      .sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0]
    if (!workflow?.taskId) return
    this._taskId = workflow.taskId
    this._taskMeta = { ...(workflow.meta || {}) }
    this._taskProgress = normalizeTaskProgress({
      task_id: workflow.taskId,
      task_type: STORY_OUTLINE_TASK_TYPE,
      status: "pending",
      meta: workflow.meta || {},
    }, STORY_OUTLINE_TASK_TYPE)
    this._startTaskPolling(workflow.taskId, projectId)
  },

  _taskMatches(task, projectId) {
    if (!task) return true
    return (
      task.task_type === STORY_OUTLINE_TASK_TYPE
      && task.meta?.action === STORY_OUTLINE_ACTION
      && task.meta?.novel_id === projectId
    )
  },

  _rejectRecoveredTask(taskId, message) {
    this._stopTaskPolling()
    clearActiveWorkflow(taskId)
    if (this._taskId === taskId) {
      this._taskId = null
      this._taskMeta = null
      this._taskProgress = null
      this._preview = null
      this._taskNotice = message
    }
    if (state.currentProjectId === this._projectId) router.renderCurrentView()
  },

  _startTaskPolling(taskId, projectId) {
    this._stopTaskPolling()
    this._taskPoller = pollTaskProgress({
      taskId,
      workflowType: STORY_OUTLINE_TASK_TYPE,
      novelId: projectId,
      apiClient: api,
      onUpdate: (progress, task) => {
        if (!this._scopeIsCurrent(projectId) || this._taskId !== taskId) return
        if (!this._taskMatches(task, projectId)) {
          this._rejectRecoveredTask(taskId, "恢复记录与当前项目或小说总纲生成动作不匹配，已停止恢复。")
          return
        }
        if (progress.stateUnknown && /(不存在|not found)/i.test(progress.errorMessage || "")) {
          this._rejectRecoveredTask(taskId, "原小说总纲生成任务已过期或被清理，请重新生成。")
          return
        }
        this._taskProgress = progress
        router.renderCurrentView()
      },
      onDone: (progress, task) => {
        if (!this._scopeIsCurrent(projectId) || this._taskId !== taskId) return
        if (!this._taskMatches(task, projectId)) {
          this._rejectRecoveredTask(taskId, "任务结果与当前项目或小说总纲生成动作不匹配，未加载预览。")
          return
        }
        this._taskPoller = null
        this._taskProgress = progress
        if (task?.result?.apply_status === "applied") {
          clearActiveWorkflow(taskId)
          this._taskId = null
          this._taskMeta = null
          this._preview = null
          this._taskNotice = "这份小说总纲预览已经采用，无需重复采用。"
          router.renderCurrentView()
          return
        }
        try {
          const content = validateStoryOutlineTaskResult(task?.result || {})
          this._preview = {
            taskId,
            content: clone(content),
            baseRevisionId: this._taskMeta?.apply_base_revision_id || null,
            idempotencyKey: this._taskMeta?.apply_idempotency_key || idempotencyKey(),
          }
          this._applyError = null
          toast("小说总纲建议已生成，请编辑后明确采用", "success")
        } catch (err) {
          clearActiveWorkflow(taskId)
          this._taskId = null
          this._taskMeta = null
          this._preview = null
          this._taskNotice = `任务已完成，但返回内容不符合总纲格式：${err.message}`
        }
        router.renderCurrentView()
      },
      onFailed: (progress) => {
        if (!this._scopeIsCurrent(projectId) || this._taskId !== taskId) return
        this._taskPoller = null
        this._cancelPending = false
        this._taskProgress = progress
        this._taskNotice = progress.cancelled
          ? "小说总纲生成已取消，没有创建 revision。"
          : `小说总纲生成失败：${progress.errorMessage || "未知错误"}`
        router.renderCurrentView()
      },
    })
  },

  _stopTaskPolling() {
    this._taskPoller?.stop?.()
    this._taskPoller = null
  },

  async _cancelTask() {
    const taskId = this._taskId
    const projectId = this._projectId
    if (!taskId || !projectId || this._cancelPending) return false
    const confirmed = await confirmAsync(
      "确认取消当前小说总纲生成任务？未采用的预览不会写入。",
      "确认取消",
    )
    if (!confirmed) return false
    this._stopTaskPolling()
    this._cancelPending = true
    router.renderCurrentView()
    try {
      await api.tasks.cancel(taskId, projectId)
      if (this._taskId !== taskId || this._projectId !== projectId) return true
      this._cancelPending = false
      this._taskProgress = normalizeTaskProgress({
        task_id: taskId,
        task_type: STORY_OUTLINE_TASK_TYPE,
        status: "cancelled",
        result: { message: "任务已取消" },
        meta: this._taskMeta || {},
      }, STORY_OUTLINE_TASK_TYPE)
      this._taskNotice = "小说总纲生成已取消，没有创建 revision。"
      router.renderCurrentView()
      return true
    } catch (err) {
      if (this._taskId === taskId && this._projectId === projectId) {
        this._cancelPending = false
        this._startTaskPolling(taskId, projectId)
      }
      toast(err.message || "取消任务失败", "error")
      return false
    }
  },

  _dismissTask() {
    if (this._taskId) clearActiveWorkflow(this._taskId)
    this._stopTaskPolling()
    this._taskId = null
    this._taskMeta = null
    this._taskProgress = null
    this._taskNotice = null
    this._cancelPending = false
    router.renderCurrentView()
  },

  async _applyPreview() {
    if (!this._preview) return false
    const projectId = this._projectId
    if (state.currentProjectId !== projectId) {
      this._setApplyError("项目已切换，请回到原项目后重新加载总纲。")
      return false
    }
    try {
      const content = this._collectEditor("story-outline-preview")
      const attemptFingerprint = JSON.stringify({
        task_id: this._preview.taskId,
        base_revision_id: this._preview.baseRevisionId,
        content,
      })
      if (
        this._preview.lastApplyFingerprint
        && this._preview.lastApplyFingerprint !== attemptFingerprint
      ) {
        this._preview.idempotencyKey = idempotencyKey()
      }
      this._preview.lastApplyFingerprint = attemptFingerprint
      const response = await api.outline.applyStoryOutlinePreview({
        novel_id: projectId,
        source_task_id: this._preview.taskId,
        ...content,
        base_revision_id: this._preview.baseRevisionId,
        idempotency_key: this._preview.idempotencyKey,
        confirmed: true,
      })
      clearActiveWorkflow(this._preview.taskId)
      this._taskId = null
      this._taskMeta = null
      this._taskProgress = null
      this._preview = null
      this._applyError = null
      toast(`小说总纲已采用为新版本 v${response?.version_number || ""}`, "success")
      await this.onEnter()
      router.renderCurrentView()
      return response
    } catch (err) {
      const message = err?.status === 409
        ? "当前总纲已在其他会话中变更，请重新加载后再生成或采用。"
        : err.message || "采用小说总纲失败"
      this._setApplyError(message)
      toast(message, "error")
      return false
    }
  },

  _setApplyError(message) {
    this._applyError = message
    const element = document.getElementById("story-outline-apply-error")
    if (element) element.textContent = message
  },

  async _discardPreview() {
    if (!this._preview) return
    const confirmed = await confirmAsync(
      "确认放弃这份尚未采用的小说总纲建议？",
      "放弃建议",
    )
    if (!confirmed) return
    clearActiveWorkflow(this._preview.taskId)
    this._taskId = null
    this._taskMeta = null
    this._taskProgress = null
    this._preview = null
    this._applyError = null
    router.renderCurrentView()
  },

  _showManualEditor() {
    const projectId = this._projectId
    const baseRevisionId = this._current?.current_revision_id || null
    const key = idempotencyKey()
    const content = this._currentRevision() ? clone(this._currentRevision()) : emptyContent()
    const html = this._renderEditor(content, "story-outline-manual", {
      title: this._currentRevision() ? "编辑小说总纲为新版本" : "手工创建小说总纲",
      hint: "保存会创建不可变 revision，不会覆盖当前或历史版本。",
    })
    showModalHtml("编辑小说总纲", html, [{
      text: "保存为新版本",
      class: "btn-primary",
      handler: async () => {
        if (state.currentProjectId !== projectId || this._projectId !== projectId) {
          toast("项目已切换，请在当前项目重新打开编辑器", "warning")
          return false
        }
        try {
          const response = await api.outline.createStoryOutlineRevision(projectId, {
            ...this._collectEditor("story-outline-manual"),
            base_revision_id: baseRevisionId,
            idempotency_key: key,
            source: "manual",
            provenance: { actor: "author", note: "前端手工保存" },
          })
          closeModal()
          toast(`小说总纲已保存为新版本 v${response?.version_number || ""}`, "success")
          await this.onEnter()
          router.renderCurrentView()
          return true
        } catch (err) {
          const message = err?.status === 409
            ? "当前总纲已变更，请关闭编辑器并重新加载后再编辑。"
            : err.message || "保存失败"
          toast(message, "error")
          return false
        }
      },
    }], { size: "full", protectUnsaved: true })
  },

  async _viewRevision(revisionId) {
    const projectId = this._projectId
    try {
      const revision = await api.outline.getStoryOutlineRevision(revisionId, projectId)
      if (state.currentProjectId !== projectId || this._projectId !== projectId) return
      showModalHtml(
        `小说总纲历史版本 v${revision.version_number}`,
        this._renderContentReadOnly(revision),
        [{ text: "关闭", class: "btn-ghost", handler: closeModal }],
        { size: "full" },
      )
    } catch (err) {
      toast(err.message || "加载历史版本失败", "error")
    }
  },

  async _restoreRevision(revisionId) {
    const projectId = this._projectId
    const confirmed = await confirmAsync(
      "确认采用该历史内容？系统会创建一个新 revision，不会原地回滚或改写历史。",
      "采用为新版本",
    )
    if (!confirmed) return false
    const key = this._restoreKeys[revisionId] || idempotencyKey()
    this._restoreKeys[revisionId] = key
    try {
      const response = await api.outline.restoreStoryOutlineRevision(revisionId, projectId, {
        base_revision_id: this._current?.current_revision_id || null,
        idempotency_key: key,
        confirmed: true,
        provenance: { actor: "author", note: "前端显式采用历史内容" },
      })
      delete this._restoreKeys[revisionId]
      toast(`历史内容已采用为新版本 v${response?.version_number || ""}`, "success")
      await this.onEnter()
      router.renderCurrentView()
      return response
    } catch (err) {
      const message = err?.status === 409
        ? "当前总纲已变更，请重新加载历史后再采用。"
        : err.message || "采用历史内容失败"
      toast(message, "error")
      this._taskNotice = message
      router.renderCurrentView()
      return false
    }
  },

  async _reload() {
    this._applyError = null
    this._taskNotice = null
    const previewTaskId = this._preview?.taskId || null
    if (previewTaskId && document.getElementById("story-outline-preview-title-input")) {
      try {
        this._preview.content = this._collectEditor("story-outline-preview")
      } catch (err) {
        this._setApplyError(err.message || "预览格式有误，请修正后再重新加载。")
        return false
      }
    }
    await this.onEnter()
    if (previewTaskId && this._preview?.taskId === previewTaskId) {
      const nextBaseRevisionId = this._current?.current_revision_id || null
      if (this._preview.baseRevisionId !== nextBaseRevisionId) {
        this._preview.baseRevisionId = nextBaseRevisionId
        this._preview.idempotencyKey = idempotencyKey()
        this._preview.lastApplyFingerprint = null
      }
    }
    router.renderCurrentView()
    return true
  },

  _formatDate(value) {
    if (!value) return "时间未知"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN")
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "nav-story-outline": () => router.navigate("outline", "story-outline"),
      "nav-arcs": () => router.navigate("outline", "arcs"),
      "nav-threads": () => router.navigate("outline", "threads"),
      "nav-scenes": () => router.navigate("outline", "scenes"),
      "nav-foreshadowing": () => router.navigate("outline", "foreshadowing"),
      "nav-reveals": () => router.navigate("outline", "reveals"),
      "reload-story-outline": () => this._reload(),
      "edit-story-outline": () => this._showManualEditor(),
      "generate-story-outline": () => this._showGenerateForm(),
      "cancel-story-outline-task": () => this._cancelTask(),
      "dismiss-story-outline-task": () => this._dismissTask(),
      "apply-story-outline-preview": () => this._applyPreview(),
      "discard-story-outline-preview": () => this._discardPreview(),
      "view-story-outline-revision": (_event, _target, context) => context.id && this._viewRevision(context.id),
      "restore-story-outline-revision": (_event, _target, context) => context.id && this._restoreRevision(context.id),
    })
  },
}

export { validateStoryOutlineContent, validateStoryOutlineTaskResult }
export default storyOutlineView
