/**
 * 生成中心视图 — 自由共创 Chatbox + 数据库草稿生成
 */

import { bindWorkspaceClick } from "../shared/viewHelper.js"

const BUILTIN_TEMPLATE_PROMPTS = {
  none: "不预设对象类型，按用户聊天内容自由收束为一个有用的世界对象草稿。",
  character: "聚焦人物卡：动机、欲望、恐惧、秘密、能力边界、外貌、性格、关系钩子、声音风格和剧情用途。",
  event: "聚焦事件卡：起因、参与方、过程、结果、隐性真相、影响范围、后续钩子和可揭示层级。",
  item: "聚焦物品卡：外观、来源、能力或用途、限制代价、归属关系、秘密、失控风险和剧情钩子。",
  location: "聚焦地点卡：地貌/空间、历史、势力归属、资源、危险、秘密区域、进入条件和剧情用途。",
  faction: "聚焦组织卡：宗旨、结构、资源、关键成员、公开形象、隐藏目标、敌友关系和行动方式。",
  rule: "聚焦规则设定：适用范围、运作机制、限制代价、例外、冲突点、已知误解和剧情可用性。",
}

const OBJECT_TEMPLATES = [
  { value: "none", label: "不带模板", hint: "不预设对象类型，按聊天内容自由收束", prompt: BUILTIN_TEMPLATE_PROMPTS.none },
  { value: "character", label: "人物", hint: "反派、主角、配角、导师", prompt: BUILTIN_TEMPLATE_PROMPTS.character },
  { value: "event", label: "事件", hint: "转折、事故、阴谋、仪式", prompt: BUILTIN_TEMPLATE_PROMPTS.event },
  { value: "item", label: "物品", hint: "法器、信物、线索、资源", prompt: BUILTIN_TEMPLATE_PROMPTS.item },
  { value: "location", label: "地点", hint: "城市、秘境、据点、禁区", prompt: BUILTIN_TEMPLATE_PROMPTS.location },
  { value: "faction", label: "组织", hint: "宗门、公司、帮派、王朝", prompt: BUILTIN_TEMPLATE_PROMPTS.faction },
  { value: "rule", label: "规则设定", hint: "能力体系、禁忌、代价", prompt: BUILTIN_TEMPLATE_PROMPTS.rule },
]

const TEMPLATE_PROMPT_STORAGE_KEY = "generate_object_template_prompts_v1"
const CUSTOM_TEMPLATE_STORAGE_KEY = "generate_object_custom_templates_v1"

