/**
 * Vue bridge 测试 — 全局回退与测试替身注入。
 */
import { describe, it, expect, afterEach, vi } from "vitest"
import {
  getApi,
  getAppState,
  getConfirm,
  getRouter,
  getToast,
  resetBridgeOverrides,
  setBridgeOverrides,
  tryMigrateLocalAuthorPreferences,
  useStateKey,
} from "../../vue/bridge/index.js"
import { effectScope } from "vue"

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
