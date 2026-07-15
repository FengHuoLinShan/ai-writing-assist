/**
 * 生成中心视图 — 自由共创 Chatbox + 数据库草稿生成 + 任务上下文编译
 */

import { confirmAiReference } from "../shared/aiReferenceModal.js"
import { bindWorkspaceClick } from "../shared/viewHelper.js"
import { worldAssetDisplay } from "../shared/assetDisplayState.js"
import { renderWorkspaceRail, workspaceRailKey } from "../shared/workspaceRail.js"

const BUILTIN_TEMPLATE_PROMPTS = {
  none: "不预设固定创作框架。围绕作者真正想创造或解决的内容，找出这个对象最核心的概念、辨识度，以及它与现有世界和故事的关系。允许对象暂时跨越多个类别或尚未完成分类，不要套用人物、事件、物品等模板的固定维度。最终先收束为概念建议，作者可在采用前调整类型。",
  character: "把人物设计成一个会作出选择、影响他人并改变局势的人，而不是属性集合。优先理解这个人物在当前故事中追求什么、受到什么阻力、如何作出选择，以及其行为逻辑和重要关系。外貌、能力、恐惧、秘密、声音风格、过去经历等，只发展对当前人物真正有帮助的部分。不要强制人物拥有悲惨过去、隐藏身份、反转或完整人物卡，也不要用性格标签代替具体的行为逻辑。",
  event: "把事件设计成一次具有因果关系的状态变化，而不是静态事件说明。优先理解事件发生前后的差异、推动变化的力量、参与者作出的关键选择，以及它对相关人物和世界产生的实际影响。起因、过程、结果、公开解释、隐藏原因和后续影响只按当前事件需要发展。事件可以失败、中断、持续发酵或仅仅巩固现状；不要强制加入阴谋、隐藏真相、反转或后续钩子。",
  item: "把物品设计成会被使用、保存、争夺、交换或传承的世界组成部分。优先理解人们为什么在意它、它能够或不能做什么、使用和持有它会带来什么，以及它与人物、地点、组织或历史的关系。外观、来源、能力、限制、代价、秘密和风险只按当前物品需要发展。不要默认物品具有超自然能力、诅咒、秘密来源或失控风险。",
  location: "把地点设计成会塑造行动、生活和关系的空间，而不是景观资料表。优先理解空间如何组织、人在其中如何行动和感受、谁能够进入或控制它，以及它为什么在当前世界中存在。历史、资源、危险、势力归属、秘密区域和进入条件只按当前地点需要发展。不要强制每个地点都有危险、秘密区域、特殊资源或剧情任务。",
  faction: "把组织设计成能够持续作出决策和采取行动的集体，而不是组织架构图。优先理解它为什么存在、如何获得资源和合法性、谁能够影响决策、内部如何合作或分裂，以及它实际能够做什么、不能做什么。成员、层级、公开形象、隐藏目标和外部关系只按当前组织需要发展。不要强制组织拥有秘密目标、宿敌、阴谋或完整层级体系。",
  rule: "把规则设计成稳定影响世界运行、人物选择和行为后果的机制，而不是术语密集的说明书。优先理解它约束什么、角色如何认识或验证它、违反或利用它会发生什么，以及它如何改变真实的选择空间。适用范围、限制、代价、边界情况、例外和普遍误解只按当前规则需要发展。不要为了制造戏剧性而强行增加漏洞、例外、代价或伪科学解释；规则应当足够一致，但不要求解释超出故事实际需要的细节。",
}

const TEMPLATE_TYPE_OPTIONS = [
  "none",
  "character",
  "event",
  "item",
  "location",
  "faction",
  "rule",
  "custom",
]

const OBJECT_TEMPLATES = [
  { value: "none", label: "不带模板", hint: "自由构思，先作为概念建议收束，采用前可调整类型", prompt: BUILTIN_TEMPLATE_PROMPTS.none },
  { value: "character", label: "人物", hint: "具有欲望、选择与关系的人物", prompt: BUILTIN_TEMPLATE_PROMPTS.character },
  { value: "event", label: "事件", hint: "改变局势或维持秩序的发生过程", prompt: BUILTIN_TEMPLATE_PROMPTS.event },
  { value: "item", label: "物品", hint: "被使用、争夺、保存或传承的物品", prompt: BUILTIN_TEMPLATE_PROMPTS.item },
  { value: "location", label: "地点", hint: "承载行动与生活的空间", prompt: BUILTIN_TEMPLATE_PROMPTS.location },
  { value: "faction", label: "组织", hint: "能够持续行动与决策的集体", prompt: BUILTIN_TEMPLATE_PROMPTS.faction },
  { value: "rule", label: "规则设定", hint: "约束世界运行与选择后果的机制", prompt: BUILTIN_TEMPLATE_PROMPTS.rule },
]

function normalizeObjectTemplateType(value) {
  return TEMPLATE_TYPE_OPTIONS.includes(value) ? value : "custom"
}

const TASK_PRESETS = {
  plot: {
    label: "生成剧情线",
    task: "基于当前设定梳理主线、支线和伏笔推进。",
    scope: "arc",
    reveal_mode: "author_full",
  },
  polish: {
    label: "润色正文",
    task: "保持设定一致，优化语气、节奏和场景细节。",
    scope: "chapter",
    reveal_mode: "author_safe",
  },
  conflict_check: {
    label: "检查冲突",
    task: "检查当前章节是否存在人物、世界对象或剧情设定冲突。",
    scope: "chapter",
    reveal_mode: "author_full",
  },
  custom: {
    label: "自定义任务",
    task: "",
    scope: "arc",
    reveal_mode: "author_safe",
  },
}

const SCOPE_OPTIONS = [
  { value: "project", label: "项目信息" },
  { value: "world", label: "世界对象" },
  { value: "world_character", label: "世界+人物" },
  { value: "arc", label: "篇章" },
  { value: "chapter", label: "章节" },
  { value: "full", label: "全部" },
]

const REVEAL_OPTIONS = [
  { value: "author_safe", label: "作者安全模式（隐藏隐藏真相）" },
  { value: "author_full", label: "作者全知模式（显示所有信息）" },
  { value: "reader", label: "读者模式（仅显示读者已知信息）" },
  { value: "character", label: "角色视角模式（按人物知识边界）" },
]

const POV_CHARACTER_PAGE_SIZE = 50
const AI_MESSAGE_LIMIT = 40
const AI_SELECTED_CHAPTER_LIMIT = 20
const GENERATE_STATE_STORAGE_PREFIX = "generate_chatbox_state_v1_"
const GENERATE_STATE_MAX_PROJECTS = 5
const GENERATE_STATE_MAX_BYTES = 512 * 1024

