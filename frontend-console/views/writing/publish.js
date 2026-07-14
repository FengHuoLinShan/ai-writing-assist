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
  let _publishClearTimer = null
  let _errorModalVisible = false

  let _lastContent = ""
  let _lastTitle = ""
  let _lastChapterIndex = null
  let _lastScene = null
  let _lastDraftId = null
  let _lastVersionNumber = null
  let _lastUpdatedAt = null
  let _lastRestoreSourceVersion = null

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
      ? `<button class="btn btn-sm writing-btn-compact" data-action="dismiss-publish-error">关闭</button>`
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

  async function _notifyPublished(result) {
    onStatusChange("发布成功")
    try {
      await onPublished(result)
    } catch {
      toast("章节已发布，但写作台刷新失败，请手动刷新", "warning")
      return
    }
    toast("已发布", "success")
  }

  function _cancelProgressClear() {
    if (!_publishClearTimer) return
    clearTimeout(_publishClearTimer)
    _publishClearTimer = null
  }

  function _scheduleProgressClear() {
    _cancelProgressClear()
    _publishClearTimer = setTimeout(() => {
      _publishClearTimer = null
      _publishProgress = null
      updateBar()
    }, 3000)
  }

  async function publish(content, title, chapterIndex, currentDraftId, currentScene, currentVersionNumber, currentUpdatedAt) {
    if (_publishProgress?.phase === "running" || _publishTaskId) {
      toast("发布任务正在进行中", "info")
      return
    }

    if (!content || !content.trim()) {
      toast("工作稿内容不能为空", "warning")
      return
    }
    _cancelProgressClear()

    _lastContent = content
    _lastTitle = title || `第 ${chapterIndex} 章`
    _lastChapterIndex = chapterIndex
    _lastScene = currentScene
    _lastDraftId = currentDraftId
    _lastVersionNumber = state._restoreSourceVersion
      ? (state._restoreExpectedVersion || currentVersionNumber)
      : currentVersionNumber
    _lastUpdatedAt = state._restoreSourceVersion
      ? (state._restoreExpectedUpdatedAt || currentUpdatedAt)
      : currentUpdatedAt
    _lastRestoreSourceVersion = state._restoreSourceVersion || null

    try {
      const result = await api.writing.publish({
        novel_id: state.currentProjectId,
        chapter_index: chapterIndex,
        scene_id: currentScene?.id || null,
        draft_id: currentDraftId || null,
        expected_version: _lastVersionNumber || null,
        expected_updated_at: _lastUpdatedAt || null,
        restore_source_version: _lastRestoreSourceVersion,
        title: _lastTitle,
        content,
      })

      if (result.new_version === false) {
        toast("正文无实质变化，已沿用当前发布版本", "info")
        return result
      }

      if (result.task_id) {
        _publishTaskId = result.task_id
        _publishProgress = { phase: "running", step: 0, message: "正在存入 RAG 系统...", showModal: false }
      } else {
        _publishProgress = { phase: "done", step: 1, message: "发布完成" }
      }

      await _notifyPublished(result)
      if (result.task_id) {
        _startPublishPolling()
      } else {
        _scheduleProgressClear()
      }
      return result
    } catch (err) {
      toast(err.message || "发布失败", "error")
      onStatusChange("发布失败")
    }
  }

  async function retry() {
    if (!_lastChapterIndex) return
    _cancelProgressClear()
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
        draft_id: _lastDraftId,
        expected_version: _lastVersionNumber,
        expected_updated_at: _lastUpdatedAt,
        restore_source_version: _lastRestoreSourceVersion,
      })
      if (result.new_version === false) {
        _publishProgress = null
        toast("正文无实质变化，已沿用当前发布版本", "info")
        return result
      }
      if (result.task_id) {
        _publishTaskId = result.task_id
      } else {
        _publishProgress = { phase: "done", step: 1, message: "发布完成" }
      }
      await _notifyPublished(result)
      if (result.task_id) {
        _startPublishPolling()
      } else {
        _scheduleProgressClear()
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
      const taskId = _publishTaskId
      if (!taskId) { _stopPublishPolling(); return }
      try {
        const task = await api.tasks.get(taskId, state.currentProjectId)
        if (_publishTaskId !== taskId) return
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
          toast("发布后处理已完成", "success")
          updateBar()
          _stopPublishPolling()
          _scheduleProgressClear()
          return
        }

        if (task.status === "failed") {
          _publishProgress.phase = "failed"
          const errMsg = sanitizeTaskErrorMessage(
            task.error_message || task.result?.error_message || task.result?.error,
            "publish_chapter",
          ) || "发布任务失败。工作稿已保存，请稍后重试。"
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
        if (_publishTaskId !== taskId) return
        if (_publishProgress) {
          const errMsg = sanitizeTaskErrorMessage(
            err?.message || "发布状态查询失败。工作稿已保存，请稍后重试。",
            "publish_chapter",
          ) || "发布状态查询失败。工作稿已保存，请稍后重试。"
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
      <p class="writing-publish-error">工作稿已保存成功。您可以手动重试失败的步骤。</p>
      <div class="writing-publish-actions">
        <button class="btn" id="btn-dismiss-publish-modal">关闭</button>
        <button class="btn btn-primary" id="btn-retry-failed">手动重试</button>
      </div>
    `)
    const retryBtn = document.getElementById("btn-retry-failed")
    if (retryBtn) retryBtn.onclick = () => { modal.close(); retry() }
    const dismissBtn = document.getElementById("btn-dismiss-publish-modal")
    if (dismissBtn) dismissBtn.onclick = () => { modal.close(); dismissError() }
  }

  function dismissError() {
    _cancelProgressClear()
    _publishProgress = null
    _publishTaskId = null
    _errorModalVisible = false
    _stopPublishPolling()
    onStatusChange(null)
  }

  function dispose() {
    _cancelProgressClear()
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
