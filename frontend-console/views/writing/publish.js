/**
 * 章节发布管理器
 *
 * 负责发布提交与后台轮询、进度条渲染、错误弹窗与重试。
 * 发布前的二次确认由 writingView orchestrator 负责。
 * 从 writingView.js 拆分，便于独立测试。
 */

import { renderFixedProgress } from "../../shared/progressRenderer.js"
import { normalizeTaskProgress, sanitizeTaskErrorMessage } from "../../shared/workflowProgress.js"

export function createPublishManager({ state, api, toast, modal, esc, onStatusChange, onPublished }) {
  let _publishTaskId = null
  let _publishProgress = null
  let _publishTimer = null
  let _errorModalVisible = false

  let _lastContent = ""
  let _lastTitle = ""
  let _lastChapterIndex = null
  let _lastScene = null

  function _normalizePublishProgress() {
    const p = _publishProgress || {}
    const status = p.phase === "failed" ? "failed" : p.phase === "done" ? "done" : "running"
    return normalizeTaskProgress({
      task_id: _publishTaskId || "publish_chapter",
      task_type: "publish_chapter",
      status,
      progress: typeof p.step === "number" ? p.step : 0,
      error_message: status === "failed" ? p.message : null,
      result: {
        message: p.message || "发布中...",
      },
    }, "publish_chapter")
  }

  function renderBar() {
    if (!_publishProgress) return ""

    const progress = _normalizePublishProgress()
    const actionsHtml = progress.failed
      ? `<button class="btn btn-sm" data-action="dismiss-publish-error" style="font-size:11px;">关闭</button>`
      : ""

    return renderFixedProgress(progress, {
      title: "发布正文",
      message: progress.message,
      showTaskId: false,
      actionsHtml,
    })
  }

  function updateBar(container = document) {
    const publishBarEl = container.querySelector
      ? container.querySelector("#writing-publish-bar-container")
      : document.getElementById("writing-publish-bar-container")
    if (publishBarEl) publishBarEl.innerHTML = renderBar()
    const dot = document.getElementById("publish-status-dot")
    if (dot && _publishProgress && _publishProgress.phase === "running") {
      dot.style.display = "inline-block"
    }
  }

  async function publish(content, title, chapterIndex, currentDraftId, currentScene) {
    if (_publishProgress?.phase === "running" || _publishTaskId) {
      toast("发布任务正在进行中", "info")
      return
    }

    if (!content || !content.trim()) {
      toast("草稿内容不能为空", "warning")
      return
    }

    _lastContent = content
    _lastTitle = title || `第 ${chapterIndex} 章`
    _lastChapterIndex = chapterIndex
    _lastScene = currentScene

    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: chapterIndex,
        scene_id: currentScene?.id || null,
        title: _lastTitle,
        content,
      })

      if (result.task_id) {
        _publishTaskId = result.task_id
        _publishProgress = { phase: "running", step: 0, message: "正在存入 RAG 系统...", showModal: false }
        _startPublishPolling()
      } else {
        _publishProgress = { phase: "done", step: 1, message: "发布完成" }
      }

      onStatusChange("发布成功")
      toast("已发布", "success")
      onPublished(result)
      return result
    } catch (err) {
      toast(err.message || "发布失败", "error")
      onStatusChange("发布失败")
    }
  }

  async function retry() {
    if (!_lastChapterIndex) return
    _publishTaskId = null
    _publishProgress = { phase: "running", step: 0, message: "正在重试...", showModal: false }
    updateBar()
    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: _lastChapterIndex,
        scene_id: _lastScene?.id || null,
        title: _lastTitle || "",
        content: _lastContent || "",
      })
      if (result.task_id) {
        _publishTaskId = result.task_id
        _startPublishPolling()
      } else {
        _publishProgress = { phase: "done", step: 1, message: "发布完成" }
        onStatusChange("发布成功")
        toast("已发布", "success")
        onPublished(result)
      }
      return result
    } catch (err) {
      toast(err.message || "重试失败", "error")
      _publishProgress = null
      onStatusChange("发布失败")
    }
  }

  function _startPublishPolling() {
    if (_publishTimer) clearInterval(_publishTimer)
    const poll = async () => {
      if (!_publishTaskId) { _stopPublishPolling(); return }
      try {
        const task = await api.tasks.get(_publishTaskId, state.currentProjectId)
        let needStatusUpdate = false

        if (task.progress !== undefined && task.progress !== null) {
          const p = parseFloat(task.progress)
          if (_publishProgress.step !== p || _publishProgress.phase !== task.status) {
            _publishProgress.step = p
            _publishProgress.phase = task.status
            if (p < 0.5) {
              _publishProgress.message = "正在存入 RAG 系统..."
            } else if (p < 1.0) {
              _publishProgress.message = "正在创建历史状态..."
            }
            needStatusUpdate = true
          }
        }

        if (task.status === "done" && _publishProgress) {
          _publishProgress.step = 1
          _publishProgress.phase = "done"
          _publishProgress.message = "发布完成"
          onStatusChange("发布成功")
          toast("已发布", "success")
          updateBar()
          _stopPublishPolling()
          setTimeout(() => { _publishProgress = null; onPublished({}) }, 3000)
          return
        }

        if (task.status === "failed") {
          _publishProgress.phase = "failed"
          const errMsg = sanitizeTaskErrorMessage(
            task.error_message || task.result?.error_message || task.result?.error,
            "publish_chapter",
          ) || "发布任务失败。草稿已保存，请稍后重试。"
          _publishProgress.message = errMsg
          _publishProgress.showModal = true
          onStatusChange("发布失败")
          updateBar()
          _stopPublishPolling()
          _showPublishErrorModal(errMsg)
          return
        }

        updateBar()
        if (needStatusUpdate) {
          onStatusChange(_publishProgress.message)
        }
      } catch (err) {
        if (_publishProgress) {
          const errMsg = sanitizeTaskErrorMessage(
            err?.message || "发布状态查询失败。草稿已保存，请稍后重试。",
            "publish_chapter",
          ) || "发布状态查询失败。草稿已保存，请稍后重试。"
          _publishProgress.phase = "failed"
          _publishProgress.message = errMsg
          _publishProgress.showModal = true
          onStatusChange("发布失败")
          updateBar()
          _showPublishErrorModal(errMsg)
        }
        _stopPublishPolling()
      }
    }
    poll()
    _publishTimer = setInterval(poll, 2000)
  }

  function _stopPublishPolling() {
    if (_publishTimer) { clearInterval(_publishTimer); _publishTimer = null }
    _publishTaskId = null
    const dot = document.getElementById("publish-status-dot")
    if (dot) dot.style.display = "none"
  }

  function _showPublishErrorModal(msg) {
    _errorModalVisible = true
    modal.showHtml("发布失败", `
      <p>${esc(msg)}</p>
      <p style="color:var(--text-dim);font-size:11px;margin-top:8px;">草稿已保存成功。您可以手动重试失败的步骤。</p>
      <div style="margin-top:12px;display:flex;gap:6px;justify-content:flex-end;">
        <button class="btn" id="btn-dismiss-publish-modal">关闭</button>
        <button class="btn btn-primary" id="btn-retry-failed">手动重试</button>
      </div>
    `)
    setTimeout(() => {
      const retryBtn = document.getElementById("btn-retry-failed")
      if (retryBtn) retryBtn.onclick = () => { modal.close(); retry() }
      const dismissBtn = document.getElementById("btn-dismiss-publish-modal")
      if (dismissBtn) dismissBtn.onclick = () => { modal.close(); dismissError() }
    }, 100)
  }

  function dismissError() {
    _publishProgress = null
    _publishTaskId = null
    _errorModalVisible = false
    _stopPublishPolling()
    onStatusChange(null)
  }

  function dispose() {
    _stopPublishPolling()
    _publishProgress = null
    _errorModalVisible = false
  }

  return {
    publish,
    retry,
    renderBar,
    updateBar,
    dismissError,
    dispose,
  }
}
