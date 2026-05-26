/**
 * 结构复查视图
 */

const reviewView = {
  onLeave() {},

  async render() {
    setTimeout(() => this._bindEvents(), 0)
    return `
      <div class="empty-state">
        <div class="empty-icon">&#128269;</div>
        <p>结构复查</p>
        <p style="color:var(--text-dim);font-size:12px;">
          对候选结构进行全维度检查，包括 Schema 校验、实体引用检查、
          提前揭示检测、人物知识边界验证、时间线冲突检查、地理冲突检查和重复检测。
        </p>
        <div style="margin-top:12px;">
          <button class="btn btn-primary" data-action="review">运行复查</button>
        </div>
      </div>

      <div id="review-output" style="margin-top:12px;max-width:600px;margin-left:auto;margin-right:auto;"></div>
    `
  },

  _bindEvents() {
    const content = document.getElementById("workspace-content")
    if (!content) return
    content.removeEventListener("click", this._clickHandler)
    this._clickHandler = (e) => {
      const btn = e.target.closest("[data-action='review']")
      if (btn) this.runReview()
    }
    content.addEventListener("click", this._clickHandler)
  },

  async runReview() {
    const output = document.getElementById("review-output")
    if (!output) return

    output.innerHTML = '<div class="loading">复查中</div>'

    try {
      const data = await api.review.run({
        novel_id: _state.currentProjectId,
        target_type: "chapter_cards",
        candidate_payload: {},
      })

      const report = data || {}
      const decision = report.decision || "none"
      const decisionColors = {
        pass: "var(--success)",
        minor_revision: "var(--warning)",
        major_revision: "var(--warning)",
        reject: "var(--danger)",
      }

      let html = '<div class="card">'
      html += `<div class="card-title">复查结果</div>`
      html += `<p style="color:${decisionColors[decision] || "var(--text)"};">结论：${decision}</p>`
      html += report.score ? `<p>综合评分：${report.score}</p>` : ""

      const allProblems = [
        ...(report.problems || []),
        ...(report.conflict_warnings || []).map((w) => ({ ...w, type: "timeline_conflict" })),
        ...(report.early_reveal_warnings || []).map((w) => ({ ...w, type: "early_reveal" })),
        ...(report.character_knowledge_warnings || []).map((w) => ({ ...w, type: "character_knowledge" })),
        ...(report.duplicate_entity_warnings || []).map((w) => ({ ...w, type: "duplicate" })),
      ]

      if (allProblems.length > 0) {
        html += '<div style="margin-top:12px;"><h4 style="color:var(--accent);">发现的问题</h4>'
        for (const p of allProblems) {
          const severityMap = { high: "高", medium: "中", low: "低" }
          const severityColors = { high: "var(--danger)", medium: "var(--warning)", low: "var(--text-muted)" }
          const msg = esc(p.message || "未命名问题")
          const sev = esc(severityMap[p.severity] || p.severity)
          const sevColor = severityColors[p.severity] || "var(--text-muted)"
          html += `
            <div class="collapsible" style="margin-top:4px;">
              <div class="collapsible-header" onclick="this.parentElement.classList.toggle('open')">
                <span>${msg}</span>
                <span style="color:${sevColor};font-size:11px;">
                  [${sev}]
                </span>
                <span class="collapse-icon">&gt;</span>
              </div>
            </div>
          `
        }
        html += '</div>'
      } else {
        html += '<p style="color:var(--success);margin-top:8px;">✓ 未发现结构问题</p>'
      }

      if (report.revision_instructions && report.revision_instructions.length > 0) {
        html += '<div style="margin-top:12px;"><h4 style="color:var(--accent);">修改建议</h4><ul>'
        for (const instr of report.revision_instructions) {
          html += `<li style="color:var(--text-muted);font-size:12px;">${esc(instr)}</li>`
        }
        html += '</ul></div>'
      }

      html += "</div>"
      output.innerHTML = html
    } catch (err) {
      output.innerHTML = `<div class="card" style="border-color:var(--danger);"><p style="color:var(--danger);">复查失败：${esc(err.message)}</p></div>`
    }
  },
}

router.registerView("review", reviewView)
window.reviewView = reviewView
export default reviewView
