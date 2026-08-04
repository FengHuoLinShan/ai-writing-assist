/**
 * 回收站 — 外壳全局 modal 内的子界面（分页/选择/恢复/永久删除），
 * 从 views/projectView.js showRecycleBin 移植。内容字符串 esc() 拼装（既有豁免模式）。
 */
import { runBulkAction, bulkResultMessage } from "../../../../shared/bulkSelection.js"
import {
  getApi,
  getConfirmAction,
  getEsc,
  getRouter,
  getShowModalHtml,
  getToast,
} from "../../../bridge/index.js"
import { projectSession } from "../projectSession.js"

const PAGE_SIZE = 20

export async function showRecycleBin(skip = projectSession.recycleBinSkip) {
  const toast = getToast()
  const esc = getEsc()
  const api = getApi()
  try {
    const data = await api.projects.listDeleted(skip, PAGE_SIZE)
    const items = data.items || data || []
    const total = Number(data.total ?? items.length) || 0
    if (total > 0 && skip >= total) {
      const lastPageSkip = Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE
      return showRecycleBin(lastPageSkip)
    }
    projectSession.recycleBinSkip = skip
    if (total === 0) {
      projectSession.recycleBinSkip = 0
      getShowModalHtml()("回收站", '<div class="recycle-bin"><p>回收站为空。</p></div>', [], { size: "large" })
      return
    }
    const currentPage = Math.floor(skip / PAGE_SIZE) + 1
    const totalPages = Math.ceil(total / PAGE_SIZE)
    const previousDisabled = skip <= 0 ? "disabled" : ""
    const nextDisabled = skip + PAGE_SIZE >= total ? "disabled" : ""
    let listHtml = `
      <div class="recycle-bin">
        <div class="bulk-toolbar recycle-bin__toolbar">
          <div class="bulk-toolbar__status"><span>回收站项目 · 共 ${esc(total)} 个</span></div>
          <div class="bulk-toolbar__actions">
            <button class="btn btn-sm" id="recycle-select-all">全选当前页</button>
            <button class="btn btn-sm btn-primary" id="recycle-bulk-restore" disabled>批量恢复</button>
            <button class="btn btn-sm btn-danger" id="recycle-bulk-delete" disabled>批量永久删除</button>
          </div>
        </div>
        <div class="recycle-bin__list">
    `
    for (const p of items) {
      const name = p.title || p.name || "未命名"
      const deletedDate = p.deleted_at
        ? new Date(p.deleted_at).toLocaleDateString("zh-CN")
        : ""
      listHtml += `
        <div class="recycle-bin__item">
          <label class="selection-checkbox" title="选择 ${esc(name)}">
            <input type="checkbox" class="recycle-project-checkbox" data-id="${esc(p.id)}" />
            <span class="sr-only">选择 ${esc(name)}</span>
          </label>
          <div class="recycle-bin__item-info">
            <div class="recycle-bin__item-name">${esc(name)}</div>
            <div class="recycle-bin__item-date">删除于 ${deletedDate}</div>
          </div>
          <div class="recycle-bin__item-actions">
            <button class="btn btn-sm btn-primary restore-project-btn" data-id="${esc(p.id)}">恢复</button>
            <button class="btn btn-sm btn-danger perm-delete-project-btn" data-id="${esc(p.id)}">永久删除</button>
          </div>
        </div>
      `
    }
    listHtml += `
        </div>
        <div class="recycle-bin__pagination" aria-label="回收站分页">
          <button class="btn btn-sm" id="recycle-prev-page" ${previousDisabled}>上一页</button>
          <span>第 ${currentPage} / ${totalPages} 页，共 ${esc(total)} 条</span>
          <button class="btn btn-sm" id="recycle-next-page" ${nextDisabled}>下一页</button>
        </div>
      </div>
    `
    getShowModalHtml()("回收站", listHtml, [], { size: "large" })

    bindRecycleBinEvents(items, skip)
  } catch (err) {
    toast(`加载回收站失败：${err.message}`, "error")
  }
}

