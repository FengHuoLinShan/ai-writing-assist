/**
 * Vue bridge 测试 — 全局回退与测试替身注入。
 */
import { describe, it, expect, afterEach, vi } from "vitest"
import {
  getApi,
  getAppState,
  getCloseModal,
  getConfirm,
  getConfirmAction,
  getEsc,
  getRouter,
  getShowModalHtml,
  getToast,
  resetBridgeOverrides,
  setBridgeOverrides,
  tryMigrateLocalAuthorPreferences,
  useStateKey,
} from "../../vue/bridge/index.js"
import { effectScope } from "vue"
import { beforeEach } from "vitest"

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("bridge 全局回退", () => {
  it("getApi/getRouter 回退到 window 全局（tests/setup.js mock）", () => {
    expect(getApi()).toBe(globalThis.api)
    expect(getRouter()).toBe(globalThis.router)
  })

  it("getToast 回退到全局 toast 函数", () => {
    getToast()("hello", "info")
    expect(globalThis.toast).toHaveBeenCalledWith("hello", "info")
  })

  it("getAppState 在未设置 window.appState 时返回 undefined（生产由 state.js 赋值）", () => {
    expect(getAppState()).toBeUndefined()
  })
})

describe("bridge 测试替身", () => {
  it("setBridgeOverrides 覆盖优先于全局，reset 后恢复", () => {
    const fakeApi = { marker: true }
    setBridgeOverrides({ api: fakeApi })
    expect(getApi()).toBe(fakeApi)
    resetBridgeOverrides()
    expect(getApi()).toBe(globalThis.api)
  })

  it("getConfirm 使用注入的确认函数", () => {
    const confirm = vi.fn(() => false)
    setBridgeOverrides({ confirm })
    expect(getConfirm()("确定吗？")).toBe(false)
    expect(confirm).toHaveBeenCalledWith("确定吗？")
  })

  it("tryMigrateLocalAuthorPreferences 调用注入实现且失败不抛出", async () => {
    const failing = vi.fn(async () => {
      throw new Error("boom")
    })
    setBridgeOverrides({ tryMigrateLocalAuthorPreferences: failing })
    await expect(tryMigrateLocalAuthorPreferences("p1")).resolves.toBeUndefined()
    expect(failing).toHaveBeenCalledWith("p1")
  })
})

describe("bridge 外壳 modal 与 esc", () => {
  it("modal 三件套回退到 window 全局", () => {
    getShowModalHtml()("标题", "<p>内容</p>", [])
    expect(globalThis.showModalHtml).toHaveBeenCalledWith("标题", "<p>内容</p>", [])
    getConfirmAction()("确定删除？", () => {}, "删除")
    expect(globalThis.confirmAction).toHaveBeenCalledWith("确定删除？", expect.any(Function), "删除")
    getCloseModal()()
    expect(globalThis.closeModal).toHaveBeenCalled()
  })

  it("modal 三件套可注入替身", () => {
    const showModalHtml = vi.fn()
    const confirmAction = vi.fn()
    const closeModal = vi.fn()
    setBridgeOverrides({ showModalHtml, confirmAction, closeModal })
    getShowModalHtml()("t", "h", [])
    getConfirmAction()("m", () => {})
    getCloseModal()()
    expect(showModalHtml).toHaveBeenCalledOnce()
    expect(confirmAction).toHaveBeenCalledOnce()
    expect(closeModal).toHaveBeenCalledOnce()
    expect(globalThis.showModalHtml).not.toHaveBeenCalled()
  })

  it("getEsc 回退到全局 esc 并可注入替身", () => {
    expect(getEsc()("<b>")).toBe("&lt;b&gt;")
    setBridgeOverrides({ esc: () => "SAFE" })
    expect(getEsc()("<b>")).toBe("SAFE")
  })
})

describe("useStateKey", () => {
  it("返回初始值并随 onStateChange 同步，作用域销毁时退订", () => {
    const listeners = []
    const state = { currentProjectId: "p0" }
    const onStateChange = (listener) => {
      listeners.push(listener)
      return () => {
        const index = listeners.indexOf(listener)
        if (index >= 0) listeners.splice(index, 1)
      }
    }
    setBridgeOverrides({ state, onStateChange })

    const scope = effectScope()
    let value
    scope.run(() => {
      value = useStateKey("currentProjectId")
    })
    expect(value.value).toBe("p0")
    expect(listeners).toHaveLength(1)

    listeners.forEach((listener) => listener("currentProjectId", "p1", "p0"))
    expect(value.value).toBe("p1")

    scope.stop()
    expect(listeners).toHaveLength(0)
  })
})
