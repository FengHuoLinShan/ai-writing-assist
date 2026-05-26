/**
 * 轻量时间线视图
 *
 * 对应后端 timeline_events: 列表、新建、编辑、删除。
 */

const timelineView = {
  _events: [],

  async onEnter() {
    this._events = []
    await this._loadEvents()
  },

  async render() {
    if (!_state.currentProjectId) {
      return `<div class="empty-state"><p>请先选择项目。</p></div>`
    }

    setTimeout(() => {
      const content = document.getElementById("workspace-content")
      if (!content) return
      content.removeEventListener("click", this._clickHandler)
      this._clickHandler = (e) => {
        const target = e.target.closest("[data-action]")
        if (!target) return
        const action = target.getAttribute("data-action")
        const id = target.getAttribute("data-id")
        switch (action) {
          case "create-event": this.showCreateForm(); break
          case "edit-event": if (id) this.showEditForm(id); break
          case "delete-event": if (id) this.deleteEvent(id); break
        }
      }
      content.addEventListener("click", this._clickHandler)
    }, 0)

    let html = `
      <p style="color:var(--text-muted);font-size:12px;margin-bottom:12px;">
        维护事件顺序，防止剧情冲突。轻量时间线，不做复杂时间推理。
      </p>
      <div style="margin-bottom:8px;display:flex;gap:8px;">
        <button class="btn btn-primary" data-action="create-event">新建事件</button>
      </div>
    `

    if (this._events.length === 0) {
      html += `<div class="empty-state"><p>暂无时间线事件。</p></div>`
    } else {
      const visMap = { author_only: "作者可见", author_safe: "作者安全", reader_known: "读者已知", public: "公开" }
      html += `
      <table class="data-table">
        <thead><tr>
          <th style="width:40px;">#</th>
          <th style="width:50px;">章节</th>
          <th>事件</th>
          <th>类型</th>
          <th>可见性</th>
          <th>操作</th>
        </tr></thead>
        <tbody>
      `
      for (const e of this._events) {
        html += `
        <tr data-id="${esc(e.id || e.event_id)}">
          <td style="color:var(--text-dim);">${esc(e.order_index)}</td>
          <td>${esc(e.chapter_index) || "-"}</td>
          <td><strong>${esc(e.title)}</strong><br><span style="color:var(--text-dim);font-size:11px;">${esc(e.summary || "").slice(0, 100)}</span></td>
          <td><span class="badge badge-draft">${esc(e.event_type || "-")}</span></td>
          <td>${visMap[e.visibility] || esc(e.visibility)}</td>
          <td style="display:flex;gap:4px;">
            <button class="btn btn-sm" data-action="edit-event" data-id="${esc(e.id || e.event_id)}">编辑</button>
            <button class="btn btn-sm btn-danger" data-action="delete-event" data-id="${esc(e.id || e.event_id)}">删除</button>
          </td>
        </tr>`
      }
      html += `</tbody></table>`
    }
    return html
  },

  async _loadEvents() {
    if (!_state.currentProjectId) return
    try {
      const data = await api.timeline.listEvents({ novel_id: _state.currentProjectId })
      this._events = data.items || data || []
    } catch { this._events = [] }
  },

  showCreateForm() {
    const formHtml = `
      <div class="form-group">
        <label>事件标题 *</label>
        <input class="form-input" id="tl-title" placeholder="事件名称" />
      </div>
      <div class="form-group">
        <label>摘要</label>
        <textarea class="form-textarea" id="tl-summary" rows="2" placeholder="事件描述"></textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>排序</label>
          <input class="form-input" id="tl-order" type="number" min="1" value="${this._events.length + 1}" />
        </div>
        <div class="form-group">
          <label>关联章节</label>
          <input class="form-input" id="tl-chapter" type="number" min="1" placeholder="可选" />
        </div>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>事件类型</label>
          <select class="form-select" id="tl-type">
            <option value="plot">剧情事件</option>
            <option value="character">人物事件</option>
            <option value="world">世界观事件</option>
            <option value="battle">战斗/冲突</option>
            <option value="discovery">发现/揭示</option>
          </select>
        </div>
        <div class="form-group">
          <label>可见性</label>
          <select class="form-select" id="tl-visibility">
            <option value="author_only">作者可见</option>
            <option value="author_safe">作者安全</option>
            <option value="reader_known">读者已知</option>
            <option value="public">公开</option>
          </select>
        </div>
      </div>
    `
    showModal("新建时间线事件", formHtml, [{
      text: "创建", class: "btn-primary", handler: async () => {
        const title = document.getElementById("tl-title")?.value
        if (!title) { toast("请输入事件标题", "warning"); return }
        try {
          await api.timeline.createEvent({
            novel_id: _state.currentProjectId,
            title, summary: document.getElementById("tl-summary")?.value || "",
            order_index: parseInt(document.getElementById("tl-order")?.value || "1", 10),
            chapter_index: parseInt(document.getElementById("tl-chapter")?.value || "0", 10) || undefined,
            event_type: document.getElementById("tl-type")?.value || "plot",
            visibility: document.getElementById("tl-visibility")?.value || "author_only",
          })
          toast("事件已创建", "success")
          router.navigate("timeline")
        } catch (err) { toast(err.message || "创建失败", "error") }
      },
    }])
  },

  showEditForm(eventId) {
    const ev = this._events.find(e => (e.id || e.event_id) === eventId)
    if (!ev) return
    const formHtml = `
      <div class="form-group">
        <label>事件标题</label>
        <input class="form-input" id="tl-title" value="${esc(ev.title)}" />
      </div>
      <div class="form-group">
        <label>摘要</label>
        <textarea class="form-textarea" id="tl-summary" rows="2">${esc(ev.summary || "")}</textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label>排序</label>
          <input class="form-input" id="tl-order" type="number" value="${esc(ev.order_index)}" />
        </div>
        <div class="form-group">
          <label>关联章节</label>
          <input class="form-input" id="tl-chapter" type="number" value="${esc(ev.chapter_index || "")}" />
        </div>
      </div>
    `
    showModal("编辑时间线事件", formHtml, [{
      text: "保存", class: "btn-primary", handler: async () => {
        try {
          await api.timeline.updateEvent(_state.currentProjectId, eventId, {
            title: document.getElementById("tl-title")?.value,
            summary: document.getElementById("tl-summary")?.value,
            order_index: parseInt(document.getElementById("tl-order")?.value || "1", 10),
            chapter_index: parseInt(document.getElementById("tl-chapter")?.value || "0", 10) || undefined,
          })
          toast("已保存", "success")
          router.navigate("timeline")
        } catch (err) { toast(err.message || "保存失败", "error") }
      },
    }])
  },

  deleteEvent(eventId) {
    confirmAction("确定删除此事件？", async () => {
      try {
        await api.timeline.updateEvent(_state.currentProjectId, eventId, { status: "deprecated" })
        toast("已删除", "success")
        router.navigate("timeline")
      } catch (err) { toast(err.message || "删除失败", "error") }
    }, "确认删除")
  },
}

router.registerView("timeline", timelineView)
window.timelineView = timelineView
export default timelineView