function bindRecycleBinEvents(items, skip) {
  const toast = getToast()
  const api = getApi()
  const selectedRecycleProjects = () => {
    const ids = new Set(Array.from(document.querySelectorAll(".recycle-project-checkbox:checked")).map((input) => input.dataset.id))
    return items.filter((item) => ids.has(item.id))
  }
  const bulkRestoreButton = document.getElementById("recycle-bulk-restore")
  const bulkDeleteButton = document.getElementById("recycle-bulk-delete")
  const syncBulkActionAvailability = () => {
    const disabled = document.querySelectorAll(".recycle-project-checkbox:checked").length === 0
    for (const button of [bulkRestoreButton, bulkDeleteButton]) {
      if (button) button.disabled = disabled
    }
  }
  document.querySelectorAll(".recycle-project-checkbox").forEach((input) => {
    input.addEventListener("change", syncBulkActionAvailability)
  })
  const selectAllButton = document.getElementById("recycle-select-all")
  if (selectAllButton) {
    selectAllButton.onclick = () => {
      document.querySelectorAll(".recycle-project-checkbox").forEach((input) => {
        input.checked = true
      })
      syncBulkActionAvailability()
    }
  }
  if (bulkRestoreButton) {
    bulkRestoreButton.onclick = async () => {
      const selected = selectedRecycleProjects()
      if (!selected.length) {
        toast("请先选择项目", "warning")
        return
      }
      try {
        const result = await runBulkAction(selected, async (project) => api.projects.restore(project.id))
        if (result.failed.length && result.success.length === 0) {
          toast(`批量恢复失败：${result.failed[0]?.error?.message || "未知错误"}`, "error")
        } else {
          toast(bulkResultMessage(result, "批量恢复项目", (item) => item.title || item.name || item.id), result.failed.length ? "warning" : "success")
        }
        await getRouter().refresh()
        showRecycleBin(projectSession.recycleBinSkip)
      } catch (err) {
        toast(`批量恢复失败：${err.message || "未知错误"}`, "error")
      }
    }
  }
  if (bulkDeleteButton) {
    bulkDeleteButton.onclick = () => {
      const selected = selectedRecycleProjects()
      if (!selected.length) {
        toast("请先选择项目", "warning")
        return
      }
      getConfirmAction()(`确定永久删除选中的 ${selected.length} 个项目？此操作不可恢复。`, async () => {
        try {
          const result = await api.projects.permanentDeleteMany(
            selected.map((project) => project.id),
          )
          toast(`已永久删除 ${result.deleted_count} 个项目`, "success")
          await showRecycleBin(projectSession.recycleBinSkip)
          return true
        } catch (err) {
          toast(`批量永久删除失败：${err.message || "未知错误"}`, "error")
          return false
        }
      }, "永久删除")
    }
  }
  document.querySelectorAll(".restore-project-btn").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api.projects.restore(btn.dataset.id)
        toast("项目已恢复", "success")
        await getRouter().refresh()
        showRecycleBin(projectSession.recycleBinSkip)
      } catch (err) {
        toast(`恢复失败：${err.message}`, "error")
      }
    }
  })
  document.querySelectorAll(".perm-delete-project-btn").forEach((btn) => {
    btn.onclick = () => {
      const pid = btn.dataset.id
      getConfirmAction()(
        "确定永久删除此项目？此操作不可恢复，所有关联数据将被级联删除。",
        async () => {
          try {
            await api.projects.permanentDelete(pid)
            toast("项目已永久删除", "success")
            await showRecycleBin(projectSession.recycleBinSkip)
            return true
          } catch (err) {
            toast(`永久删除失败：${err.message || "未知错误"}`, "error")
            return false
          }
        },
        "永久删除",
      )
    }
  })
  const previousButton = document.getElementById("recycle-prev-page")
  if (previousButton) {
    previousButton.onclick = () => showRecycleBin(Math.max(0, skip - PAGE_SIZE))
  }
  const nextButton = document.getElementById("recycle-next-page")
  if (nextButton) {
    nextButton.onclick = () => showRecycleBin(skip + PAGE_SIZE)
  }
  syncBulkActionAvailability()
}
