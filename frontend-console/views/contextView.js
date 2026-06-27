/**
 * 上下文视图
 */

import { bindWorkspaceClick } from "../shared/viewHelper.js"

const contextView = {
  onLeave() {
    this._lastBundle = null
    this._lastMarkdown = null
  },

  _lastBundle: null,
  _lastMarkdown: null,

  async render() {
    setTimeout(() => this._bindEvents(), 0)
    return `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:16px;">
        Context Compiler 决定哪些资料真正交给 AI 模型。
        在此可以预览 AI 生成结构时使用的上下文。
      </p>

      <div class="two-column-workspace context-workspace">
        <div>
          <div class="card">
            <div class="card-title">编译上下文</div>
            <div class="form-group">
              <label>任务描述 *</label>
              <textarea class="form-textarea" id="ctx-task" rows="2" placeholder="如：为旧档案缺页篇生成 10 章章节卡"></textarea>
            </div>
            <div class="form-group">
              <label>范围</label>
              <select class="form-select" id="ctx-scope">
                <option value="project">项目信息</option>
                <option value="world">世界对象</option>
                <option value="world_character">世界+人物</option>
                <option value="arc" selected>篇章</option>
                <option value="chapter">章节</option>
                <option value="full">全部</option>
              </select>
            </div>
            <div class="form-group">
              <label>相关对象</label>
              <input class="form-input" id="ctx-entities" placeholder="输入 world_entity ID，逗号分隔（可选）" />
            </div>
            <div class="form-group">
              <label>相关人物</label>
              <input class="form-input" id="ctx-characters" placeholder="输入 character ID，逗号分隔（可选）" />
            </div>
            <div class="form-group">
              <label>章节索引</label>
              <input class="form-input" id="ctx-chapter" type="number" min="1" placeholder="当前章节（可选）" />
            </div>
            <div class="form-group">
              <label>Scene ID</label>
              <input class="form-input" id="ctx-scene" placeholder="当前 Scene ID（可选，优先于章节）" />
            </div>
            <div class="form-group">
              <label>预算 (tokens)</label>
              <input class="form-input" id="ctx-budget" type="number" min="500" max="32000" value="4000" />
            </div>
            <div class="form-group">
              <label>揭示模式</label>
              <select class="form-select" id="ctx-reveal">
                <option value="author_safe">作者安全模式（隐藏隐藏真相）</option>
                <option value="author_full">作者全知模式（显示所有信息）</option>
                <option value="reader">读者模式（仅显示读者已知信息）</option>
                <option value="character">角色视角模式（按人物知识边界）</option>
              </select>
            </div>
            <button class="btn btn-primary" data-action="compile">编译上下文</button>
            <button class="btn" data-action="render-md" disabled style="margin-left:8px;">渲染 Markdown</button>
          </div>
        </div>

        <div>
          <div class="card" style="min-height:300px;">
            <div class="card-title" style="display:flex;justify-content:space-between;align-items:center;">
              <span>输出</span>
              <span>
                <button class="btn btn-sm" data-action="copy" disabled>复制</button>
                <button class="btn btn-sm" data-action="export" disabled>导出</button>
              </span>
            </div>
            <div id="ctx-output" style="margin-top:8px;font-size:13px;line-height:1.6;">
              <p style="color:var(--text-dim);">填写左侧参数后点击编译。</p>
            </div>
          </div>
        </div>
      </div>
    `
  },

  _bindEvents() {
    bindWorkspaceClick(this, {
      "compile": () => this.compile(),
      "render-md": () => this.renderMarkdown(),
      "copy": () => this.copyMarkdown(),
      "export": () => this.exportContext(),
    })
  },

  async compile() {
    const output = document.getElementById("ctx-output")
    const renderBtn = document.querySelector('[data-action="render-md"]')
    const copyBtn = document.querySelector('[data-action="copy"]')
    const exportBtn = document.querySelector('[data-action="export"]')
    if (!output) return

    if (!state.currentProjectId) {
      toast("请先选择项目", "warning")
      return
    }

    const task = document.getElementById("ctx-task")?.value || ""
    const scope = document.getElementById("ctx-scope")?.value || "arc"
    const reveal = document.getElementById("ctx-reveal")?.value || "author_safe"
    const entitiesInput = document.getElementById("ctx-entities")?.value || ""
    const charactersInput = document.getElementById("ctx-characters")?.value || ""
    const chapterInput = document.getElementById("ctx-chapter")?.value || ""
    const sceneInput = document.getElementById("ctx-scene")?.value || ""
    const budgetInput = document.getElementById("ctx-budget")?.value || ""

    if (!task) {
      toast("请输入任务描述", "warning")
      return
    }

    const entityIds = entitiesInput ? entitiesInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const characterIds = charactersInput ? charactersInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const chapterIndex = chapterInput ? parseInt(chapterInput, 10) : undefined
    const sceneId = sceneInput ? sceneInput.trim() : undefined
    const budgetTokens = budgetInput ? parseInt(budgetInput, 10) : 4000
    const viewpointCharacterId = reveal === "character" ? characterIds?.[0] : undefined
    if (reveal === "character" && !viewpointCharacterId) {
      toast("角色视角模式必须选择或输入视角人物 ID", "warning")
      return
    }

    output.innerHTML = '<div class="loading">编译中...</div>'
    if (renderBtn) renderBtn.disabled = true
    if (copyBtn) copyBtn.disabled = true
    if (exportBtn) exportBtn.disabled = true

    try {
      const data = await api.context.compile({
        novel_id: state.currentProjectId,
        task, scope,
        chapter_index: chapterIndex,
        scene_id: sceneId,
        budget_tokens: budgetTokens,
        entity_ids: entityIds,
        character_ids: characterIds,
        reveal_mode: reveal,
        viewpoint_character_id: viewpointCharacterId,
      })
      this._lastBundle = data
      this._renderCompileResult(data)
      if (renderBtn) renderBtn.disabled = false
    } catch (err) {
      const errMsg = esc(err.message)
      output.innerHTML = `<div style="color:var(--danger);padding:12px;border:1px solid var(--danger);border-radius:4px;">
        <strong>编译失败</strong>
        <p style="margin:4px 0 0 0;font-size:13px;">${errMsg}</p>
        <p style="color:var(--text-dim);font-size:12px;margin:4px 0 0 0;">请确认后端已启动。</p>
      </div>`
    }
  },

  _renderCompileResult(data) {
    const output = document.getElementById("ctx-output")
    if (!output) return
    let html = ''
    html += '<div style="margin-bottom:12px;padding:8px;background:var(--panel);border-radius:4px;border:1px solid var(--border);">'
    html += `<span style="color:var(--accent);font-size:13px;">已加载 ${data.sections?.length || 0} 段上下文</span>`
    html += `<span style="color:var(--text-dim);margin-left:12px;">范围：${esc(data.scope)}</span>`
    html += `<span style="color:var(--text-dim);margin-left:12px;">揭示模式：${esc(data.reveal_mode)}</span>`
    html += `<span style="color:var(--text-dim);margin-left:12px;">Tokens：${data.total_tokens || 0} / ${data.budget_tokens || 0}</span>`
    html += '</div>'

    if (data.sections && data.sections.length > 0) {
      html += '<table class="data-table" style="margin-bottom:12px;"><thead><tr><th>Tier</th><th>Section</th><th>Tokens</th><th>Truncated</th></tr></thead><tbody>'
      for (const section of data.sections) {
        const truncatedText = section.truncated ? "是" : "否"
        html += `<tr><td style="color:var(--text-muted);">${esc(this._tierName(section.tier))}</td><td>${esc(section.key)}</td><td>${section.token_count || 0}</td><td>${truncatedText}</td></tr>`
      }
      html += '</tbody></table>'
    }

    if (data.evicted && data.evicted.length > 0) {
      html += '<div style="margin-bottom:12px;"><strong style="color:var(--text-muted);font-size:12px;">已驱逐段落：</strong>'
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">'
      for (const key of data.evicted) {
        html += `<span style="background:var(--panel);color:var(--text);padding:2px 8px;border-radius:3px;font-size:11px;border:1px solid var(--border);">${esc(key)}</span>`
      }
      html += '</div></div>'
    }

    if (data.truncated && data.truncated.length > 0) {
      html += '<div style="margin-bottom:12px;"><strong style="color:var(--text-muted);font-size:12px;">已截断段落：</strong>'
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">'
      for (const key of data.truncated) {
        html += `<span style="background:var(--panel);color:var(--danger);padding:2px 8px;border-radius:3px;font-size:11px;border:1px solid var(--border);">${esc(key)}</span>`
      }
      html += '</div></div>'
    }

    if (data.warnings && data.warnings.length > 0) {
      html += '<div style="margin-bottom:12px;padding:8px;background:rgba(255,204,102,0.1);border-radius:4px;border:1px solid var(--warning);"><strong style="color:var(--warning);font-size:12px;">⚠ 警告</strong>'
      for (const w of data.warnings) {
        html += `<p style="color:var(--warning);font-size:12px;margin:2px 0;">${esc(w)}</p>`
      }
      html += '</div>'
    }
    html += '<p style="color:var(--text-dim);font-size:12px;">点击"渲染 Markdown"查看完整上下文内容。</p>'
    output.innerHTML = html
  },

  async renderMarkdown() {
    const output = document.getElementById("ctx-output")
    const copyBtn = document.querySelector('[data-action="copy"]')
    const exportBtn = document.querySelector('[data-action="export"]')
    if (!output || !this._lastBundle) return

    const task = document.getElementById("ctx-task")?.value || ""
    const scope = document.getElementById("ctx-scope")?.value || "arc"
    const reveal = document.getElementById("ctx-reveal")?.value || "author_safe"
    const entitiesInput = document.getElementById("ctx-entities")?.value || ""
    const charactersInput = document.getElementById("ctx-characters")?.value || ""
    const chapterInput = document.getElementById("ctx-chapter")?.value || ""
    const sceneInput = document.getElementById("ctx-scene")?.value || ""
    const budgetInput = document.getElementById("ctx-budget")?.value || ""
    const entityIds = entitiesInput ? entitiesInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const characterIds = charactersInput ? charactersInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const chapterIndex = chapterInput ? parseInt(chapterInput, 10) : undefined
    const sceneId = sceneInput ? sceneInput.trim() : undefined
    const budgetTokens = budgetInput ? parseInt(budgetInput, 10) : 4000
    const viewpointCharacterId = reveal === "character" ? characterIds?.[0] : undefined
    if (reveal === "character" && !viewpointCharacterId) {
      toast("角色视角模式必须选择或输入视角人物 ID", "warning")
      return
    }

    try {
      const data = await api.context.render({
        novel_id: state.currentProjectId, task, scope,
        chapter_index: chapterIndex, scene_id: sceneId,
        budget_tokens: budgetTokens,
        entity_ids: entityIds,
        character_ids: characterIds, reveal_mode: reveal,
        viewpoint_character_id: viewpointCharacterId,
      })
      if (data && data.markdown) {
        output.innerHTML = `<pre style="background:var(--bg);color:var(--text);padding:16px;border-radius:4px;border:1px solid var(--border);font-size:12px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-word;">${esc(data.markdown)}</pre>`
        this._lastMarkdown = data.markdown
        if (copyBtn) copyBtn.disabled = false
        if (exportBtn) exportBtn.disabled = false
      }
    } catch (err) {
      output.innerHTML = `<div style="color:var(--danger);padding:12px;">渲染失败：${esc(err.message)}</div>`
    }
  },

  copyMarkdown() {
    if (this._lastMarkdown) {
      navigator.clipboard.writeText(this._lastMarkdown)
        .then(() => toast("上下文 Markdown 已复制到剪贴板", "success"))
        .catch(() => toast("复制失败，请手动选择复制", "warning"))
    }
  },

  exportContext() {
    if (this._lastMarkdown) {
      const blob = new Blob([this._lastMarkdown], { type: "text/markdown;charset=utf-8" })
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `context-${state.currentProject?.title || "project"}-${Date.now()}.md`
      a.click()
      URL.revokeObjectURL(url)
      toast("上下文已导出为 Markdown 文件", "success")
    }
  },

  _budgetName(key) {
    const names = { core_entities: "核心对象", normal_entities: "普通对象", characters: "人物", memory: "记忆", timeline: "时间线", geo_relations: "地理关系", plot_threads: "剧情线", rag_chunks: "RAG 片段" }
    return names[key] || key
  },

  _tierName(key) {
    const names = { core: "核心", standard: "标准", memory: "记忆", rag: "RAG", optional: "可选" }
    return names[key] || key
  },
}

router.registerView("context", contextView)
window.contextView = contextView
export default contextView
