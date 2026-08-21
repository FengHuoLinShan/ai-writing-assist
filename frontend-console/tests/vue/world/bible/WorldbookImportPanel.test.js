import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

import WorldbookImportPanel from "../../../../vue/views/world/bible/WorldbookImportPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

let api
let navigate
let toast

beforeEach(() => {
  api = {
    world: {
      previewWorldbookImport: vi.fn(),
      getWorldbookImport: vi.fn(),
      applyWorldbookImport: vi.fn(),
    },
  }
  navigate = vi.fn()
  toast = vi.fn()
  setBridgeOverrides({
    api,
    router: { navigate },
    toast,
    confirm: vi.fn(() => true),
  })
})

afterEach(() => resetBridgeOverrides())

describe("WorldbookImportPanel", () => {
  it("keeps directory content local until preview and applies only after confirmation", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-1",
      source_format: "obsidian",
      preview_hash: "a".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [{ source_key: "b".repeat(64), title: "潮汐城", path: "Vault/潮汐城.md", action: "create", reason: "新来源" }],
      ignored_paths: ["Vault/.obsidian/app.json"],
    })
    api.world.applyWorldbookImport.mockResolvedValue({
      draft_ids: ["draft-1"],
      conflict_ids: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    const file = new File(["正文"], "潮汐城.md", { type: "text/markdown" })
    Object.defineProperty(file, "webkitRelativePath", { value: "Vault/潮汐城.md" })
    Object.defineProperty(file, "text", { value: vi.fn(async () => "正文") })
    const image = new File(["binary"], "map.png", { type: "image/png" })
    Object.defineProperty(image, "webkitRelativePath", { value: "Vault/map.png" })
    Object.defineProperty(image, "text", { value: vi.fn(async () => "must not read") })
    const input = wrapper.get("input[type='file']")
    Object.defineProperty(input.element, "files", { value: [file, image], configurable: true })
    await input.trigger("change")

    expect(api.world.previewWorldbookImport).not.toHaveBeenCalled()
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(api.world.previewWorldbookImport).toHaveBeenCalledWith("p1", [
      { path: "Vault/潮汐城.md", content: "正文" },
      { path: "Vault/map.png", content: "" },
    ])
    expect(image.text).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("新建 1")
    expect(wrapper.text()).toContain("Obsidian Vault")
    expect(wrapper.text()).toContain("Vault/.obsidian/app.json")

    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(api.world.applyWorldbookImport).toHaveBeenCalledWith("import-1", "p1", "a".repeat(64))
    expect(navigate).toHaveBeenCalledWith("world", "bible", true, new URLSearchParams("draft_id=draft-1"))
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("导入完成"), "success")
  })

  it("restores a compact pending preview from a Today deep link", async () => {
    api.world.getWorldbookImport.mockResolvedValue({
      suggestion_id: "import-2",
      source_format: "generic",
      preview_hash: "c".repeat(64),
      counts: { create: 0, update: 0, preserve: 0, conflict: 1, missing: 0 },
      items: [],
      ignored_paths: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true, suggestionId: "import-2" },
    })
    await flushPromises()
    expect(api.world.getWorldbookImport).toHaveBeenCalledWith("import-2", "p1")
    expect(wrapper.text()).toContain("冲突 1")
  })
})