const generateView = {
  _selectedTemplateId: "builtin:none",
  _templates: [],
  _templatesLoaded: false,
  _activationProfiles: [],
  _activationProfilesLoaded: false,
  _activationProfileId: null,
  _templateLoadError: null,
  _messages: [],
  _selectedChapters: [],
  _povChapters: [],
  _povScenes: [],
  _povCharacters: [],
  _povForm: {
    chapterIndex: null,
    sceneId: "",
    viewpointCharacterId: "",
    instruction: "",
  },
  _lastPovSubmission: null,
  _povLoadWarning: null,
  _qualityMode: "fast",
  _includeWorldSynopsis: true,
  _lastEntity: null,
  _lastContextUsage: null,
  _lastChatContextUsage: null,
  _lastEntityContextUsage: null,
  _busy: false,
  _abortControllers: null,

  _generateSubTab: "chat",
  _taskPreset: "custom",
  _taskForm: {
    task: "",
    scope: "arc",
    reveal_mode: "author_safe",
    budget_tokens: 4000,
    entity_ids: undefined,
    character_ids: undefined,
    viewpoint_character_id: undefined,
    chapter_index: undefined,
    scene_id: undefined,
    include_world_synopsis: true,
  },
  _lastContextBundle: null,
  _lastContextSource: null,
  _lastContextMarkdown: null,
  _lastContextRequestParams: null,
  _activeStorageKey: null,
  _storageDirty: false,
  _storageNotices: new Set(),

  onLeave() {
    this._persistState()
    this._clearTopbarNote()
    this._abortAllRequests()
  },

  async render() {
    this._activateProjectState()

    const query = router.getCurrentQuery ? router.getCurrentQuery() : new URLSearchParams()
    const requestedTab = query.get("tab")
    if (["chat", "task", "preview", "pov_prose"].includes(requestedTab)) {
      this._generateSubTab = requestedTab
    }
    const requestedPreset = query.get("preset")
    if (requestedPreset && TASK_PRESETS[requestedPreset]) {
      this._taskPreset = requestedPreset
      this._applyTaskPresetValues(requestedPreset)
    }
    if (!this._templatesLoaded) {
      await this._loadTemplates()
    }
    if (!this._activationProfilesLoaded) {
      await this._loadActivationProfiles()
    }
    if (this._generateSubTab === "pov_prose") {
      await this._loadPovBaseOptions()
    }
    return `
      ${this._renderHeader()}
      ${this._renderGenerateSubView()}
      ${this._renderStyles()}
    `
  },

  onRendered() {
    this._bindEvents()
    this._mountTopbarNote()
    this._renderMessages()
    this._renderAttachments()
    this._syncTaskFormInputs()
  },

  _renderProjectChip() {
    const title = state.currentProject?.title || state.currentProject?.name
    if (!title) return ""
    return `<span class="view-toolbar__project" title="${esc(title)}">${esc(title)}</span>`
  },

  _renderGenerateSubTabs() {
    return `
      <button class="generate-subtab ${this._generateSubTab === "chat" ? "active" : ""}" data-action="switch-generate-subtab" data-subtab="chat">自由对话</button>
      <button class="generate-subtab ${this._generateSubTab === "pov_prose" ? "active" : ""}" data-action="switch-generate-subtab" data-subtab="pov_prose">角色视角正文</button>
      <button class="generate-subtab ${this._generateSubTab === "task" ? "active" : ""}" data-action="switch-generate-subtab" data-subtab="task">任务</button>
      <button class="generate-subtab ${this._generateSubTab === "preview" ? "active" : ""}" data-action="switch-generate-subtab" data-subtab="preview">上下文预览</button>
    `
  },

  _renderHeaderActions() {
    const projectChip = this._renderProjectChip()
    if (this._generateSubTab === "chat") {
      return `
        ${projectChip}
        <button class="btn btn-sm" data-action="send-chat-message">发送</button>
        <button class="btn btn-sm btn-primary" data-action="generate-object-draft">生成世界对象建议</button>
      `
    }
    if (this._generateSubTab === "pov_prose") {
      return `
        ${projectChip}
        <button class="btn btn-sm btn-primary" data-action="generate-pov-prose">生成角色视角正文</button>
      `
    }
    if (this._generateSubTab === "task") {
      return `
        ${projectChip}
        <button class="btn btn-sm btn-primary" data-action="run-task">编译上下文</button>
        <button class="btn btn-sm" data-action="preview-task-context">预览上下文</button>
        <button class="btn btn-sm" data-action="render-task-md">渲染 Markdown</button>
        <button class="btn btn-sm" data-action="apply-to-chat">应用到聊天</button>
      `
    }
    return projectChip
  },

  _renderHeader() {
    return `
      <div class="view-header view-header--with-tabs generate-toolbar">
        <div class="subnav generate-subtabs" role="tablist" aria-label="生成模式">
          ${this._renderGenerateSubTabs()}
        </div>
        <div class="view-header__actions">
          ${this._renderHeaderActions()}
        </div>
      </div>
    `
  },

  _renderGenerateSubView() {
    if (this._generateSubTab === "pov_prose") return this._renderPovProseTab()
    if (this._generateSubTab === "task") return this._renderTaskTab()
    if (this._generateSubTab === "preview") return this._renderContextPreviewTab()
    return this._renderChatTab()
  },

  _renderChatTab() {
    return `
      <div id="generate-template-row" class="generate-template-row generate-template-row--toolbar">
        ${this._renderTemplateButtons()}
      </div>
      <div class="generate-chatbox">
        <div class="generate-chat-main">
          <div class="card generate-chat-panel">
            <div id="generate-chat-messages" class="generate-chat-messages"></div>
            <div class="generate-composer">
              <textarea
                class="generate-chat-input"
                id="generate-chat-input"
                rows="4"
                placeholder="直接聊，或把其他 Chatbox 的完整讨论粘贴到这里。"
              ></textarea>
            </div>
          </div>
        </div>

        ${renderWorkspaceRail({
          key: workspaceRailKey("generate", state.currentProjectId, "assistant"),
          title: "生成辅助",
          className: "generate-side-rail workspace-rail--right",
          defaultOpen: typeof window === "undefined" || window.innerWidth > 1099,
          content: `<div class="generate-chat-side">
          <div class="card generate-settings-card">
            <div class="generate-card-title-row">
              <div class="card-title">选项</div>
              <button class="btn btn-sm" data-action="edit-object-templates">编辑模板</button>
            </div>
            <div class="generate-side-options">
              <label class="generate-quality-toggle">
                <input id="generate-quality-pro" type="checkbox" ${this._qualityMode === "pro" ? "checked" : ""} />
                <span>高质量</span>
              </label>
              <label class="generate-quality-toggle">
                <input id="generate-include-world-synopsis" type="checkbox" ${this._includeWorldSynopsis ? "checked" : ""} />
                <span>使用世界观简介</span>
              </label>
              <label class="generate-quality-toggle generate-quality-toggle--stacked">
                <span>已发布 AI 参考规则（显式启用）</span>
                <select id="generate-activation-profile" class="form-select">
                  <option value="">不启用</option>
                  ${this._activationProfiles.map((item) => `
                    <option value="${esc(item.id)}" ${this._activationProfileId === item.id ? "selected" : ""}>${esc(item.name)} · v${esc(item.version_number)}</option>
                  `).join("")}
                </select>
              </label>
              <div id="generate-chat-context-usage">
                ${this._renderChatContextUsageAction()}
              </div>
              <button class="btn btn-sm" data-action="select-source-chapters">附带正文</button>
            </div>
            <p class="generate-empty-copy">单次最多附带 20 章；长对话只发送最近 40 条消息。</p>
            <div id="generate-selected-chapters" class="generate-attachment-summary"></div>
          </div>
          <div class="card">
            <div class="card-title">结果</div>
            <div id="generate-result" class="generate-result">
              ${this._lastEntity ? this._renderEntityResult(this._lastEntity) : `
                <p class="generate-empty-copy">聊天不会写入世界设定。点击“生成世界对象建议”后，结果会进入待处理，采用后才成为当前有效设定。</p>
              `}
            </div>
          </div>
        </div>`,
        })}
      </div>
    `
  },

  _renderPovProseTab() {
    const form = this._povForm
    const scene = this._selectedPovScene()
    const role = this._selectedPovCharacter()
    const chapterTitle = this._povChapters.find((item) => Number(item.chapter_index) === Number(form.chapterIndex))?.title || ""
    const scenePovId = scene?.pov_character_id || ""
    const hasManualRole = Boolean(form.viewpointCharacterId && scenePovId && form.viewpointCharacterId !== scenePovId)
    const hasSceneWithoutPov = Boolean(scene && !scenePovId)
    return `
      <div class="generate-pov-workspace">
        <div class="card generate-pov-form">
          ${this._povLoadWarning ? `<div class="generate-template-warning">${esc(this._povLoadWarning)}</div>` : ""}
          <div class="generate-form-grid">
            <label>章节 *
              <select class="form-select" id="generate-pov-chapter">
                <option value="">请选择章节</option>
                ${this._povChapters.map((item) => `
                  <option value="${esc(item.chapter_index)}" ${Number(form.chapterIndex) === Number(item.chapter_index) ? "selected" : ""}>
                    第 ${esc(item.chapter_index)} 章${item.title ? ` · ${esc(item.title)}` : ""}
                  </option>
                `).join("")}
              </select>
            </label>
            <label>Scene *
              <select class="form-select" id="generate-pov-scene" ${form.chapterIndex ? "" : "disabled"}>
                <option value="">请选择 Scene</option>
                ${this._povScenes.map((item) => `
                  <option value="${esc(item.id)}" ${form.sceneId === item.id ? "selected" : ""}>
                    ${esc(item.title || item.name || item.id)}
                  </option>
                `).join("")}
              </select>
            </label>
            <label>视角角色 *
              <select class="form-select" id="generate-pov-character">
                <option value="">请选择角色</option>
                ${this._povCharacters.map((item) => {
                  const id = this._characterId(item)
                  return `
                    <option value="${esc(id)}" ${form.viewpointCharacterId === id ? "selected" : ""}>
                      ${esc(item.name || item.display_name || id)}
                    </option>
                  `
                }).join("")}
              </select>
            </label>
          </div>
          ${hasManualRole ? `<div class="generate-pov-note">本次使用手动选择角色，不修改 Scene POV 设置。</div>` : ""}
          ${hasSceneWithoutPov ? `<div class="generate-pov-note">当前 Scene 未设置 POV 角色，请手动选择本次生成角色。</div>` : ""}
          <div class="generate-pov-note">世界观简介在角色视角模式中强制禁用；本次继续使用逐事实可见性过滤链。</div>
          <label>作者指令
            <textarea class="form-textarea" id="generate-pov-instruction" rows="5" placeholder="作为作者意图输入，不等于角色知识。">${esc(form.instruction || "")}</textarea>
          </label>
          <p class="generate-empty-copy">生成结果先保存为正文建议；采用到工作稿后才能继续编辑和发布。结构化 POV 面板会展示泄漏诊断。</p>
        </div>
        <div class="card">
          <div class="card-title">结果</div>
          <div id="generate-pov-result" class="generate-result">
            ${this._lastPovSubmission ? this._renderPovSubmission(this._lastPovSubmission) : `
              <p class="generate-empty-copy">选择章节、Scene 和视角角色后生成正文建议。</p>
            `}
          </div>
          ${scene || role || form.chapterIndex ? `
            <div class="generate-pov-summary">
              <div>章节：${form.chapterIndex ? `第 ${esc(form.chapterIndex)} 章${chapterTitle ? ` · ${esc(chapterTitle)}` : ""}` : "未选择"}</div>
              <div>Scene：${scene ? esc(scene.title || scene.name || scene.id) : "未选择"}</div>
              <div>角色：${role ? esc(role.name || role.display_name || this._characterId(role)) : "未选择"}</div>
            </div>
          ` : ""}
        </div>
      </div>
    `
  },

  _renderStyles() {
    return `
      <style>
        .topbar-generate-note { margin-left:10px; color:var(--text-secondary); font-size:12px; font-style:italic; white-space:nowrap; }
        .generate-chatbox { display:grid; grid-template-columns:minmax(0,78fr) minmax(180px,22fr); gap:12px; align-items:stretch; height:calc(100vh - 180px); min-height:480px; overflow:hidden; }
        .generate-chatbox:has(.generate-side-rail:not([open])) { grid-template-columns:minmax(0,1fr) var(--workspace-rail-collapsed); }
        .generate-chat-main { min-height:0; overflow:hidden; }
        .generate-chat-panel { display:flex; flex-direction:column; height:100%; min-height:0; overflow:hidden; }
        .generate-chat-side { min-height:0; max-height:100%; overflow:auto; padding-right:2px; }
        .generate-settings-card { margin-bottom:12px; }
        .generate-card-title-row { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:10px; }
        .generate-card-title-row .card-title { margin-bottom:0; }
        .generate-quality-toggle { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-muted); white-space:nowrap; }
        .generate-template-row { display:flex; flex-wrap:wrap; gap:6px; }
        .generate-template-btn { border:1px solid var(--border); background:var(--panel); color:var(--text); border-radius:var(--radius-sm); padding:6px 10px; cursor:pointer; font-size:13px; }
        .generate-template-btn.active { border-color:var(--accent); background:var(--selected); color:var(--accent); }
        .generate-side-options { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:12px; }
        .generate-attachment-summary { color:var(--text-dim); font-size:12px; }
        .generate-chat-messages { flex:1 1 auto; min-height:0; overflow:auto; border:1px solid var(--border); border-radius:var(--radius-md); padding:18px; background:var(--bg); margin-bottom:12px; }
        .generate-chat-message { margin-bottom:10px; max-width:92%; }
        .generate-chat-message.assistant { margin-left:auto; }
        .generate-chat-role { color:var(--text-dim); font-size:11px; margin-bottom:3px; }
        .generate-chat-bubble { white-space:pre-wrap; border:1px solid var(--border); border-radius:var(--radius-md); padding:10px 12px; background:var(--panel); color:var(--text); font-size:13px; line-height:1.55; }
        .generate-chat-message.assistant .generate-chat-bubble { border-color:var(--accent-dim); }
        .generate-chat-message.pending .generate-chat-bubble { color:var(--text-dim); font-style:italic; }
        .generate-chat-message.error .generate-chat-bubble { color:var(--danger); border-color:var(--danger); background:var(--panel); }
        .generate-composer { flex:0 0 auto; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--panel); padding:8px; }
        .generate-chat-input { width:100%; min-height:72px; resize:vertical; border:0; outline:0; background:transparent; color:var(--text); font:inherit; line-height:1.5; }
        .generate-chat-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:8px; flex-wrap:wrap; }
        .generate-template-row--toolbar { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:var(--space-2); }
        .generate-empty-copy { color:var(--text-dim); font-size:13px; line-height:1.6; margin:0; }
        .generate-result-card { border:1px solid var(--accent); border-radius:var(--radius-sm); padding:12px; background:var(--panel); }
        .generate-result-title { font-weight:600; margin-bottom:6px; }
        .generate-result-meta { color:var(--text-dim); font-size:12px; margin-bottom:8px; }
        .generate-result-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
        .generate-chapter-list { display:grid; gap:8px; max-height:460px; overflow:auto; }
        .generate-chapter-card { display:grid; grid-template-columns:auto minmax(0,1fr); gap:8px; border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px; }
        .generate-chapter-title { font-weight:600; font-size:13px; }
        .generate-chapter-excerpt { color:var(--text-dim); font-size:12px; margin-top:4px; line-height:1.45; }
        .generate-template-editor { display:grid; gap:10px; }
        .generate-template-editor label { display:block; color:var(--text-muted); font-size:12px; margin-bottom:4px; }
        .generate-template-editor textarea { min-height:180px; }
        .generate-template-editor-help { color:var(--text-dim); font-size:12px; line-height:1.5; margin:0; }
        .generate-template-history { display:grid; gap:8px; max-height:320px; overflow:auto; }
        .generate-template-revision { display:grid; gap:6px; border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px; }
        .generate-template-revision pre { margin:0; white-space:pre-wrap; max-height:120px; overflow:auto; color:var(--text-muted); font:12px/1.5 var(--font-mono); }
        @media (max-width: 900px) {
          .generate-chatbox, .generate-chatbox:has(.generate-side-rail:not([open])) { grid-template-columns:1fr; height:auto; min-height:0; overflow:visible; }
          .generate-side-rail { grid-column:1 / -1; }
          .topbar-generate-note { display:none; }
          .generate-chat-panel { min-height:auto; }
          .generate-chat-side { max-height:none; overflow:visible; padding-right:0; }
          .generate-chat-messages { min-height:260px; max-height:60vh; }
        }
        .generate-subtab { flex-shrink:0; border:1px solid var(--border); background:var(--panel); color:var(--text); border-radius:var(--radius-sm); padding:5px 12px; cursor:pointer; font-size:13px; }
        .generate-subtab.active { border-color:var(--accent); background:var(--selected); color:var(--accent); }
        .generate-task-workspace { display:grid; grid-template-columns:minmax(190px,22fr) minmax(0,78fr); gap:12px; align-items:start; }
        .generate-task-cards { display:grid; gap:8px; }
        .generate-task-card { border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px 10px; cursor:pointer; text-align:left; background:var(--panel); color:var(--text); }
        .generate-task-card.active { border-color:var(--accent); background:var(--selected); }
        .generate-task-card h4 { margin:0 0 2px; font-size:13px; }
        .generate-task-card p { margin:0; color:var(--text-dim); font-size:12px; line-height:1.45; }
        .generate-task-form .form-group { margin-bottom:10px; }
        .generate-task-form label { display:block; color:var(--text-muted); font-size:12px; margin-bottom:4px; }
        .generate-task-result { margin-top:12px; }
        .generate-context-preview-source { color:var(--text-muted); font-size:12px; margin-bottom:10px; }
        .generate-context-preview-empty { color:var(--text-dim); font-size:13px; line-height:1.6; }
        .generate-pov-workspace { display:grid; grid-template-columns:minmax(0,72fr) minmax(200px,28fr); gap:12px; align-items:start; }
        .generate-pov-form { display:grid; gap:10px; }
        .generate-pov-form label { display:grid; gap:4px; color:var(--text-muted); font-size:12px; }
        .generate-form-grid { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; }
        .generate-template-warning { border:1px solid var(--warning); border-radius:var(--radius-sm); color:var(--warning); padding:7px; font-size:12px; margin-bottom:10px; }
        .generate-pov-note { border:1px solid var(--warning); border-radius:var(--radius-sm); color:var(--warning); padding:8px; font-size:12px; }
        .generate-pov-summary { display:grid; gap:5px; margin-top:12px; color:var(--text-dim); font-size:12px; line-height:1.5; }
        @media (max-width: 900px) {
          .generate-task-workspace, .generate-pov-workspace, .generate-form-grid { grid-template-columns:1fr; }
        }
      </style>
    `
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "select-object-template": (_e, target) => this._selectTemplate(target.getAttribute("data-template")),
      "edit-object-templates": () => this._openTemplateEditor(),
      "send-chat-message": () => this._sendChatMessage(),
      "generate-object-draft": () => this._generateObjectDraft(),
      "generate-pov-prose": () => this._generatePovProse(),
      "select-source-chapters": () => this._openChapterPicker(),
      "open-generated-destination": (_e, target) => {
        const view = target.getAttribute("data-target-view")
        const subview = target.getAttribute("data-target-subview") || null
        const chapterIndex = Number(target.getAttribute("data-chapter-index") || 0)
        if (view === "writing" && chapterIndex) state._currentChapter = chapterIndex
        if (view) router.navigate(view, subview)
      },
      "continue-chat": () => this._focusChatInput(),
      "generate-another": () => this._clearResult(),
      "switch-generate-subtab": (_e, target) => this._switchGenerateSubTab(target.getAttribute("data-subtab")),
      "select-task-preset": (_e, target) => this._selectTaskPreset(target.getAttribute("data-preset")),
      "run-task": () => this._runTask(),
      "preview-task-context": () => this._previewTaskContext(),
      "render-task-md": () => this._renderTaskMarkdown(),
      "copy-task-md": () => this._copyTaskMarkdown(),
      "export-task-md": () => this._exportTaskMarkdown(),
      "apply-to-chat": () => this._applyTaskToChat(),
      "view-generation-context": (_e, target) => this._viewGenerationContext(
        target.getAttribute("data-context-kind"),
      ),
    })
    document.getElementById("generate-quality-pro")?.addEventListener("change", () => {
      this._syncInputs()
      this._persistState()
    })
    document.getElementById("generate-include-world-synopsis")?.addEventListener("change", () => {
      this._syncInputs()
      this._persistState()
    })
    document.getElementById("generate-activation-profile")?.addEventListener("change", (event) => {
      this._activationProfileId = event.target.value || null
      this._persistState()
    })
    document.getElementById("generate-pov-chapter")?.addEventListener("change", (event) => {
      this._changePovChapter(event.target.value)
    })
    document.getElementById("generate-pov-scene")?.addEventListener("change", (event) => {
      this._changePovScene(event.target.value)
    })
    document.getElementById("generate-pov-character")?.addEventListener("change", (event) => {
      this._povForm.viewpointCharacterId = event.target.value || ""
      this._persistState()
      this._refreshView()
    })
    document.getElementById("generate-pov-instruction")?.addEventListener("input", (event) => {
      this._povForm.instruction = event.target.value || ""
      this._persistState()
    })
    document.getElementById("gen-reveal")?.addEventListener("change", (event) => {
      const group = document.getElementById("gen-viewpoint-character-group")
      if (group) {
        group.style.display = event.target.value === "character" ? "" : "none"
      }
      const synopsis = document.getElementById("gen-include-world-synopsis")
      const synopsisHint = document.getElementById("gen-world-synopsis-visibility-hint")
      if (synopsis) {
        synopsis.disabled = ["reader", "character"].includes(event.target.value)
        if (synopsis.disabled) synopsis.checked = false
      }
      if (synopsisHint) {
        synopsisHint.hidden = !["reader", "character"].includes(event.target.value)
      }
    })
  },

  _builtinTemplates() {
    return OBJECT_TEMPLATES.map((item) => ({
      id: `builtin:${item.value}`,
      value: `builtin:${item.value}`,
      label: item.label,
      hint: item.hint,
      prompt: item.prompt,
      object_template: item.value,
      is_builtin: true,
      version_number: 1,
    }))
  },

  _normalizeTemplate(raw) {
    return {
      id: raw.id,
      value: raw.id,
      label: raw.name || raw.label || "未命名模板",
      hint: raw.description || raw.hint || "",
      prompt: raw.prompt_text || raw.prompt || "",
      object_template: normalizeObjectTemplateType(raw.object_template || "custom"),
      is_builtin: Boolean(raw.is_builtin),
      version_number: raw.version_number || 1,
    }
  },

  async _loadTemplates() {
    if (!state.currentProjectId) {
      this._templates = this._builtinTemplates()
      this._templatesLoaded = true
      return
    }
    try {
      const data = await api.generate.listPromptTemplates(state.currentProjectId)
      const items = Array.isArray(data?.items) ? data.items : []
      this._templates = items.length ? items.map((item) => this._normalizeTemplate(item)) : this._builtinTemplates()
      this._templateLoadError = null
      this._templatesLoaded = true
    } catch (err) {
      this._templates = this._builtinTemplates()
      this._templateLoadError = `模板加载失败：${err.message || "未知错误"}`
      this._templatesLoaded = true
      toast(this._templateLoadError, "warning")
    }
    if (!this._findTemplate(this._selectedTemplateId)) {
      this._selectedTemplateId = "builtin:none"
    }
  },

  async _loadActivationProfiles() {
    if (!state.currentProjectId) {
      this._activationProfiles = []
      this._activationProfilesLoaded = true
      return
    }
    try {
      const data = await api.context.listActivationProfiles(state.currentProjectId)
      this._activationProfiles = (data?.items || []).filter((item) => item.status === "published")
      if (this._activationProfileId && !this._activationProfiles.some((item) => item.id === this._activationProfileId)) {
        this._activationProfileId = null
      }
    } catch (err) {
      this._activationProfiles = []
      toast(`AI 参考规则加载失败：${err.message || "未知错误"}`, "warning")
    }
    this._activationProfilesLoaded = true
  },

  _allTemplates() {
    return this._templates.length ? this._templates : this._builtinTemplates()
  },

  _findTemplate(value = this._selectedTemplateId) {
    return this._allTemplates().find((item) => item.value === value)
  },

  _selectedTemplatePayload() {
    const item = this._findTemplate() || this._allTemplates()[0]
    return {
      template_id: item.id,
      template_version: item.version_number,
      template: item.object_template,
      template_name: item.label,
      template_prompt: item.is_builtin ? undefined : item.prompt,
    }
  },

  _renderTemplateButtons() {
    return this._allTemplates().map((item) => `
      <button
        class="generate-template-btn ${item.value === this._selectedTemplateId ? "active" : ""}"
        data-action="select-object-template"
        data-template="${esc(item.value)}"
        title="${esc(item.hint || item.prompt || "")}"
      >${esc(item.label)}</button>
    `).join("")
  },

  _selectTemplate(template) {
    if (!this._findTemplate(template)) return
    this._selectedTemplateId = template
    this._renderTemplateControls()
    this._persistState()
  },

  _renderTemplateControls() {
    const row = document.getElementById("generate-template-row")
    if (row) row.innerHTML = this._renderTemplateButtons()
  },

  _openTemplateEditor() {
    const current = this._findTemplate()
    showModalHtml("编辑模板", this._renderTemplateEditor(current?.value), [
      { text: "保存模板", class: "btn-primary", handler: () => this._saveTemplateFromEditor() },
      { text: "新建模板", class: "btn", handler: () => this._createTemplateFromEditor() },
      { text: "关闭", class: "btn-ghost", handler: closeModal },
    ])
    this._bindTemplateEditor()
  },

  _renderTemplateEditor(selectedValue) {
    const selected = this._findTemplate(selectedValue) || this._allTemplates()[0]
    const isBuiltin = selected?.is_builtin
    return `
      <div class="generate-template-editor">
        <div>
          <label for="generate-template-editor-select">现有模板</label>
          <select class="form-select" id="generate-template-editor-select">
            ${this._allTemplates().map((item) => `
              <option value="${esc(item.value)}" ${item.value === selected.value ? "selected" : ""}>
                ${esc(item.is_builtin ? item.label : `自定义 · ${item.label}`)}
              </option>
            `).join("")}
          </select>
        </div>
        <div>
          <label for="generate-template-editor-name">模板名称</label>
          <input class="form-input" id="generate-template-editor-name" value="${esc(selected.label)}" maxlength="80" />
        </div>
        <div>
          <label for="generate-template-editor-prompt">提示词</label>
          <textarea class="form-textarea" id="generate-template-editor-prompt" maxlength="8000">${esc(selected.prompt || "")}</textarea>
        </div>
        <p class="generate-template-editor-help">
          ${isBuiltin
            ? "内置模板为只读；点击“保存模板”会以原名称创建项目级副本，点击“新建模板”则使用当前输入的名称创建新模板。"
            : "修改自定义模板会更新后端存储的版本，所有设备同步生效。"}
        </p>
        <div class="generate-template-history-actions" ${isBuiltin ? "hidden" : ""}>
          <button class="btn btn-sm" id="generate-template-history-load" type="button">版本历史</button>
        </div>
        <div id="generate-template-history" class="generate-template-history"></div>
      </div>
    `
  },

  _bindTemplateEditor() {
    const select = document.getElementById("generate-template-editor-select")
    select?.addEventListener("change", () => {
      const item = this._findTemplate(select.value)
      const nameEl = document.getElementById("generate-template-editor-name")
      const promptEl = document.getElementById("generate-template-editor-prompt")
      if (!item) return
      if (nameEl) nameEl.value = item.label
      if (promptEl) promptEl.value = item.prompt || ""
      const helpEl = document.querySelector(".generate-template-editor-help")
      if (helpEl) {
        helpEl.textContent = item.is_builtin
          ? "内置模板为只读；点击“保存模板”会以原名称创建项目级副本，点击“新建模板”则使用当前输入的名称创建新模板。"
          : "修改自定义模板会更新后端存储的版本，所有设备同步生效。"
      }
      const historyActions = document.querySelector(".generate-template-history-actions")
      if (historyActions) historyActions.hidden = Boolean(item.is_builtin)
      const history = document.getElementById("generate-template-history")
      if (history) history.innerHTML = ""
    })
    document.getElementById("generate-template-history-load")?.addEventListener("click", () => {
      const item = this._findTemplate(select?.value || this._selectedTemplateId)
      if (item && !item.is_builtin) this._loadTemplateHistory(item.id)
    })
  },

  async _loadTemplateHistory(templateId) {
    const container = document.getElementById("generate-template-history")
    if (!container || !templateId || !state.currentProjectId) return
    container.innerHTML = '<p class="generate-template-editor-help">加载版本历史…</p>'
    try {
      const result = await api.generate.listPromptTemplateRevisions(templateId, state.currentProjectId)
      const revisions = Array.isArray(result) ? result : (result?.items || [])
      if (!revisions.length) {
        container.innerHTML = '<p class="generate-template-editor-help">暂无版本历史。</p>'
        return
      }
      container.innerHTML = revisions.map((revision, index) => `
        <article class="generate-template-revision">
          <div><strong>v${esc(String(revision.version_number || "-"))}</strong> · ${esc(revision.created_at ? new Date(revision.created_at).toLocaleString("zh-CN") : "-")} · ${esc(revision.validation_state || "unknown")}</div>
          <pre>${esc(String(revision.prompt_text || "").slice(0, 800))}</pre>
          <button class="btn btn-sm" type="button" data-template-revision-index="${index}">载入到编辑器</button>
        </article>
      `).join("")
      container.querySelectorAll("[data-template-revision-index]").forEach((button) => {
        button.addEventListener("click", () => {
          const revision = revisions[Number(button.getAttribute("data-template-revision-index"))]
          if (revision) this._loadTemplateRevisionIntoEditor(revision)
        })
      })
    } catch (err) {
      container.innerHTML = `<p class="generate-template-warning">版本历史加载失败：${esc(err.message || "未知错误")}</p>`
    }
  },

  _loadTemplateRevisionIntoEditor(revision) {
    const name = document.getElementById("generate-template-editor-name")
    const prompt = document.getElementById("generate-template-editor-prompt")
    const help = document.querySelector(".generate-template-editor-help")
    if (name && revision.name) name.value = revision.name
    if (prompt) prompt.value = revision.prompt_text || ""
    if (help) help.textContent = `已载入 v${revision.version_number || "-"}；内容尚未保存，点击“保存模板”后才会生成新版本。`
  },

  async _saveTemplateFromEditor() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const selected = document.getElementById("generate-template-editor-select")?.value || this._selectedTemplateId
    const item = this._findTemplate(selected) || this._allTemplates()[0]
    const prompt = document.getElementById("generate-template-editor-prompt")?.value?.trim() || ""
    const name = document.getElementById("generate-template-editor-name")?.value?.trim() || ""
    if (!prompt) {
      toast("请输入模板提示词", "warning")
      return
    }
    try {
      if (item.is_builtin) {
        const copied = await api.generate.copyPromptTemplate(item.id, {
          novel_id: state.currentProjectId,
          name: item.label,
        })
        const updated = await api.generate.updatePromptTemplate(copied.id, state.currentProjectId, {
          prompt_text: prompt,
        })
        this._templates = [...this._templates, this._normalizeTemplate(updated)]
        this._selectedTemplateId = updated.id
      } else {
        if (!name) {
          toast("请输入模板名称", "warning")
          return
        }
        const updated = await api.generate.updatePromptTemplate(item.id, state.currentProjectId, {
          name,
          prompt_text: prompt,
        })
        this._templates = this._templates.map((tpl) => (
          tpl.id === item.id ? this._normalizeTemplate(updated) : tpl
        ))
      }
      this._renderTemplateControls()
      this._persistState()
      toast("模板已保存", "success")
    } catch (err) {
      toast(`保存模板失败：${err.message || "未知错误"}`, "error")
    }
  },

  async _createTemplateFromEditor() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const name = document.getElementById("generate-template-editor-name")?.value?.trim() || ""
    const prompt = document.getElementById("generate-template-editor-prompt")?.value?.trim() || ""
    if (!name) {
      toast("请输入模板名称", "warning")
      return
    }
    if (!prompt) {
      toast("请输入模板提示词", "warning")
      return
    }
    try {
      const created = await api.generate.createPromptTemplate({
        novel_id: state.currentProjectId,
        name,
        object_template: "custom",
        prompt_text: prompt,
      })
      this._templates = [...this._templates, this._normalizeTemplate(created)]
      this._selectedTemplateId = created.id
      this._renderTemplateControls()
      this._persistState()
      toast("新模板已创建", "success")
    } catch (err) {
      toast(`创建模板失败：${err.message || "未知错误"}`, "error")
    }
  },

  async _sendChatMessage() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const input = document.getElementById("generate-chat-input")
    const text = input?.value?.trim() || ""
    if (!text) {
      toast("请输入要聊的内容", "warning")
      return
    }
    this._syncInputs()
    this._messages.push({ role: "user", content: text })
    if (input) input.value = ""
    const payload = this._buildPayload()
    const pendingMessage = { role: "assistant", content: "正在思考...", pending: true }
    this._messages.push(pendingMessage)
    this._renderMessages()
    this._persistState()

    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const response = await api.generate.objectDraftChat(payload, { signal: controller.signal })
      this._lastContextUsage = response?.context_usage || null
      this._lastChatContextUsage = response?.context_usage || null
      this._renderChatContextUsageAction(true)
      if (response?.reply) {
        pendingMessage.content = response.reply
        pendingMessage.pending = false
        this._renderMessages()
        this._persistState()
      }
    } catch (err) {
      pendingMessage.content = `聊天失败：${err.message || "未知错误"}`
      pendingMessage.pending = false
      pendingMessage.error = true
      this._renderMessages()
      this._persistState()
      toast(`聊天失败：${err.message || "未知错误"}`, "error")
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
  },

  async _generateObjectDraft() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    this._captureDraftInputAsMessage()
    this._syncInputs()
    if (!this._messages.length) {
      toast("请先聊天或粘贴已有对话到输入框", "warning")
      return
    }
    this._renderMessages()
    this._persistState()
    const resultEl = document.getElementById("generate-result")
    if (resultEl) resultEl.innerHTML = '<div class="loading">正在生成世界对象建议...</div>'
    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const response = await api.generate.generateObjectDraft(this._buildPayload(), { signal: controller.signal })
      this._lastEntity = response?.suggestion || response?.entity || null
      this._lastContextUsage = response?.context_usage || null
      this._lastEntityContextUsage = response?.context_usage || null
      if (resultEl) {
        resultEl.replaceChildren()
        if (this._lastEntity) {
          resultEl.append(this._renderEntityResultNode(this._lastEntity))
        } else {
          const empty = document.createElement("p")
          empty.className = "generate-empty-copy"
          empty.textContent = "生成完成，但未返回对象。"
          resultEl.append(empty)
        }
      }
      this._persistState()
      toast("世界对象建议已进入待处理", "success")
    } catch (err) {
      if (resultEl) {
        resultEl.replaceChildren(this._renderInlineError(`生成失败：${err.message || "未知错误"}`))
      }
      toast(`生成失败：${err.message || "未知错误"}`, "error")
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
  },

  async _openChapterPicker() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    try {
      const data = await api.writing.listChapters(state.currentProjectId)
      const summaries = Array.isArray(data.chapters) ? data.chapters : []
      if (!summaries.length) {
        toast("当前项目还没有正文，可直接聊天或粘贴外部对话生成建议", "info")
        return
      }
      const previewChapters = await this._runInBatches(
        summaries.slice(0, AI_SELECTED_CHAPTER_LIMIT),
        5,
        async (item) => {
          try {
            const draft = item.id
              ? await api.writing.get(item.id, state.currentProjectId)
              : await api.writing.getDraft(item.chapter_index, state.currentProjectId)
            return {
              chapter_index: item.chapter_index,
              title: draft.title || item.title || `第${item.chapter_index}章`,
              excerpt: this._excerpt(draft.content || ""),
            }
          } catch {
            return {
              chapter_index: item.chapter_index,
              title: item.title || `第${item.chapter_index}章`,
              excerpt: "",
            }
          }
        },
      )
      const previewByIndex = new Map(
        previewChapters.map((item) => [item.chapter_index, item]),
      )
      const chapters = summaries.map((item) => previewByIndex.get(item.chapter_index) || {
        chapter_index: item.chapter_index,
        title: item.title || `第${item.chapter_index}章`,
        excerpt: "",
      })
      showModalHtml("选择附带正文", this._renderChapterPicker(chapters), [
        { text: "取消", class: "btn-ghost", handler: closeModal },
        {
          text: "确认选择",
          class: "btn-primary",
          handler: () => {
            const selectedChapters = chapters.filter((item) => {
              const el = document.getElementById(`generate-chapter-${item.chapter_index}`)
              return Boolean(el?.checked)
            })
            if (selectedChapters.length > AI_SELECTED_CHAPTER_LIMIT) {
              toast(`每次最多附带 ${AI_SELECTED_CHAPTER_LIMIT} 章正文`, "warning")
              return false
            }
            this._selectedChapters = selectedChapters
            this._renderAttachments()
            this._persistState()
            closeModal()
          },
        },
      ])
    } catch (err) {
      toast(`加载章节失败：${err.message || "未知错误"}`, "error")
    }
  },

  _renderChapterPicker(chapters) {
    const selected = new Set(this._selectedChapters.map((item) => item.chapter_index))
    return `
      <div class="generate-chapter-list">
        ${chapters.map((item) => `
          <label class="generate-chapter-card">
            <input id="generate-chapter-${esc(item.chapter_index)}" type="checkbox" ${selected.has(item.chapter_index) ? "checked" : ""} />
            <span>
              <span class="generate-chapter-title">第 ${esc(item.chapter_index)} 章 · ${esc(item.title || "")}</span>
              <span class="generate-chapter-excerpt">${esc(item.excerpt || "暂无正文摘录")}</span>
            </span>
          </label>
        `).join("")}
      </div>
    `
  },

  _renderMessages() {
    const el = document.getElementById("generate-chat-messages")
    if (!el) return
    if (!this._messages.length) {
      el.innerHTML = '<p class="generate-empty-copy">可以直接说“帮我设计一个反派”，也可以先粘贴外部聊完的内容。</p>'
      return
    }
    el.innerHTML = this._messages.map((message) => `
      <div class="generate-chat-message ${esc(message.role)} ${message.pending ? "pending" : ""} ${message.error ? "error" : ""}">
        <div class="generate-chat-role">${message.role === "assistant" ? "AI" : "你"}</div>
        <div class="generate-chat-bubble">${esc(message.content)}</div>
      </div>
    `).join("")
    el.scrollTop = el.scrollHeight
  },

  _renderAttachments() {
    const el = document.getElementById("generate-selected-chapters")
    if (!el) return
    if (!this._selectedChapters.length) {
      el.textContent = "未附带正文"
      return
    }
    el.textContent = `已附带 ${this._selectedChapters.length} 章：${
      this._selectedChapters.map((item) => `第${item.chapter_index}章`).join("、")
    }`
  },

  _renderChatContextUsageAction(updateDom = false) {
    const html = this._lastChatContextUsage
      ? `<button class="btn btn-sm" data-action="view-generation-context" data-context-kind="chat">查看最近聊天上下文</button>`
      : ""
    if (updateDom) {
      const container = document.getElementById("generate-chat-context-usage")
      if (container) container.innerHTML = html
    }
    return html
  },

  _renderEntityResult(entity) {
    const content = entity.payload_json || entity.entity || entity
    const display = worldAssetDisplay({ ...content, status: entity.status || content.status || "candidate" })
    return `
      <div class="generate-result-card">
        <div class="generate-result-title">${esc(content.name || content.title || "未命名对象")}</div>
        <div class="generate-result-meta">${esc(content.entity_type || entity.target_type || "-")} · ${esc(display.label)}</div>
        <p class="generate-result-summary">${esc(content.summary || content.public_info || "世界对象建议已进入待处理。")}</p>
        <div class="generate-result-actions">
          <button class="btn btn-sm btn-primary" data-action="open-generated-destination" data-target-view="world" data-target-subview="review-objects">前往待处理</button>
          <button class="btn btn-sm" data-action="continue-chat">继续聊</button>
          <button class="btn btn-sm" data-action="generate-another">再生成一个</button>
          ${this._lastEntityContextUsage
            ? `<button class="btn btn-sm" data-action="view-generation-context" data-context-kind="entity">查看本次上下文</button>`
            : ""}
        </div>
      </div>
    `
  },

  _renderEntityResultNode(entity) {
    const content = entity.payload_json || entity.entity || entity
    const display = worldAssetDisplay({ ...content, status: entity.status || content.status || "candidate" })
    const card = document.createElement("div")
    card.className = "generate-result-card"

    const title = document.createElement("div")
    title.className = "generate-result-title"
    title.textContent = content.name || content.title || "未命名对象"

    const meta = document.createElement("div")
    meta.className = "generate-result-meta"
    meta.textContent = `${content.entity_type || entity.target_type || "-"} · ${display.label}`

    const summary = document.createElement("p")
    summary.style.cssText = "font-size:13px;line-height:1.6;margin:0;"
    summary.textContent = content.summary || content.public_info || "世界对象建议已进入待处理。"

    const actions = document.createElement("div")
    actions.className = "generate-result-actions"
    const buttons = [
      ["open-generated-destination", "前往待处理", "btn btn-sm btn-primary"],
      ["continue-chat", "继续聊", "btn btn-sm"],
      ["generate-another", "再生成一个", "btn btn-sm"],
    ]
    if (this._lastEntityContextUsage) {
      buttons.push(["view-generation-context", "查看本次上下文", "btn btn-sm"])
    }
    for (const [action, label, className] of buttons) {
      const button = document.createElement("button")
      button.type = "button"
      button.className = className
      button.dataset.action = action
      if (action === "view-generation-context") button.dataset.contextKind = "entity"
      if (action === "open-generated-destination") {
        button.dataset.targetView = "world"
        button.dataset.targetSubview = "review-objects"
      }
      button.textContent = label
      actions.append(button)
    }

    card.append(title, meta, summary, actions)
    return card
  },

  _renderInlineError(message) {
    const p = document.createElement("p")
    p.className = "generate-error-text"
    p.textContent = message
    return p
  },

  _buildPayload() {
    const templatePayload = this._selectedTemplatePayload()
    const messages = this._messages
      .filter((item) => !item.pending && !item.error && (item.role === "user" || item.role === "assistant"))
      .map((item) => ({
        role: item.role,
        content: item.content,
      }))
    return {
      novel_id: state.currentProjectId,
      template_id: templatePayload.template_id,
      template_version: templatePayload.template_version,
      template: templatePayload.template,
      template_name: templatePayload.template_name,
      template_prompt: templatePayload.template_prompt,
      messages: messages.slice(-AI_MESSAGE_LIMIT),
      selected_chapter_indices: this._selectedChapters
        .slice(0, AI_SELECTED_CHAPTER_LIMIT)
        .map((item) => item.chapter_index),
      quality_mode: this._qualityMode,
      include_world_synopsis: this._includeWorldSynopsis,
      selected_world_bible_draft_ids: [],
      activation_profile_id: this._activationProfileId,
    }
  },

  _syncInputs() {
    this._qualityMode = document.getElementById("generate-quality-pro")?.checked ? "pro" : "fast"
    const synopsis = document.getElementById("generate-include-world-synopsis")
    if (synopsis) this._includeWorldSynopsis = Boolean(synopsis.checked)
  },

  _captureDraftInputAsMessage() {
    const input = document.getElementById("generate-chat-input")
    const text = input?.value?.trim() || ""
    if (!text) return false
    this._messages.push({ role: "user", content: text })
    if (input) input.value = ""
    return true
  },

  _setBusy(busy) {
    this._busy = busy
    document.querySelectorAll(
      '[data-action="send-chat-message"], [data-action="generate-object-draft"], [data-action="generate-pov-prose"], [data-action="run-task"], [data-action="preview-task-context"], [data-action="render-task-md"]'
    ).forEach((btn) => {
      btn.disabled = busy
    })
  },

  _trackRequestController() {
    if (!this._abortControllers) this._abortControllers = new Set()
    const controller = new AbortController()
    this._abortControllers.add(controller)
    return controller
  },

  _releaseRequestController(controller) {
    if (!controller) return
    this._abortControllers?.delete(controller)
  },

  _abortAllRequests() {
    if (!this._abortControllers) return
    for (const controller of this._abortControllers) {
      try {
        controller.abort()
      } catch {}
    }
    this._abortControllers.clear()
  },

  async _runInBatches(items, batchSize, fn) {
    const results = []
    for (let i = 0; i < items.length; i += batchSize) {
      const batch = items.slice(i, i + batchSize)
      const batchResults = await Promise.all(batch.map((item) => fn(item)))
      results.push(...batchResults)
    }
    return results
  },

  _focusChatInput() {
    document.getElementById("generate-chat-input")?.focus()
  },

  _clearResult() {
    this._lastEntity = null
    this._lastEntityContextUsage = null
    const resultEl = document.getElementById("generate-result")
    if (resultEl) {
      resultEl.innerHTML = '<p class="generate-empty-copy">可以继续基于当前聊天生成新的世界对象建议。</p>'
    }
    this._persistState()
  },

  _excerpt(content, limit = 120) {
    const text = String(content || "").replace(/\s+/g, " ").trim()
    return text.length > limit ? `${text.slice(0, limit)}...` : text
  },

  _storageKey() {
    return `${GENERATE_STATE_STORAGE_PREFIX}${state.currentProjectId || "none"}`
  },

  _mountTopbarNote() {
    this._clearTopbarNote()
    const moduleEl = document.getElementById("topbar-module")
    if (!moduleEl) return
    const note = document.createElement("span")
    note.id = "topbar-generate-note"
    note.className = "topbar-generate-note"
    note.textContent = "先自由聊，确定后再生成待处理建议。"
    moduleEl.insertAdjacentElement("afterend", note)
  },

  _clearTopbarNote() {
    document.getElementById("topbar-generate-note")?.remove()
  },

  _activateProjectState() {
    const storageKey = this._storageKey()
    if (this._activeStorageKey === storageKey) return
    // The router updates the global project before rendering the next view and
    // does not call onLeave when generate -> generate only changes project.
    // Persist through the previous active key before resetting project state.
    if (this._activeStorageKey) this._persistState()
    this._activeStorageKey = storageKey
    this._resetProjectState()
    this._restoreState(storageKey)
  },

  _resetProjectState() {
    this._selectedTemplateId = "builtin:none"
    this._templates = []
    this._templatesLoaded = false
    this._templateLoadError = null
    this._activationProfiles = []
    this._activationProfilesLoaded = false
    this._activationProfileId = null
    this._messages = []
    this._selectedChapters = []
    this._povChapters = []
    this._povScenes = []
    this._povCharacters = []
    this._povForm = {
      chapterIndex: null,
      sceneId: "",
      viewpointCharacterId: "",
      instruction: "",
    }
    this._lastPovSubmission = null
    this._povLoadWarning = null
    this._qualityMode = "fast"
    this._includeWorldSynopsis = true
    this._lastEntity = null
    this._lastContextUsage = null
    this._lastChatContextUsage = null
    this._lastEntityContextUsage = null
    this._generateSubTab = "chat"
    this._taskPreset = "custom"
    this._taskForm = {
      task: "",
      scope: "arc",
      reveal_mode: "author_safe",
      budget_tokens: 4000,
      entity_ids: undefined,
      character_ids: undefined,
      viewpoint_character_id: undefined,
      chapter_index: undefined,
      scene_id: undefined,
      include_world_synopsis: true,
    }
    this._lastContextBundle = null
    this._lastContextSource = null
    this._lastContextMarkdown = null
    this._lastContextRequestParams = null
    this._storageDirty = false
  },

  _persistedState() {
    return {
      savedAt: Date.now(),
      selectedTemplateId: this._selectedTemplateId,
      messages: this._messages.filter((item) => !item.pending),
      selectedChapters: this._selectedChapters.slice(0, AI_SELECTED_CHAPTER_LIMIT),
      povForm: this._povForm,
      lastPovSubmission: this._lastPovSubmission,
      qualityMode: this._qualityMode,
      includeWorldSynopsis: this._includeWorldSynopsis,
      activationProfileId: this._activationProfileId,
      lastEntity: this._lastEntity,
      lastContextUsage: this._lastContextUsage,
      lastChatContextUsage: this._lastChatContextUsage,
      lastEntityContextUsage: this._lastEntityContextUsage,
      generateSubTab: this._generateSubTab,
      taskPreset: this._taskPreset,
      taskForm: this._taskForm,
      lastContextBundle: this._lastContextBundle,
      lastContextSource: this._lastContextSource,
    }
  },

  _serializedStateWithinLimit() {
    const payload = this._persistedState()
    let serialized = JSON.stringify(payload)
    let droppedDerived = false
    let droppedMessages = 0

    if (new TextEncoder().encode(serialized).byteLength > GENERATE_STATE_MAX_BYTES) {
      droppedDerived = Boolean(
        payload.lastPovSubmission
        || payload.lastEntity
        || payload.lastContextUsage
        || payload.lastChatContextUsage
        || payload.lastEntityContextUsage
        || payload.lastContextBundle
        || payload.lastContextSource,
      )
      payload.lastPovSubmission = null
      payload.lastEntity = null
      payload.lastContextUsage = null
      payload.lastChatContextUsage = null
      payload.lastEntityContextUsage = null
      payload.lastContextBundle = null
      payload.lastContextSource = null
      serialized = JSON.stringify(payload)
    }

    if (
      new TextEncoder().encode(serialized).byteLength > GENERATE_STATE_MAX_BYTES
      && payload.messages.length > AI_MESSAGE_LIMIT
    ) {
      droppedMessages = payload.messages.length - AI_MESSAGE_LIMIT
      payload.messages = payload.messages.slice(-AI_MESSAGE_LIMIT)
      serialized = JSON.stringify(payload)
    }

    if (new TextEncoder().encode(serialized).byteLength > GENERATE_STATE_MAX_BYTES) {
      return { serialized: null, droppedDerived, droppedMessages }
    }
    return { serialized, droppedDerived, droppedMessages }
  },

  _generateStorageEntries(excludeKey = null) {
    const entries = []
    try {
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index)
        if (!key?.startsWith(GENERATE_STATE_STORAGE_PREFIX) || key === excludeKey) continue
        let savedAt = 0
        try {
          savedAt = Number(JSON.parse(localStorage.getItem(key))?.savedAt) || 0
        } catch {}
        entries.push({ key, savedAt })
      }
    } catch {}
    return entries.sort((left, right) => (
      left.savedAt - right.savedAt || left.key.localeCompare(right.key)
    ))
  },

  _evictOldestGenerateState(currentKey) {
    const oldest = this._generateStorageEntries(currentKey)[0]
    if (!oldest) return false
    try {
      localStorage.removeItem(oldest.key)
      return localStorage.getItem(oldest.key) === null
    } catch {
      return false
    }
  },

  _pruneGenerateStates(currentKey) {
    const entries = this._generateStorageEntries(currentKey)
    let removed = 0
    while (entries.length + 1 > GENERATE_STATE_MAX_PROJECTS) {
      const oldest = entries.shift()
      try {
        localStorage.removeItem(oldest.key)
        removed += 1
      } catch {
        break
      }
    }
    return removed
  },

  _isStorageQuotaError(err) {
    return err?.name === "QuotaExceededError"
      || err?.name === "NS_ERROR_DOM_QUOTA_REACHED"
      || err?.code === 22
      || err?.code === 1014
  },

  _notifyStorageNotice(code, message) {
    const noticeKey = `${this._activeStorageKey || this._storageKey()}:${code}`
    if (this._storageNotices.has(noticeKey)) return
    this._storageNotices.add(noticeKey)
    toast(message, "warning")
  },

  _persistState() {
    const currentKey = this._activeStorageKey || this._storageKey()
    const bounded = this._serializedStateWithinLimit()
    if (!bounded.serialized) {
      this._storageDirty = true
      this._notifyStorageNotice(
        "too-large",
        "生成中心本地会话超过 512 KiB 保存上限；当前页面内容仍在，请精简或复制重要内容。",
      )
      return false
    }

    let quotaEvictions = 0
    while (true) {
      try {
        localStorage.setItem(currentKey, bounded.serialized)
        break
      } catch (err) {
        if (this._isStorageQuotaError(err) && this._evictOldestGenerateState(currentKey)) {
          quotaEvictions += 1
          continue
        }
        this._storageDirty = true
        this._notifyStorageNotice(
          "save-failed",
          "生成中心本地会话保存失败；当前页面内容仍在，请复制重要内容后重试。",
        )
        return false
      }
    }

    const lruEvictions = this._pruneGenerateStates(currentKey)
    this._storageDirty = false
    if (bounded.droppedDerived || bounded.droppedMessages) {
      const detail = bounded.droppedMessages && bounded.droppedDerived
        ? "已省略可重新生成的预览，并仅保留最近 40 条对话。"
        : bounded.droppedMessages
          ? "已仅保留最近 40 条对话。"
          : "已省略可重新生成的预览数据。"
      this._notifyStorageNotice("compacted", `生成中心本地会话较大，${detail}`)
    }
    if (quotaEvictions + lruEvictions > 0) {
      this._notifyStorageNotice(
        "evicted",
        "本地生成会话已达到容量边界，已清理最久未使用的项目缓存。",
      )
    }
    return true
  },

  _restoreState(storageKey = this._storageKey()) {
    let raw
    try {
      raw = localStorage.getItem(storageKey)
    } catch {
      this._notifyStorageNotice(
        "read-failed",
        "无法读取生成中心本地会话；当前数据库内容不受影响。",
      )
      return
    }
    if (!raw) return

    try {
      const parsed = JSON.parse(raw)
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("invalid local state")
      }
      if (
        ("messages" in parsed && !Array.isArray(parsed.messages))
        || ("selectedChapters" in parsed && !Array.isArray(parsed.selectedChapters))
        || (
          "povForm" in parsed
          && (!parsed.povForm || typeof parsed.povForm !== "object" || Array.isArray(parsed.povForm))
        )
        || (
          "taskForm" in parsed
          && (!parsed.taskForm || typeof parsed.taskForm !== "object" || Array.isArray(parsed.taskForm))
        )
      ) {
        throw new Error("invalid local state shape")
      }
      this._selectedTemplateId = parsed.selectedTemplateId || this._selectedTemplateId
      this._messages = Array.isArray(parsed.messages) ? parsed.messages : []
      this._selectedChapters = Array.isArray(parsed.selectedChapters)
        ? parsed.selectedChapters.slice(0, AI_SELECTED_CHAPTER_LIMIT)
        : []
      this._povForm = parsed.povForm && typeof parsed.povForm === "object"
        ? { ...this._povForm, ...parsed.povForm }
        : this._povForm
      this._lastPovSubmission = parsed.lastPovSubmission || null
      this._qualityMode = parsed.qualityMode || "fast"
      this._includeWorldSynopsis = parsed.includeWorldSynopsis !== false
      this._activationProfileId = parsed.activationProfileId || null
      this._lastEntity = parsed.lastEntity || null
      this._lastContextUsage = parsed.lastContextUsage || null
      this._lastChatContextUsage = parsed.lastChatContextUsage || null
      this._lastEntityContextUsage = parsed.lastEntityContextUsage
        || (this._lastEntity ? parsed.lastContextUsage : null)
      this._generateSubTab = ["chat", "task", "preview", "pov_prose"].includes(parsed.generateSubTab)
        ? parsed.generateSubTab
        : this._generateSubTab
      this._taskPreset = parsed.taskPreset || this._taskPreset
      this._taskForm = parsed.taskForm && typeof parsed.taskForm === "object"
        ? { ...this._taskForm, ...parsed.taskForm }
        : this._taskForm
      this._lastContextBundle = parsed.lastContextBundle || null
      this._lastContextSource = parsed.lastContextSource || null
    } catch {
      try {
        localStorage.removeItem(storageKey)
      } catch {}
      this._notifyStorageNotice(
        "invalid-state",
        "生成中心本地会话已损坏，已忽略该缓存；当前数据库内容不受影响。",
      )
    }
  },

  _applyTaskPresetValues(presetKey) {
    const preset = TASK_PRESETS[presetKey]
    if (!preset) return
    this._taskForm = {
      ...this._taskForm,
      task: preset.task,
      scope: preset.scope,
      reveal_mode: preset.reveal_mode,
      viewpoint_character_id: preset.reveal_mode === "character" ? this._taskForm.viewpoint_character_id : undefined,
    }
  },

  async _loadPovBaseOptions() {
    if (!state.currentProjectId) {
      this._povChapters = []
      this._povScenes = []
      this._povCharacters = []
      return
    }
    try {
      const [chapterData, characterData] = await Promise.all([
        api.writing.listChapters(state.currentProjectId),
        this._loadAllPovCharacters(state.currentProjectId),
      ])
      this._povChapters = Array.isArray(chapterData?.chapters) ? chapterData.chapters : []
      this._povCharacters = characterData
      this._povLoadWarning = null
      if (this._povForm.chapterIndex) {
        await this._loadPovScenesForChapter(this._povForm.chapterIndex)
      }
    } catch (err) {
      this._povLoadWarning = `加载章节或角色失败：${err.message || "未知错误"}`
      this._povChapters = []
      this._povScenes = []
      this._povCharacters = []
    }
  },

  async _loadAllPovCharacters(novelId) {
    const characters = []
    let skip = 0

    while (true) {
      const data = await api.world.listCharacters({
        novel_id: novelId,
        skip,
        limit: POV_CHARACTER_PAGE_SIZE,
      })
      const page = Array.isArray(data?.items) ? data.items : []
      characters.push(...page)

      const total = Number(data?.total)
      if (page.length < POV_CHARACTER_PAGE_SIZE || (Number.isFinite(total) && characters.length >= total)) {
        return characters
      }
      skip += page.length
    }
  },

  async _loadPovScenesForChapter(chapterIndex) {
    if (!state.currentProjectId || !chapterIndex) {
      this._povScenes = []
      return
    }
    try {
      const data = await api.outline.listScenesByChapter(state.currentProjectId, Number(chapterIndex))
      this._povScenes = Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : [])
      this._povLoadWarning = null
    } catch (err) {
      this._povScenes = []
      this._povLoadWarning = `加载 Scene 失败：${err.message || "未知错误"}`
    }
  },

  async _changePovChapter(value) {
    const chapterIndex = value ? Number(value) : null
    this._povForm = {
      ...this._povForm,
      chapterIndex,
      sceneId: "",
      viewpointCharacterId: "",
    }
    this._lastPovSubmission = null
    if (chapterIndex) {
      await this._loadPovScenesForChapter(chapterIndex)
    } else {
      this._povScenes = []
    }
    this._persistState()
    await this._refreshView()
  },

  async _changePovScene(sceneId) {
    const scene = this._povScenes.find((item) => item.id === sceneId)
    this._povForm = {
      ...this._povForm,
      sceneId: sceneId || "",
      viewpointCharacterId: scene?.pov_character_id || "",
    }
    this._lastPovSubmission = null
    this._persistState()
    await this._refreshView()
  },

  _selectedPovScene() {
    return this._povScenes.find((item) => item.id === this._povForm.sceneId) || null
  },

  _selectedPovCharacter() {
    return this._povCharacters.find((item) => this._characterId(item) === this._povForm.viewpointCharacterId) || null
  },

  _characterId(character) {
    return String(character?.entity_id || character?.id || "")
  },

  async _generatePovProse() {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    this._povForm.instruction = document.getElementById("generate-pov-instruction")?.value || this._povForm.instruction || ""
    const { chapterIndex, sceneId, viewpointCharacterId, instruction } = this._povForm
    if (!chapterIndex) {
      toast("请先选择章节", "warning")
      return
    }
    if (!sceneId) {
      toast("请先选择 Scene", "warning")
      return
    }
    if (!viewpointCharacterId) {
      toast("请先选择视角角色", "warning")
      return
    }

    const resultEl = document.getElementById("generate-pov-result")
    if (resultEl) resultEl.innerHTML = '<div class="loading">正在确认参考资料...</div>'
    const povInstruction = [
      instruction?.trim() || "",
      "请从所选 Scene 的 POV 角色有限认知出发生成正文建议。",
      "用户指令是作者意图，不等于角色知识。",
      "角色判断、台词、内心只能使用确认上下文中该角色可见的信息。",
    ].filter(Boolean).join("\n")

    try {
      this._setBusy(true)
      const confirmation = await confirmAiReference({
        novel_id: state.currentProjectId,
        action: "writing.generate",
        task: "基于所选 Scene 和 POV 角色有限认知，生成正文建议预览",
        scope: "chapter",
        chapter_index: chapterIndex,
        scene_id: sceneId,
        reveal_mode: "character",
        viewpoint_character_id: viewpointCharacterId,
        character_ids: [viewpointCharacterId],
        include_pending_objects: false,
      })
      const userNote = confirmation.user_note ? `${confirmation.user_note}\n\n` : ""
      if (resultEl) resultEl.innerHTML = '<div class="loading">正在生成正文建议...</div>'
      const result = await api.writing.generate({
        novel_id: state.currentProjectId,
        chapter_index: chapterIndex,
        title: this._povChapters.find((item) => Number(item.chapter_index) === Number(chapterIndex))?.title || `第 ${chapterIndex} 章`,
        instruction: `${userNote}${povInstruction}`,
        context_confirmation_id: confirmation.id,
      })
      this._lastPovSubmission = {
        result,
        chapterIndex,
        sceneId,
        viewpointCharacterId,
      }
      if (resultEl) resultEl.innerHTML = this._renderPovSubmission(this._lastPovSubmission)
      this._persistState()
      toast(`角色视角正文建议已提交：${result.task_id || result.id || result.draft_id || ""}`, "success")
    } catch (err) {
      if (err?.message?.includes("取消")) {
        if (resultEl) resultEl.innerHTML = this._lastPovSubmission
          ? this._renderPovSubmission(this._lastPovSubmission)
          : '<p class="generate-empty-copy">已取消 AI 参考资料确认。</p>'
        return
      }
      if (resultEl) {
        resultEl.innerHTML = `<p class="generate-error-text">生成失败：${esc(err.message || "未知错误")}</p>`
      }
      toast(`角色视角正文生成失败：${err.message || "未知错误"}`, "error")
    } finally {
      this._setBusy(false)
    }
  },

  _renderPovSubmission(submission) {
    const result = submission?.result || {}
    const scene = this._povScenes.find((item) => item.id === submission.sceneId)
    const role = this._povCharacters.find((item) => this._characterId(item) === submission.viewpointCharacterId)
    const id = result.task_id || result.draft_id || result.id || result.draft?.id || ""
    return `
      <div class="generate-result-card">
        <div class="generate-result-title">角色视角正文建议已提交</div>
        <div class="generate-result-meta">
          第 ${esc(submission.chapterIndex)} 章 · ${esc(scene?.title || scene?.name || submission.sceneId)} · ${esc(role?.name || role?.display_name || submission.viewpointCharacterId)}
        </div>
        <p class="generate-result-summary">${id ? `任务 / 建议：${esc(id)}` : "正文建议已生成，可到写作页采用到工作稿。"}</p>
        <div class="generate-result-actions">
          <button class="btn btn-sm btn-primary" data-action="open-generated-destination" data-target-view="writing" data-chapter-index="${esc(submission.chapterIndex)}">打开写作页</button>
        </div>
      </div>
    `
  },

  async _selectTaskPreset(presetKey) {
    if (!TASK_PRESETS[presetKey]) return
    this._taskPreset = presetKey
    this._applyTaskPresetValues(presetKey)
    this._persistState()
    await this._refreshView()
  },

  async _switchGenerateSubTab(subtab) {
    if (!["chat", "task", "preview", "pov_prose"].includes(subtab)) return
    this._generateSubTab = subtab
    if (subtab === "pov_prose") {
      await this._loadPovBaseOptions()
    }
    this._persistState()
    await this._refreshView()
  },

  _syncTaskFormInputs() {
    if (this._generateSubTab !== "task") return
    const task = document.getElementById("gen-task")
    if (task) task.value = this._taskForm.task || ""
    const scope = document.getElementById("gen-scope")
    if (scope) scope.value = this._taskForm.scope || "arc"
    const entities = document.getElementById("gen-entities")
    if (entities) entities.value = (this._taskForm.entity_ids || []).join(", ")
    const characters = document.getElementById("gen-characters")
    if (characters) characters.value = (this._taskForm.character_ids || []).join(", ")
    const chapter = document.getElementById("gen-chapter")
    if (chapter) chapter.value = this._taskForm.chapter_index || ""
    const scene = document.getElementById("gen-scene")
    if (scene) scene.value = this._taskForm.scene_id || ""
    const budget = document.getElementById("gen-budget")
    if (budget) budget.value = this._taskForm.budget_tokens || 4000
    const reveal = document.getElementById("gen-reveal")
    if (reveal) reveal.value = this._taskForm.reveal_mode || "author_safe"
    const viewpointGroup = document.getElementById("gen-viewpoint-character-group")
    if (viewpointGroup) {
      viewpointGroup.style.display = (this._taskForm.reveal_mode === "character") ? "" : "none"
    }
    const viewpointCharacter = document.getElementById("gen-viewpoint-character")
    if (viewpointCharacter) viewpointCharacter.value = this._taskForm.viewpoint_character_id || ""
    const synopsis = document.getElementById("gen-include-world-synopsis")
    if (synopsis) {
      synopsis.disabled = ["reader", "character"].includes(this._taskForm.reveal_mode)
      synopsis.checked = !synopsis.disabled && Boolean(this._taskForm.include_world_synopsis)
    }
  },

  _readTaskForm() {
    const task = document.getElementById("gen-task")?.value?.trim() || ""
    const scope = document.getElementById("gen-scope")?.value || "arc"
    const reveal = document.getElementById("gen-reveal")?.value || "author_safe"
    const entitiesInput = document.getElementById("gen-entities")?.value || ""
    const charactersInput = document.getElementById("gen-characters")?.value || ""
    const chapterInput = document.getElementById("gen-chapter")?.value || ""
    const sceneInput = document.getElementById("gen-scene")?.value || ""
    const budgetInput = document.getElementById("gen-budget")?.value || ""
    const viewpointCharacterInput = document.getElementById("gen-viewpoint-character")?.value || ""
    const includeWorldSynopsis = Boolean(document.getElementById("gen-include-world-synopsis")?.checked)
    const entityIds = entitiesInput ? entitiesInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const characterIds = charactersInput ? charactersInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const chapterIndex = chapterInput ? parseInt(chapterInput, 10) : undefined
    const sceneId = sceneInput ? sceneInput.trim() : undefined
    const budgetTokens = budgetInput ? parseInt(budgetInput, 10) : 4000
    const viewpointCharacterId = reveal === "character" ? (viewpointCharacterInput.trim() || undefined) : undefined
    const finalCharacterIds = reveal === "character" && viewpointCharacterId
      ? [...new Set([...(characterIds || []), viewpointCharacterId])]
      : characterIds
    return {
      novel_id: state.currentProjectId,
      task,
      scope,
      chapter_index: chapterIndex,
      scene_id: sceneId,
      budget_tokens: budgetTokens,
      entity_ids: entityIds,
      character_ids: finalCharacterIds,
      reveal_mode: reveal,
      viewpoint_character_id: viewpointCharacterId,
      include_world_synopsis: !["reader", "character"].includes(reveal) && includeWorldSynopsis,
    }
  },

  _validateTaskForm(params) {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return false
    }
    if (!params.task) {
      toast("请输入任务描述", "warning")
      return false
    }
    if (params.reveal_mode === "character" && !params.viewpoint_character_id) {
      toast("角色视角模式必须选择或输入视角人物 ID", "warning")
      return false
    }
    return true
  },

  async _compileTaskContext({ silent = false } = {}) {
    const params = this._readTaskForm()
    if (!this._validateTaskForm(params)) return
    this._taskForm = {
      task: params.task,
      scope: params.scope,
      reveal_mode: params.reveal_mode,
      budget_tokens: params.budget_tokens,
      entity_ids: params.entity_ids,
      character_ids: params.character_ids,
      viewpoint_character_id: params.viewpoint_character_id,
      chapter_index: params.chapter_index,
      scene_id: params.scene_id,
      include_world_synopsis: params.include_world_synopsis,
    }
    this._lastContextSource = "task"
    this._lastContextRequestParams = params
    const output = document.getElementById("gen-task-output")
    if (output) output.innerHTML = '<div class="loading">编译中...</div>'
    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const data = await api.context.compile(params, { signal: controller.signal })
      this._lastContextBundle = data
      this._generateSubTab = "preview"
      this._persistState()
      await this._refreshView()
    } catch (err) {
      const message = `编译失败：${err.message || "未知错误"}`
      if (output) {
        output.replaceChildren(this._renderInlineError(message))
      }
      if (!silent) {
        toast(message, "error")
      }
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
  },

  async _runTask() {
    await this._compileTaskContext({ silent: false })
  },

  async _previewTaskContext() {
    await this._compileTaskContext({ silent: true })
  },

  async _renderTaskMarkdown() {
    const params = this._lastContextRequestParams || this._readTaskForm()
    if (!this._validateTaskForm(params)) return
    const output = document.getElementById("gen-task-output")
    if (!output) return
    let controller = null
    try {
      this._setBusy(true)
      controller = this._trackRequestController()
      const data = await api.context.render(params, { signal: controller.signal })
      if (data?.markdown) {
        this._lastContextMarkdown = data.markdown
        output.innerHTML = `<pre class="generate-markdown-pre">${esc(data.markdown)}</pre>`
      }
    } catch (err) {
      output.innerHTML = `<p class="generate-error-text">渲染失败：${esc(err.message || "未知错误")}</p>`
    } finally {
      this._releaseRequestController(controller)
      this._setBusy(false)
    }
  },

  _copyTaskMarkdown() {
    if (this._lastContextMarkdown) {
      navigator.clipboard.writeText(this._lastContextMarkdown)
        .then(() => toast("上下文 Markdown 已复制到剪贴板", "success"))
        .catch(() => toast("复制失败，请手动选择复制", "warning"))
    }
  },

  _exportTaskMarkdown() {
    if (this._lastContextMarkdown) {
      const blob = new Blob([this._lastContextMarkdown], { type: "text/markdown;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `context-${state.currentProject?.title || "project"}-${Date.now()}.md`
      a.click()
      URL.revokeObjectURL(url)
      toast("上下文已导出为 Markdown 文件", "success")
    }
  },

  _applyTaskToChat() {
    const task = this._taskForm.task
    if (!task) {
      toast("当前没有任务内容", "warning")
      return
    }
    this._messages.push({ role: "user", content: task })
    if (this._lastContextBundle?.sections?.length) {
      const summary = `已加载 ${this._lastContextBundle.sections.length} 段上下文，共 ${this._lastContextBundle.total_tokens || 0} tokens。`
      this._messages.push({ role: "assistant", content: summary })
    }
    this._generateSubTab = "chat"
    this._persistState()
    this._refreshView()
  },

  async _viewGenerationContext(kind = null) {
    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }
    const usage = kind === "chat"
      ? this._lastChatContextUsage
      : kind === "entity"
        ? this._lastEntityContextUsage
        : this._lastContextUsage
    if (!usage) {
      toast("本次生成没有返回可审计的上下文记录", "warning")
      return
    }
    const body = `
      <div class="generate-context-header">
        <span class="generate-context-stat">${esc(usage.section_key || "world_bible_synopsis")}</span>
        <span class="generate-context-meta">状态：${esc(usage.status || "unknown")}</span>
        <span class="generate-context-meta">Tokens：${esc(usage.token_count || 0)}</span>
      </div>
      <table class="data-table"><tbody>
        <tr><th>Revision</th><td>${esc(usage.revision_id || "确定性降级/未包含")}</td></tr>
        <tr><th>Source hash</th><td>${esc(usage.source_hash || "-")}</td></tr>
        <tr><th>Block hash</th><td>${esc(usage.block_hash || "-")}</td></tr>
        <tr><th>Context snapshot</th><td>${esc(usage.context_snapshot_id || "-")}</td></tr>
        <tr><th>Stale</th><td>${usage.stale ? "是" : "否"}</td></tr>
        <tr><th>Fallback</th><td>${usage.fallback ? "是" : "否"}</td></tr>
      </tbody></table>
      ${(usage.warnings || []).map((item) => `<p class="generate-context-warning-text">${esc(item)}</p>`).join("")}
    `
    showModalHtml("本次实际使用的上下文", body, [], { size: "large" })
  },

  _renderTaskTab() {
    const preset = TASK_PRESETS[this._taskPreset] || TASK_PRESETS.custom
    const form = this._taskForm
    return `
      <div class="generate-task-workspace">
        <div class="generate-task-cards">
          ${Object.entries(TASK_PRESETS).map(([key, p]) => `
            <button
              class="generate-task-card ${this._taskPreset === key ? "active" : ""}"
              data-action="select-task-preset"
              data-preset="${esc(key)}"
            >
              <h4>${esc(p.label)}</h4>
              <p>${esc(p.task || "填写自定义任务描述")}</p>
            </button>
          `).join("")}
        </div>
        <div class="generate-task-form">
          <div class="card">
            <div class="card-title">任务参数</div>
            <div class="form-group">
              <label>任务描述 *</label>
              <textarea class="form-textarea" id="gen-task" rows="2" placeholder="如：为旧档案缺页篇生成 10 章章节卡">${esc(form.task || "")}</textarea>
            </div>
            <details class="gen-form-section generate-task-section">
              <summary>高级设置</summary>
              <div class="form-group">
                <label>范围</label>
                <select class="form-select" id="gen-scope">
                  ${SCOPE_OPTIONS.map((opt) => `
                    <option value="${esc(opt.value)}" ${form.scope === opt.value ? "selected" : ""}>${esc(opt.label)}</option>
                  `).join("")}
                </select>
              </div>
              <div class="form-group">
                <label>相关对象</label>
                <input class="form-input" id="gen-entities" value="${esc((form.entity_ids || []).join(", "))}" placeholder="可选 world_entity ID，逗号分隔" />
              </div>
              <div class="form-group">
                <label>相关人物</label>
                <input class="form-input" id="gen-characters" value="${esc((form.character_ids || []).join(", "))}" placeholder="可选 character ID，逗号分隔" />
              </div>
              <div class="form-group">
                <label>章节索引</label>
                <input class="form-input" id="gen-chapter" type="number" min="1" value="${esc(form.chapter_index || "")}" placeholder="当前章节（可选）" />
              </div>
              <div class="form-group">
                <label>Scene ID</label>
                <input class="form-input" id="gen-scene" value="${esc(form.scene_id || "")}" placeholder="当前 Scene ID（可选，优先于章节）" />
              </div>
              <div class="form-group">
                <label>预算 (tokens)</label>
                <input class="form-input" id="gen-budget" type="number" min="500" max="32000" value="${esc(form.budget_tokens || 4000)}" />
              </div>
              <div class="form-group">
                <label>揭示模式</label>
                <select class="form-select" id="gen-reveal">
                  ${REVEAL_OPTIONS.map((opt) => `
                    <option value="${esc(opt.value)}" ${form.reveal_mode === opt.value ? "selected" : ""}>${esc(opt.label)}</option>
                  `).join("")}
                </select>
              </div>
              <label class="generate-quality-toggle">
                <input id="gen-include-world-synopsis" type="checkbox"
                  ${form.include_world_synopsis ? "checked" : ""}
                  ${["reader", "character"].includes(form.reveal_mode) ? "disabled" : ""} />
                <span>在作者模式中加入世界观简介</span>
              </label>
              <p id="gen-world-synopsis-visibility-hint" class="generate-form-hint"
                ${["reader", "character"].includes(form.reveal_mode) ? "" : "hidden"}>
                读者/角色模式强制排除作者全知简介。
              </p>
              <div class="form-group" id="gen-viewpoint-character-group" style="${form.reveal_mode === "character" ? "" : "display:none;"}">
                <label>视角人物 *</label>
                <input class="form-input" id="gen-viewpoint-character" value="${esc(form.viewpoint_character_id || "")}" placeholder="角色视角模式必须填写一个 character ID" />
                <p class="generate-form-hint">角色视角模式仅使用此 ID 作为视角人物，与“相关人物”相互独立。</p>
              </div>
            </details>
          </div>
          <div class="card generate-task-result">
            <div class="card-title generate-task-output-header">
              <span>输出</span>
              <span>
                <button class="btn btn-sm" data-action="copy-task-md" disabled title="渲染 Markdown 后可复制">复制</button>
                <button class="btn btn-sm" data-action="export-task-md" disabled title="渲染 Markdown 后可导出">导出</button>
              </span>
            </div>
            <div id="gen-task-output">
              ${this._lastContextBundle && this._lastContextSource === "task" ? this._renderCompileResult(this._lastContextBundle) : '<p class="generate-empty-copy">选择任务或填写描述后编译、预览上下文；此页签不会启动不存在的业务执行链路。</p>'}
            </div>
          </div>
        </div>
      </div>
    `
  },

  _renderContextPreviewTab() {
    const sourceText = this._lastContextSource === "chat" ? "自由对话" : this._lastContextSource === "task" ? `任务：${TASK_PRESETS[this._taskPreset]?.label || "自定义任务"}` : ""
    return `
      <div class="card">
        <div class="card-title">上下文预览</div>
        ${sourceText ? `<div class="generate-context-preview-source">来自：${esc(sourceText)}</div>` : ""}
        ${this._lastContextBundle ? `
          <div class="generate-result-actions generate-preview-actions">
            <button class="btn btn-sm" data-action="render-task-md">渲染 Markdown</button>
            <button class="btn btn-sm" data-action="copy-task-md" ${this._lastContextMarkdown ? "" : "disabled"}>复制</button>
            <button class="btn btn-sm" data-action="export-task-md" ${this._lastContextMarkdown ? "" : "disabled"}>导出</button>
            <button class="btn btn-sm" data-action="switch-generate-subtab" data-subtab="${esc(this._lastContextSource || "chat")}">返回</button>
          </div>
          <div id="gen-task-output">
            ${this._renderCompileResult(this._lastContextBundle)}
          </div>
        ` : `
          <p class="generate-context-preview-empty">还未执行任何 AI 生成或上下文编译。去「自由对话」聊天，或在「任务」里执行一个任务。</p>
        `}
      </div>
    `
  },

  _renderCompileResult(data) {
    let html = ''
    html += '<div class="generate-context-header">'
    html += `<span class="generate-context-stat">已加载 ${data.sections?.length || 0} 段上下文</span>`
    html += `<span class="generate-context-meta">范围：${esc(data.scope)}</span>`
    html += `<span class="generate-context-meta">揭示模式：${esc(data.reveal_mode)}</span>`
    html += `<span class="generate-context-meta">Tokens：${data.total_tokens || 0} / ${data.budget_tokens || 0}</span>`
    html += '</div>'

    if (data.sections && data.sections.length > 0) {
      html += '<table class="data-table generate-context-table"><thead><tr><th>Tier</th><th>Section</th><th>Tokens</th><th>Truncated</th></tr></thead><tbody>'
      for (const section of data.sections) {
        const truncatedText = section.truncated ? "是" : "否"
        html += `<tr><td class="generate-context-meta">${esc(this._tierName(section.tier))}</td><td>${esc(section.key)}</td><td>${section.token_count || 0}</td><td>${truncatedText}</td></tr>`
      }
      html += '</tbody></table>'
    }

    if (data.evicted && data.evicted.length > 0) {
      html += '<div class="generate-context-tag-list">'
      html += '<strong class="generate-context-meta">已驱逐段落：</strong>'
      html += '<div class="generate-context-tags">'
      for (const key of data.evicted) {
        html += `<span class="generate-context-tag">${esc(key)}</span>`
      }
      html += '</div></div>'
    }

    if (data.truncated && data.truncated.length > 0) {
      html += '<div class="generate-context-tag-list">'
      html += '<strong class="generate-context-meta">已截断段落：</strong>'
      html += '<div class="generate-context-tags">'
      for (const key of data.truncated) {
        html += `<span class="generate-context-tag generate-context-tag--truncated">${esc(key)}</span>`
      }
      html += '</div></div>'
    }

    if (data.warnings && data.warnings.length > 0) {
      html += '<div class="generate-context-warning">'
      html += '<strong class="generate-context-warning-title">⚠ 警告</strong>'
      for (const w of data.warnings) {
        html += `<p class="generate-context-warning-text">${esc(w)}</p>`
      }
      html += '</div>'
    }
    html += '<p class="generate-context-hint">点击"渲染 Markdown"查看完整上下文内容。</p>'
    return html
  },

  _tierName(key) {
    const names = { core: "核心", standard: "标准", memory: "记忆", rag: "RAG", optional: "可选" }
    return names[key] || key
  },

  async _refreshView() {
    this._persistState()
    const el = document.getElementById("workspace-content")
    if (el) el.innerHTML = await this.render()
    else if (router.refresh) router.refresh()
  },

}

router.registerView("generate", generateView)
window.generateView = generateView
export default generateView
