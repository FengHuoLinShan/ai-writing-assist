/**
 * 生成中心视图
 */

const generateView = {
  onLeave() { this._currentType = null },
  _currentType: null,

  async render() {
    setTimeout(() => this._bindEvents(), 0)
    return `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:16px;">
        从左侧菜单中选择模块，或使用下方的生成中心统一入口。
      </p>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <div>
          <div class="card" style="margin-bottom:12px;">
            <div class="card-title">生成类型</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;">
              <div class="clickable generate-card ${this._currentType === "world_character" ? "active" : ""}" data-action="select-type" data-type="world_character">
                <strong>1. 世界与人物结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">世界对象、人物、关系等</p>
              </div>
              <div class="clickable generate-card ${this._currentType === "plot" ? "active" : ""}" data-action="select-type" data-type="plot">
                <strong>2. 剧情结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">剧情线、篇章纲、伏笔计划</p>
              </div>
              <div class="clickable generate-card ${this._currentType === "chapter" ? "active" : ""}" data-action="select-type" data-type="chapter">
                <strong>3. 章节与场景结构</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">章节卡和场景卡</p>
              </div>
              <div class="clickable generate-card ${this._currentType === "review" ? "active" : ""}" data-action="select-type" data-type="review">
                <strong>4. 结构复查与状态抽取</strong>
                <p style="color:var(--text-dim);font-size:11px;margin:4px 0 0 0;">检查冲突，抽取状态变化</p>
              </div>
            </div>
          </div>

          <div class="card" id="generate-input-area" style="${this._currentType ? "" : "display:none;"}">
            <div class="card-title">输入意图</div>
            <div class="form-group">
              <label>创作意图/描述 *</label>
              <textarea class="form-textarea" id="generate-intent" rows="3"
                placeholder="描述你想要生成的内容..."></textarea>
            </div>
            <div class="form-group">
              <label>范围</label>
              <select class="form-select" id="generate-scope">
                <option value="arc">当前篇章</option>
                <option value="chapter">当前章节</option>
                <option value="full">全部</option>
              </select>
            </div>
            <div id="generate-extra-fields">
              <div class="form-group">
                <label>相关对象/人物 ID（可选）</label>
                <input class="form-input" id="generate-related" placeholder="逗号分隔" />
              </div>
            </div>
            <button class="btn btn-primary" data-action="start-generate">开始生成</button>
          </div>
        </div>

        <div>
          <div class="card" style="margin-bottom:12px;">
            <div class="card-title">生成流程</div>
            <div id="generate-steps" style="margin-top:8px;">
              <div class="step-item" data-step="1"><span class="step-indicator">1</span> 输入意图</div>
              <div class="step-item" data-step="2"><span class="step-indicator">2</span> 编译上下文</div>
              <div class="step-item" data-step="3"><span class="step-indicator">3</span> 生成候选</div>
              <div class="step-item" data-step="4"><span class="step-indicator">4</span> 预览结果</div>
              <div class="step-item" data-step="5"><span class="step-indicator">5</span> 结构复查</div>
              <div class="step-item" data-step="6"><span class="step-indicator">6</span> 确认写入正史</div>
            </div>
          </div>

          <div class="card" style="min-height:200px;">
            <div class="card-title">结果</div>
            <div id="generate-result">
              <p style="color:var(--text-dim);font-size:13px;">选择左侧生成类型并填写意图后，点击"开始生成"。</p>
            </div>
          </div>
        </div>
      </div>

      <style>
        .generate-card { padding:12px; border:1px solid var(--border); border-radius:4px; background:var(--panel); transition:border-color 0.2s; }
        .generate-card:hover { border-color:var(--accent); }
        .generate-card.active { border-color:var(--accent); background:var(--selected); }
        .step-item { display:flex; align-items:center; gap:8px; padding:6px 0; color:var(--text-dim); font-size:13px; }
        .step-item.active { color:var(--accent); }
        .step-item.done { color:var(--accent-dim); }
        .step-indicator { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px; border-radius:50%; background:var(--border); color:var(--text-dim); font-size:12px; font-weight:bold; }
        .step-item.active .step-indicator { background:var(--accent); color:var(--bg); }
        .step-item.done .step-indicator { background:var(--accent-dim); color:var(--bg); }
      </style>
    `
  },

  _bindEvents() {
    const content = document.getElementById("workspace-content")
    if (!content) return
    content.removeEventListener("click", this._clickHandler)
    this._clickHandler = (e) => {
      const target = e.target.closest("[data-action]")
      if (!target) return
      const action = target.getAttribute("data-action")
      if (action === "select-type") {
        this._selectType(target.getAttribute("data-type"))
      } else if (action === "start-generate") {
        this._startGenerate()
      }
    }
    content.addEventListener("click", this._clickHandler)
  },

  _selectType(type) {
    this._currentType = type
    const inputArea = document.getElementById("generate-input-area")
    if (inputArea) inputArea.style.display = ""

    const intentEl = document.getElementById("generate-intent")
    const typeNames = {
      world_character: "如：为旧档案缺页篇生成世界对象和人物候选",
      plot: "如：为旧档案缺页篇生成 10 章剧情结构和伏笔计划",
      chapter: "如：为旧档案缺页篇生成章节卡",
      review: "如：复查旧档案缺页篇的章节卡结构",
    }
    if (intentEl) intentEl.placeholder = typeNames[type] || "描述你想要生成的内容..."
    document.querySelectorAll(".generate-card").forEach((el) => {
      el.classList.toggle("active", el.getAttribute("data-type") === type)
    })
  },

  _updateStep(step, status) {
    document.querySelectorAll(".step-item").forEach((el) => {
      const s = parseInt(el.dataset.step, 10)
      el.classList.remove("active", "done")
      if (s === step) {
        if (status === "active") el.classList.add("active")
        if (status === "done") el.classList.add("done")
      } else if (s < step) {
        el.classList.add("done")
      }
    })
  },

  async _startGenerate() {
    const intent = document.getElementById("generate-intent")?.value
    if (!intent || !intent.trim()) { toast("请输入创作意图描述", "warning"); return }
    if (!this._currentType) { toast("请先选择生成类型", "warning"); return }

    const resultEl = document.getElementById("generate-result")
    if (!resultEl) return

    const typeNames = { world_character: "世界与人物结构", plot: "剧情结构", chapter: "章节与场景结构", review: "结构复查与状态抽取" }

    this._updateStep(1, "done")
    this._updateStep(2, "active")
    resultEl.innerHTML = '<div class="loading">步骤 2/6：正在编译上下文...</div>'

    try {
      const scope = document.getElementById("generate-scope")?.value || "arc"
      const related = document.getElementById("generate-related")?.value || ""
      const relatedIds = related ? related.split(",").map((s) => s.trim()).filter((s) => s) : undefined

      await api.context.compile({
        novel_id: _state.currentProjectId, task: intent, scope,
        reveal_mode: "author_safe", entity_ids: relatedIds, character_ids: relatedIds,
      })

      this._updateStep(2, "done")
      this._updateStep(3, "active")
      resultEl.innerHTML = `<div class="loading">步骤 3/6：正在生成${typeNames[this._currentType]}...</div>`

      let resp
      const apiCalls = {
        world_character: api.generate.worldCharacter,
        plot: api.generate.plotStructure,
        chapter: api.generate.chapterScene,
        review: api.generate.reviewMemory,
      }
      resp = await apiCalls[this._currentType]({ novel_id: _state.currentProjectId, intent, context: {} })

      this._updateStep(3, resp ? "done" : "active")
      this._updateStep(4, "active")

      let previewHtml = `<div class="card" style="border-color:var(--accent);">`
      if (resp && resp.id) {
        previewHtml += `
          <p style="color:var(--accent);">&#10003; 任务已提交</p>
          <p style="color:var(--text-muted);font-size:12px;">任务 ID: ${resp.id}<br>类型: ${typeNames[this._currentType]}<br>${resp.status ? `状态: ${resp.status}` : ""}</p>
          <p style="color:var(--text-dim);font-size:12px;">任务正在后台运行。完成后可以在对应模块查看结果。</p>
        `
      } else {
        previewHtml += `
          <p style="color:var(--accent);">&#10003; 生成请求已发送</p>
          <p style="color:var(--text-muted);font-size:12px;">请在对应模块中查看生成的候选对象。</p>
        `
      }
      previewHtml += '</div>'
      resultEl.innerHTML = previewHtml
      this._updateStep(4, "done")

      setTimeout(() => { this._updateStep(5, "active"); this._updateStep(6, "") }, 500)
    } catch (err) {
      this._updateStep(2, "")
      const errMsg = esc(err.message)
      resultEl.innerHTML = `
        <div style="color:var(--danger);padding:12px;border:1px solid var(--danger);border-radius:4px;">
          <strong>生成失败</strong>
          <p style="margin:4px 0 0 0;font-size:13px;">${errMsg}</p>
          <p style="color:var(--text-dim);font-size:12px;margin:4px 0 0 0;">请确认后端已启动，并且项目已选择。</p>
          <button class="btn btn-sm" style="margin-top:8px;" data-action="start-generate">重试</button>
        </div>
      `
      toast(`生成失败：${err.message}`, "error")
    }
  },
}

router.registerView("generate", generateView)
window.generateView = generateView
export default generateView
