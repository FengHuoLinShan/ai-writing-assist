import { enableAutoUnmount, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"

import SmartDedupAction from "../../../vue/components/SmartDedupAction.vue"
import {
  notifySmartDedupChanged,
  resetBridgeOverrides,
  setBridgeOverrides,
} from "../../../vue/bridge/index.js"

enableAutoUnmount(afterEach)

describe("SmartDedupAction", () => {
  let progress
  let manager

  beforeEach(() => {
    progress = null
    manager = {
      getState: vi.fn(() => ({ progress })),
      handleAction: vi.fn(),
    }
    setBridgeOverrides({
      smartDedup: manager,
      state: { currentProjectId: "project-1" },
    })
  })

  afterEach(() => resetBridgeOverrides())

  it("renders state and delegates the action through the bridge", async () => {
    const wrapper = mount(SmartDedupAction)

    await wrapper.get("button").trigger("click")
    expect(manager.handleAction).toHaveBeenCalledWith("start-smart-dedup")

    progress = { terminal: false, done: false }
    notifySmartDedupChanged()
    await nextTick()
    expect(wrapper.get("button").text()).toBe("查看智能去重")

  })

  it("stays hidden without a current project", () => {
    setBridgeOverrides({ state: { currentProjectId: null } })
    expect(mount(SmartDedupAction).find("button").exists()).toBe(false)
  })
})
