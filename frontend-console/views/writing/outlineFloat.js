/**
 * 大纲浮窗模块
 *
 * 负责大纲浮窗的展开/收起与内容加载。
 */

export function createOutlineFloat({ state, api, esc }) {
  const projectState = state
  const escapeHtml = esc

  function currentProjectId() {
    return projectState.currentProjectId
  }

  async function toggle() {
    const panel = document.getElementById("outline-float-panel")
    if (!panel) return
    const opening = panel.classList.contains("hidden")
    panel.classList.toggle("hidden", !opening)
    document.body.classList.toggle("outline-float-open", opening)
    if (opening) await load()
  }

  function close() {
    const panel = document.getElementById("outline-float-panel")
    panel?.classList.add("hidden")
    document.body.classList.remove("outline-float-open")
  }

  async function load() {
    const body = document.getElementById("outline-float-body")
    const projectId = currentProjectId()
    if (!body || !projectId) return
    try {
      const response = await api.outline.listThreads(projectId, { limit: 50 })
      const threads = response.items || response || []
      const currentChapter = projectState._currentChapter
      body.innerHTML = threads.length ? `
        <div class="outline-float-list">
          ${threads.map((thread) => `
            <article class="outline-float-item">
              <div class="outline-float-title">${escapeHtml(thread.title || thread.name || "未命名剧情线")}</div>
              <div class="outline-float-chapters">
                ${(thread.chapter_ids || thread.chapters || []).map((chapter) => `
                  <button class="outline-float-chapter ${String(chapter) === String(currentChapter) ? "current" : ""}"
                    data-action="select-chapter" data-chapter="${escapeHtml(chapter)}">${escapeHtml(chapter)}</button>
                `).join("") || '<span class="muted">暂无章节映射</span>'}
              </div>
            </article>
          `).join("")}
        </div>
      ` : '<p class="muted">暂无大纲条目</p>'
    } catch {
      body.innerHTML = '<p class="muted">大纲加载失败</p>'
    }
  }

  function render() {
    return `
      <div id="outline-float-panel" class="outline-float-panel hidden">
        <div class="outline-float-header">
          <span>大纲</span>
          <button class="btn-icon" data-action="close-outline-float" title="关闭大纲浮窗">&times;</button>
        </div>
        <div class="outline-float-body" id="outline-float-body">
          <p class="muted">加载中...</p>
        </div>
      </div>
    `
  }

  function dispose() {
    close()
  }

  return {
    toggle,
    close,
    render,
    dispose,
  }
}
