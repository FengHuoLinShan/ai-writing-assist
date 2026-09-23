import { afterEach, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneVisual from "../../../vue/views/scene/SceneVisual.vue"

afterEach(() => { resetBridgeOverrides(); vi.restoreAllMocks() })

it("只显示仍绑定原图片版本的场景图，并在读取失败时可重试", async () => {
  URL.createObjectURL = vi.fn(() => "blob:scene")
  URL.revokeObjectURL = vi.fn()
  const getEntity = vi.fn(async () => ({ image_version: "v1" }))
  const fetchEntityImage = vi.fn().mockRejectedValueOnce(new Error("storage unavailable")).mockResolvedValue(new Blob(["image"]))
  setBridgeOverrides({ api: { world: { getEntity, fetchEntityImage } } })
  const visual = { entity_id: "place", image_version: "v1", caption: "灰雾中的神殿" }
  const wrapper = mount(SceneVisual, { props: { projectId: "novel", visual, sceneTitle: "灰雾初现" } })
  await flushPromises()
  expect(wrapper.text()).toContain("暂时无法读取")
  await wrapper.get("button").trigger("click")
  await flushPromises()
  expect(wrapper.get("img").attributes("src")).toBe("blob:scene")
  expect(wrapper.get("img").attributes("alt")).toContain("灰雾初现")
  expect(fetchEntityImage).toHaveBeenCalledWith("place", "novel", "full", { expectedVersion: "v1" })

  await wrapper.setProps({ visual: { ...visual, image_version: "v2" } })
  await flushPromises()
  expect(wrapper.find("img").exists()).toBe(false)
  expect(wrapper.text()).toContain("已更新，请重新核对")
  expect(fetchEntityImage).toHaveBeenCalledTimes(2)
  wrapper.unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:scene")
})