const generateView = {
  _template: "none",
  _messages: [],
  _pastedContext: "",
  _selectedChapters: [],
  _qualityMode: "fast",
  _lastEntity: null,
  _busy: false,
  _templatePromptOverrides: {},
  _customTemplates: [],

  onLeave() {
    this._persistState()
    this._clearTopbarNote()
  },

  async render() {
    this._restoreState()
    setTimeout(() => {
      this._bindEvents()
      this._mountTopbarNote()
      this._renderMessages()
      this._renderAttachments()
    }, 0)
    return `
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
              <div class="generate-chat-actions">
                <button class="btn" data-action="send-chat-message">发送</button>
                <button class="btn btn-primary" data-action="generate-object-draft">生成对象（数据库草稿）</button>
              </div>
            </div>
          </div>
        </div>

        <div class="generate-chat-side">
          <div class="card generate-settings-card">
            <div class="generate-card-title-row">
              <div class="card-title">模板</div>
              <button class="btn btn-sm" data-action="edit-object-templates">编辑模板</button>
            </div>
            <div id="generate-template-row" class="generate-template-row">
              ${this._renderTemplateButtons()}
            </div>
            <div class="generate-side-options">
              <label class="generate-quality-toggle">
                <input id="generate-quality-pro" type="checkbox" ${this._qualityMode === "pro" ? "checked" : ""} />
                <span>高质量</span>
              </label>
              <button class="btn btn-sm" data-action="select-source-chapters">附带正文</button>
            </div>
            <div id="generate-selected-chapters" class="generate-attachment-summary"></div>
          </div>
          <div class="card">
            <div class="card-title">结果</div>
            <div id="generate-result" class="generate-result">
              ${this._lastEntity ? this._renderEntityResult(this._lastEntity) : `
                <p class="generate-empty-copy">聊天不会写入数据库。点击“生成对象（数据库草稿）”后，结果会作为世界对象草稿保存。</p>
              `}
            </div>
          </div>
        </div>
      </div>

      <style>
        .topbar-generate-note { margin-left:10px; color:var(--text-secondary); font-size:12px; font-style:italic; white-space:nowrap; }
        .generate-chatbox { display:grid; grid-template-columns:minmax(0,1fr) 280px; gap:12px; align-items:stretch; height:calc(100vh - 180px); min-height:480px; overflow:hidden; }
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
        .generate-composer { flex:0 0 auto; border:1px solid var(--border); border-radius:var(--radius-md); background:var(--panel); padding:10px; }
        .generate-chat-input { width:100%; min-height:92px; resize:vertical; border:0; outline:0; background:transparent; color:var(--text); font:inherit; line-height:1.5; }
        .generate-chat-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:8px; flex-wrap:wrap; }
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
        @media (max-width: 900px) {
          .generate-chatbox { grid-template-columns:1fr; height:auto; min-height:0; overflow:visible; }
          .topbar-generate-note { display:none; }
          .generate-chat-panel { min-height:auto; }
          .generate-chat-side { max-height:none; overflow:visible; padding-right:0; }
          .generate-chat-messages { min-height:260px; max-height:60vh; }
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
      "select-source-chapters": () => this._openChapterPicker(),
      "open-generated-destination": (_e, target) => {
        const view = target.getAttribute("data-target-view")
        const subview = target.getAttribute("data-target-subview") || null
        if (view) router.navigate(view, subview)
      },
      "continue-chat": () => this._focusChatInput(),
      "generate-another": () => this._clearResult(),
    })
    document.getElementById("generate-quality-pro")?.addEventListener("change", () => {
      this._syncInputs()
      this._persistState()
    })
  },

  _renderTemplateButtons() {
    return this._allTemplates().map((item) => `
      <button
        class="generate-template-btn ${item.value === this._template ? "active" : ""}"
        data-action="select-object-template"
        data-template="${esc(item.value)}"
        title="${esc(item.hint || item.prompt || "")}"
      >${esc(item.label)}</button>
    `).join("")
  },

  _selectTemplate(template) {
    if (!this._findTemplate(template)) return
    this._template = template
    this._renderTemplateControls()
    this._persistState()
  },

  _renderTemplateControls() {
    const row = document.getElementById("generate-template-row")
    if (row) row.innerHTML = this._renderTemplateButtons()
  },

  _allTemplates() {
    const builtins = OBJECT_TEMPLATES.map((item) => ({
      ...item,
      prompt: this._templatePromptOverrides[item.value] || item.prompt,
      template: item.value,
      custom: false,
    }))
    const custom = this._customTemplates.map((item) => ({
      value: `custom:${item.id}`,
      label: item.name,
      hint: item.prompt,
      prompt: item.prompt,
      template: "custom",
      custom: true,
    }))
    return [...builtins, ...custom]
  },

  _findTemplate(value = this._template) {
    return this._allTemplates().find((item) => item.value === value)
  },

  _selectedTemplatePayload() {
    const item = this._findTemplate() || this._allTemplates()[0]
    const hasOverride = item.custom || Boolean(this._templatePromptOverrides[item.value])
    return {
      template: item.template,
      template_name: item.label,
      template_prompt: hasOverride ? item.prompt : undefined,
    }
  },

  _openTemplateEditor() {
    const current = this._findTemplate()
    showModal("编辑模板", this._renderTemplateEditor(current.value), [
      { text: "保存模板", class: "btn-primary", handler: () => this._saveTemplateFromEditor() },
      { text: "新建模板", class: "btn", handler: () => this._createTemplateFromEditor() },
      { text: "关闭", class: "btn-ghost", handler: closeModal },
    ])
    setTimeout(() => this._bindTemplateEditor(), 0)
  },

  _renderTemplateEditor(selectedValue) {
    const selected = this._findTemplate(selectedValue) || this._allTemplates()[0]
    return `
      <div class="generate-template-editor">
        <div>
          <label for="generate-template-editor-select">现有模板</label>
          <select class="form-select" id="generate-template-editor-select">
            ${this._allTemplates().map((item) => `
              <option value="${esc(item.value)}" ${item.value === selected.value ? "selected" : ""}>
                ${esc(item.custom ? `自定义 · ${item.label}` : item.label)}
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
          保存内置模板时只覆盖提示词，不改名称。点击“新建模板”会使用当前名称和提示词创建一个新的自定义模板。
        </p>
      </div>
    `
  },

  _bindTemplateEditor() {
    const select = document.getElementById("generate-template-editor-select")
    select?.addEventListener("change", () => {
      const item = this._findTemplate(select.value)
      const nameEl = document.getElementById("generate-template-editor-name")
      const promptEl = document.getElementById("generate-template-editor-prompt")
      if (nameEl) nameEl.value = item.label
      if (promptEl) promptEl.value = item.prompt || ""
    })
  },

  _saveTemplateFromEditor() {
    const selected = document.getElementById("generate-template-editor-select")?.value || this._template
    const item = this._findTemplate(selected) || this._allTemplates()[0]
    const prompt = document.getElementById("generate-template-editor-prompt")?.value?.trim() || ""
    const name = document.getElementById("generate-template-editor-name")?.value?.trim() || ""
    if (!prompt) {
      toast("请输入模板提示词", "warning")
      return
    }
    if (item.custom) {
      if (!name) {
        toast("请输入模板名称", "warning")
        return
      }
      this._customTemplates = this._customTemplates.map((tpl) => (
        `custom:${tpl.id}` === selected ? { ...tpl, name, prompt } : tpl
      ))
    } else {
      this._templatePromptOverrides[item.value] = prompt
    }
    this._template = selected
    this._persistTemplateLibrary()
    this._renderTemplateControls()
    this._persistState()
    toast("模板已保存", "success")
  },

  _createTemplateFromEditor() {
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
    const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
    this._customTemplates.push({ id, name, prompt })
    this._template = `custom:${id}`
    this._persistTemplateLibrary()
    this._renderTemplateControls()
    this._persistState()
    toast("新模板已创建", "success")
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

    try {
      this._setBusy(true)
      const response = await api.generate.objectDraftChat(payload)
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
    if (resultEl) resultEl.innerHTML = '<div class="loading">正在生成数据库草稿...</div>'
    try {
      this._setBusy(true)
      const response = await api.generate.generateObjectDraft(this._buildPayload())
      this._lastEntity = response?.entity || null
      if (resultEl) resultEl.innerHTML = this._lastEntity
        ? this._renderEntityResult(this._lastEntity)
        : '<p class="generate-empty-copy">生成完成，但未返回对象。</p>'
      this._persistState()
      toast("对象草稿已生成", "success")
    } catch (err) {
      if (resultEl) {
        resultEl.innerHTML = `<p style="color:var(--danger);font-size:13px;">生成失败：${esc(err.message || "未知错误")}</p>`
      }
      toast(`生成失败：${err.message || "未知错误"}`, "error")
    } finally {
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
        toast("当前项目还没有正文，可直接聊天或粘贴外部对话生成草稿", "info")
        return
      }
      const chapters = await Promise.all(summaries.slice(0, 60).map(async (item) => {
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
      }))
      showModal("选择附带正文", this._renderChapterPicker(chapters), [
        { text: "取消", class: "btn-ghost", handler: closeModal },
        {
          text: "确认选择",
          class: "btn-primary",
          handler: () => {
            this._selectedChapters = chapters.filter((item) => {
              const el = document.getElementById(`generate-chapter-${item.chapter_index}`)
              return Boolean(el?.checked)
            })
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

  _renderEntityResult(entity) {
    return `
      <div class="generate-result-card">
        <div class="generate-result-title">${esc(entity.name || "未命名对象")}</div>
        <div class="generate-result-meta">${esc(entity.entity_type || "-")} · ${esc(entity.status || "draft")}</div>
        <p style="font-size:13px;line-height:1.6;margin:0;">${esc(entity.summary || "已生成数据库草稿。")}</p>
        <div class="generate-result-actions">
          <button class="btn btn-sm btn-primary" data-action="open-generated-destination" data-target-view="world" data-target-subview="objects">打开世界对象</button>
          <button class="btn btn-sm" data-action="continue-chat">继续聊</button>
          <button class="btn btn-sm" data-action="generate-another">再生成一个</button>
        </div>
      </div>
    `
  },

  _buildPayload() {
    const templatePayload = this._selectedTemplatePayload()
    return {
      novel_id: state.currentProjectId,
      template: templatePayload.template,
      template_name: templatePayload.template_name,
      template_prompt: templatePayload.template_prompt,
      messages: this._messages
        .filter((item) => !item.pending && !item.error && (item.role === "user" || item.role === "assistant"))
        .map((item) => ({
          role: item.role,
          content: item.content,
        })),
      pasted_context: undefined,
      selected_chapter_indices: this._selectedChapters.map((item) => item.chapter_index),
      quality_mode: this._qualityMode,
    }
  },

  _syncInputs() {
    this._qualityMode = document.getElementById("generate-quality-pro")?.checked ? "pro" : "fast"
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
    document.querySelectorAll('[data-action="send-chat-message"], [data-action="generate-object-draft"]').forEach((btn) => {
      btn.disabled = busy
    })
  },

  _focusChatInput() {
    document.getElementById("generate-chat-input")?.focus()
  },

  _clearResult() {
    this._lastEntity = null
    const resultEl = document.getElementById("generate-result")
    if (resultEl) {
      resultEl.innerHTML = '<p class="generate-empty-copy">可以继续基于当前聊天生成新的对象草稿。</p>'
    }
    this._persistState()
  },

  _excerpt(content, limit = 120) {
    const text = String(content || "").replace(/\s+/g, " ").trim()
    return text.length > limit ? `${text.slice(0, limit)}...` : text
  },

  _storageKey() {
    return `generate_chatbox_state_v1_${state.currentProjectId || "none"}`
  },

  _persistTemplateLibrary() {
    try {
      localStorage.setItem(TEMPLATE_PROMPT_STORAGE_KEY, JSON.stringify(this._templatePromptOverrides))
      localStorage.setItem(CUSTOM_TEMPLATE_STORAGE_KEY, JSON.stringify(this._customTemplates))
    } catch {}
  },

  _loadTemplateLibrary() {
    try {
      const prompts = JSON.parse(localStorage.getItem(TEMPLATE_PROMPT_STORAGE_KEY) || "{}")
      this._templatePromptOverrides = prompts && typeof prompts === "object" && !Array.isArray(prompts) ? prompts : {}
    } catch {
      this._templatePromptOverrides = {}
    }
    try {
      const custom = JSON.parse(localStorage.getItem(CUSTOM_TEMPLATE_STORAGE_KEY) || "[]")
      this._customTemplates = Array.isArray(custom)
        ? custom.filter((item) => item?.id && item?.name && item?.prompt).map((item) => ({
          id: String(item.id),
          name: String(item.name).slice(0, 80),
          prompt: String(item.prompt).slice(0, 8000),
        }))
        : []
    } catch {
      this._customTemplates = []
    }
  },

  _mountTopbarNote() {
    this._clearTopbarNote()
    const moduleEl = document.getElementById("topbar-module")
    if (!moduleEl) return
    const note = document.createElement("span")
    note.id = "topbar-generate-note"
    note.className = "topbar-generate-note"
    note.textContent = "先自由聊，确定后再生成数据库草稿。"
    moduleEl.insertAdjacentElement("afterend", note)
  },

  _clearTopbarNote() {
    document.getElementById("topbar-generate-note")?.remove()
  },

  _persistState() {
    try {
      localStorage.setItem(this._storageKey(), JSON.stringify({
        template: this._template,
        messages: this._messages.filter((item) => !item.pending),
        selectedChapters: this._selectedChapters,
        qualityMode: this._qualityMode,
        lastEntity: this._lastEntity,
      }))
    } catch {}
  },

  _restoreState() {
    this._loadTemplateLibrary()
    try {
      const raw = localStorage.getItem(this._storageKey())
      if (!raw) return
      const parsed = JSON.parse(raw)
      this._template = parsed.template || this._template
      if (!this._findTemplate(this._template)) this._template = "none"
      this._messages = Array.isArray(parsed.messages) ? parsed.messages : []
      this._pastedContext = ""
      this._selectedChapters = Array.isArray(parsed.selectedChapters) ? parsed.selectedChapters : []
      this._qualityMode = parsed.qualityMode || "fast"
      this._lastEntity = parsed.lastEntity || null
    } catch {}
  },
}

router.registerView("generate", generateView)
window.generateView = generateView
export default generateView
