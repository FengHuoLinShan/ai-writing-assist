/**
 * useImportUpload 测试 — 对应 vanilla _uploadFile 的行为契约。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { effectScope } from "vue"
import { MAX_IMPORT_FILE_BYTES, useImportUpload } from "../../../vue/composables/useImportUpload.js"
import { resetBridgeOverrides } from "../../../vue/bridge/index.js"

function makeFile(bytes = 1024, name = "novel.txt") {
  return new File(["x".repeat(Math.min(bytes, 4096))], name, { type: "text/plain" })
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("前置校验", () => {
  it("无文件/无项目/格式错误/超限分别给出对应提示", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())

    expect(await u.upload(null, "p1")).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("请先选择文件", "warning")

    expect(await u.upload(makeFile(), null)).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("请先点击项目行选择项目", "warning")

    expect(await u.upload(makeFile(1024, "novel.pdf"), "p1")).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith(
      "不支持的文件格式，请选择 txt、epub、html、htm、mobi 或 azw3 文件",
      "error",
    )

    const big = makeFile()
    Object.defineProperty(big, "size", { value: MAX_IMPORT_FILE_BYTES + 1 })
    expect(await u.upload(big, "p1")).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("文件大小超过限制（最大 50MB）", "error")
    scope.stop()
  })
})

describe("上传流程", () => {
  it("进度回调驱动 refs，成功后 toast 并跳转写作台", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())
    const progressSeen = []
    globalThis.api.imports.uploadFile = vi.fn(async (_file, _pid, onProgress) => {
      onProgress(40)
      progressSeen.push(u.progress.value?.message)
      onProgress(100)
      progressSeen.push(u.progress.value?.stage)
      return { total_chapters: 12, imported_chapters: 12 }
    })
    const settled = vi.fn()

    const ok = await u.upload(makeFile(), "p1", { onSettled: settled })

    expect(ok).toBe(true)
    expect(progressSeen).toEqual(["正在上传文件 40%", "解析章节"])
    expect(globalThis.toast).toHaveBeenCalledWith(
      "导入完成：共解析 12 章，已保存 12 章为章节工作稿，可在写作台按需启动场景自动提取",
      "success",
    )
    expect(globalThis.api.clearCache).toHaveBeenCalled()
    expect(settled).toHaveBeenCalledWith(null, { total_chapters: 12, imported_chapters: 12 })
    expect(globalThis.router.navigate).toHaveBeenCalledWith("writing")
    expect(globalThis.router.refresh).toHaveBeenCalled()
    expect(u.uploading.value).toBe(false)
    expect(u.progress.value).toBeNull()
    scope.stop()
  })

  it("imported_chapters 为 0 时不带下一步提示", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())
    globalThis.api.imports.uploadFile = vi.fn(async () => ({ total_chapters: 3, imported_chapters: 0 }))
    await u.upload(makeFile(), "p1")
    expect(globalThis.toast).toHaveBeenCalledWith(
      "导入完成：共解析 3 章，已保存 0 章为章节工作稿",
      "success",
    )
    scope.stop()
  })

  it("失败时 toast 错误并复位状态，不跳转", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())
    globalThis.api.imports.uploadFile = vi.fn(async () => {
      throw new Error("解析失败")
    })
    const settled = vi.fn()

    const ok = await u.upload(makeFile(), "p1", { onSettled: settled })

    expect(ok).toBe(false)
    expect(globalThis.toast).toHaveBeenCalledWith("解析失败", "error")
    expect(settled).toHaveBeenCalledWith(expect.any(Error), null)
    expect(globalThis.router.navigate).not.toHaveBeenCalled()
    expect(u.uploading.value).toBe(false)
    scope.stop()
  })

  it("scope 销毁后进度回调不再写入 refs", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())
    let capturedOnProgress = null
    globalThis.api.imports.uploadFile = vi.fn((_file, _pid, onProgress) => {
      capturedOnProgress = onProgress
      return new Promise(() => {}) // 永不完成
    })
    void u.upload(makeFile(), "p1")
    await vi.waitFor(() => expect(capturedOnProgress).not.toBeNull())

    scope.stop()
    const before = u.progress.value
    capturedOnProgress(80)
    expect(u.progress.value).toBe(before)
  })

  it("scope 销毁时取消底层 XHR 上传", async () => {
    const scope = effectScope()
    const u = scope.run(() => useImportUpload())
    let signal = null
    globalThis.api.imports.uploadFile = vi.fn((_file, _pid, _onProgress, options) => {
      signal = options.signal
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(new DOMException("已取消", "AbortError")), { once: true })
      })
    })
    const pending = u.upload(makeFile(), "p1")
    await vi.waitFor(() => expect(signal).toBeInstanceOf(AbortSignal))
    scope.stop()
    await expect(pending).resolves.toBe(false)
    expect(signal.aborted).toBe(true)
    expect(globalThis.toast).not.toHaveBeenCalledWith("已取消", "error")
  })
})
