/**
 * 导入文件上传 composable — 对应 vanilla projectView._uploadFile。
 * api.imports.uploadFile 的 XHR onprogress 回调 → 响应式 refs；
 * 所有回调 guard 组件已卸载（island 重建竞态）。
 */
import { getCurrentScope, onScopeDispose, ref } from "vue"
import { getApi, getRouter, getToast } from "../bridge/index.js"

export const MAX_IMPORT_FILE_BYTES = 50 * 1024 * 1024

export function useImportUpload() {
  const uploading = ref(false)
  const percent = ref(0)
  /** @type {import("vue").Ref<{stage:string, percent:number, message:string}|null>} */
  const progress = ref(null)

  let active = true
  if (getCurrentScope()) {
    onScopeDispose(() => {
      active = false
    })
  }

  function setProgress(stage, value, message) {
    if (!active) return
    progress.value = {
      stage,
      percent: Math.max(0, Math.min(100, Math.round(value || 0))),
      message,
    }
  }

  /**
   * 上传并导入到指定项目。
   * @param {File} file
   * @param {string} projectId
   * @param {{onSettled?: (err: Error|null, result: object|null) => void}} hooks
   *   onSettled 在成功（导航前）与失败时各调用一次，供调用方刷新导入历史/清空文件输入
   * @returns {Promise<boolean>} 是否上传成功
   */
  async function upload(file, projectId, { onSettled } = {}) {
    const toast = getToast()
    if (!file) {
      toast("请先选择文件", "warning")
      return false
    }
    if (!projectId) {
      toast("请先点击项目行选择项目", "warning")
      return false
    }
    if (file.size > MAX_IMPORT_FILE_BYTES) {
      toast("文件大小超过限制（最大 50MB）", "error")
      return false
    }

    uploading.value = true
    progress.value = null
    percent.value = 0
    setProgress("上传文件", 0, "正在上传文件...")

    try {
      const result = await getApi().imports.uploadFile(file, projectId, (value) => {
        if (!active) return
        percent.value = value
        setProgress("上传文件", value, `正在上传文件 ${value}%`)
        if (value >= 100) {
          setProgress("解析章节", 100, "文件已上传，正在解析章节...")
        }
      })
      setProgress("解析章节", 100, "章节解析完成")

      const nextStep = result.imported_chapters > 0
        ? "，可在写作台按需启动场景自动提取"
        : ""
      toast(`导入完成：共解析 ${result.total_chapters || 0} 章，已保存 ${result.imported_chapters || 0} 章为章节工作稿${nextStep}`, "success")
      getApi().clearCache()
      setProgress("刷新项目", 100, "正在刷新项目...")
      onSettled?.(null, result)
      await getRouter().navigate("writing")
      await getRouter().refresh()
      return true
    } catch (err) {
      toast(err.message || "导入失败", "error")
      getApi().clearCache()
      onSettled?.(err, null)
      return false
    } finally {
      if (active) {
        uploading.value = false
        progress.value = null
      }
    }
  }

  return { uploading, percent, progress, upload }
}
