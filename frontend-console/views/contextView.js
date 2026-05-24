/**
 * 上下文视图
 *
 * 帮助作者看到 AI 生成结构时到底参考了什么。
 * 支持：输入任务 → 编译上下文 → 预览 Markdown → 复制/导出
 */
const contextView = {
  onLeave() {
    this._lastBundle = null
    this._lastMarkdown = null
  },

  /** @type {Object|null} 上次编译结果 */
  _lastBundle: null,

  async render() {
    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:16px;">
        Context Compiler 决定哪些资料真正交给 AI 模型。
        在此可以预览 AI 生成结构时使用的上下文。
        编译后的上下文可直接复制到任何 Prompt 中。
      </p>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <!-- 左侧：输入区 -->
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
              <label>揭示模式</label>
              <select class="form-select" id="ctx-reveal">
                <option value="author_safe">作者安全模式（隐藏隐藏真相）</option>
                <option value="author_only">作者全知模式（显示所有信息）</option>
              </select>
            </div>
            <button class="btn btn-primary" id="btn-compile-ctx" onclick="contextView.compile()">编译上下文</button>
            <button class="btn" id="btn-render-ctx" onclick="contextView.renderMarkdown()" disabled style="margin-left:8px;">渲染 Markdown</button>
          </div>
        </div>

        <!-- 右侧：输出区 -->
        <div>
          <div class="card" style="min-height:300px;">
            <div class="card-title" style="display:flex;justify-content:space-between;align-items:center;">
              <span>输出</span>
              <span>
                <button class="btn btn-sm" id="btn-copy-ctx" onclick="contextView.copyMarkdown()" disabled>复制</button>
                <button class="btn btn-sm" id="btn-export-ctx" onclick="contextView.exportContext()" disabled>导出</button>
              </span>
            </div>
            <div id="ctx-output" style="margin-top:8px;font-size:13px;line-height:1.6;">
              <p style="color:var(--text-dim);">填写左侧参数后点击编译。</p>
            </div>
          </div>
        </div>
      </div>
    `
    return html
  },

  async compile() {
    const output = document.getElementById("ctx-output")
    const renderBtn = document.getElementById("btn-render-ctx")
    const copyBtn = document.getElementById("btn-copy-ctx")
    const exportBtn = document.getElementById("btn-export-ctx")
    if (!output) return

    const task = document.getElementById("ctx-task")?.value || ""
    const scope = document.getElementById("ctx-scope")?.value || "arc"
    const reveal = document.getElementById("ctx-reveal")?.value || "author_safe"
    const entitiesInput = document.getElementById("ctx-entities")?.value || ""
    const charactersInput = document.getElementById("ctx-characters")?.value || ""
    const chapterInput = document.getElementById("ctx-chapter")?.value || ""

    if (!task) {
      toast("请输入任务描述", "warning")
      return
    }

    const entityIds = entitiesInput ? entitiesInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const characterIds = charactersInput ? charactersInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const chapterIndex = chapterInput ? parseInt(chapterInput, 10) : undefined

    output.innerHTML = '<div class="loading">编译中...</div>'
    if (renderBtn) renderBtn.disabled = true
    if (copyBtn) copyBtn.disabled = true
    if (exportBtn) exportBtn.disabled = true

    try {
      const data = await api.context.compile({
        novel_id: _state.currentProjectId,
        task,
        scope,
        chapter_index: chapterIndex,
        entity_ids: entityIds,
        character_ids: characterIds,
        reveal_mode: reveal,
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

    // 统计信息
    html += '<div style="margin-bottom:12px;padding:8px;background:var(--panel);border-radius:4px;border:1px solid var(--border);">'
    html += `<span style="color:var(--accent);font-size:13px;">已加载 ${data.section_count} 段上下文</span>`
    html += `<span style="color:var(--text-dim);margin-left:12px;">范围：${esc(data.scope)}</span>`
    html += `<span style="color:var(--text-dim);margin-left:12px;">揭示模式：${esc(data.reveal_mode)}</span>`
    html += '</div>'

    // 预算使用
    if (data.budgets && data.budgets.length > 0) {
      html += '<table class="data-table" style="margin-bottom:12px;"><thead><tr><th>类别</th><th>预算</th><th>已用</th></tr></thead><tbody>'
      for (const b of data.budgets) {
        const pct = b.budget > 0 ? Math.round((b.used / b.budget) * 100) : 0
        const pctColor = pct > 80 ? "var(--danger)" : pct > 50 ? "var(--warning)" : "var(--accent)"
        const catName = esc(this._budgetName(b.category))
        html += `<tr>
          <td style="color:var(--text-muted);">${catName}</td>
          <td>${b.budget}</td>
          <td style="color:${pctColor};">${b.used} (${pct}%)</td>
        </tr>`
      }
      html += '</tbody></table>'
    }

    // 来源显示
    if (data.sections_present && data.sections_present.length > 0) {
      html += '<div style="margin-bottom:12px;">'
      html += '<strong style="color:var(--text-muted);font-size:12px;">加载的段落来源：</strong>'
      html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">'
      const sourceNames = {
        project: "📁 项目信息",
        world_entities: "🌍 世界对象",
        characters: "👤 人物档案",
        geo_locations: "🗺️ 地理地点",
        memory_records: "📝 长期记忆",
        timeline_events: "📅 时间线事件",
        plot_threads: "🧵 剧情线",
        outline_arc: "📖 篇章纲",
        chapter_card: "📄 章节卡",
        rag_chunks: "🔍 RAG 片段",
      }
      for (const section of data.sections_present) {
        const secName = esc(sourceNames[section] || section)
        html += `<span style="background:var(--panel);color:var(--text);padding:2px 8px;border-radius:3px;font-size:11px;border:1px solid var(--border);">${secName}</span>`
      }
      html += '</div></div>'
    }

    // 警告
    if (data.warnings && data.warnings.length > 0) {
      html += '<div style="margin-bottom:12px;padding:8px;background:rgba(255,204,102,0.1);border-radius:4px;border:1px solid var(--warning);">'
      html += '<strong style="color:var(--warning);font-size:12px;">⚠ 警告</strong>'
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
    const copyBtn = document.getElementById("btn-copy-ctx")
    const exportBtn = document.getElementById("btn-export-ctx")
    if (!output || !this._lastBundle) return

    const task = document.getElementById("ctx-task")?.value || ""
    const scope = document.getElementById("ctx-scope")?.value || "arc"
    const reveal = document.getElementById("ctx-reveal")?.value || "author_safe"
    const entitiesInput = document.getElementById("ctx-entities")?.value || ""
    const charactersInput = document.getElementById("ctx-characters")?.value || ""
    const chapterInput = document.getElementById("ctx-chapter")?.value || ""

    const entityIds = entitiesInput ? entitiesInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const characterIds = charactersInput ? charactersInput.split(",").map((s) => s.trim()).filter((s) => s) : undefined
    const chapterIndex = chapterInput ? parseInt(chapterInput, 10) : undefined

    try {
      const data = await api.context.render({
        novel_id: _state.currentProjectId,
        task,
        scope,
        chapter_index: chapterIndex,
        entity_ids: entityIds,
        character_ids: characterIds,
        reveal_mode: reveal,
      })

      if (data && data.markdown) {
        // 渲染为可折叠的 Markdown 预览
        output.innerHTML = `<pre style="background:var(--bg);color:var(--text);padding:16px;border-radius:4px;border:1px solid var(--border);font-size:12px;line-height:1.6;overflow-x:auto;white-space:pre-wrap;word-break:break-word;">${this._escapeHtml(data.markdown)}</pre>`
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
      a.download = `context-${_state.currentProject?.title || "project"}-${Date.now()}.md`
      a.click()
      URL.revokeObjectURL(url)
      toast("上下文已导出为 Markdown 文件", "success")
    }
  },

  _budgetName(key) {
    const names = {
      core_entities: "核心对象",
      normal_entities: "普通对象",
      characters: "人物",
      memory: "记忆",
      timeline: "时间线",
      geo_relations: "地理关系",
      plot_threads: "剧情线",
      rag_chunks: "RAG 片段",
    }
    return names[key] || key
  },

  _escapeHtml(str) {
    const div = document.createElement("div")
    div.textContent = str
    return div.innerHTML
  },
}

router.registerView("context", contextView)
window.contextView = contextView
