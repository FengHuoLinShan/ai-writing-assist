import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import RpSourceSetup from "../../../vue/views/interaction/RpSourceSetup.vue"
import {
  resetBridgeOverrides,
  setBridgeOverrides,
} from "../../../vue/bridge/index.js"
import {
  RP_SOURCE_FILE_ACCEPT,
  validateImportFile,
} from "../../../vue/composables/useImportUpload.js"

const revision = {
  id: "22222222-2222-4222-8222-222222222222",
  project_id: "11111111-1111-4111-8111-111111111111",
  title: "雾都之夜",
  version_number: 1,
  status: "ready",
  progress_message: "作品资料已完整整理，可以开始旅程",
  anchors: [{
    anchor_key: "a".repeat(64),
    chapter_index: 1,
    chapter_title: "第一章",
    label: "抵达雾都",
    excerpt: "火车刚刚进站",
    end_offset: 20,
  }, {
    anchor_key: "d".repeat(64),
    chapter_index: 2,
    chapter_title: "第二章",
    label: "进入钟楼",
    excerpt: "铜门关闭",
    end_offset: 40,
  }],
  objects: [{
    reference_key: "b".repeat(64),
    label: "林默",
    entity_type: "character",
    summary: "",
    aliases: [],
    first_chapter_index: 1,
    first_end_offset: 10,
  }, {
    reference_key: "e".repeat(64),
    label: "尚未登场的人",
    entity_type: "character",
    summary: "",
    aliases: [],
    first_chapter_index: 2,
    first_end_offset: 30,
  }],
  ambiguities: [],
}

let api

beforeEach(() => {
  sessionStorage.clear()
  api = {
    interactions: {
      listSources: vi.fn(async () => ({
        items: [revision],
        projects: [{
          project_id: revision.project_id,
          title: revision.title,
          latest_revision: revision,
        }],
      })),
      getSource: vi.fn(async () => revision),
      sourceFromProject: vi.fn(async () => revision),
      resolveSourceAmbiguity: vi.fn(),
      matchSourceAnchors: vi.fn(async () => ({ items: revision.anchors })),
      previewSourceImport: vi.fn(),
      importSource: vi.fn(),
    },
  }
  setBridgeOverrides({ api })
})

afterEach(() => resetBridgeOverrides())

describe("RP 作品资料设置", () => {
  it("只有版本、剧情点和玩家身份都确认后才产出 source setup", async () => {
    const wrapper = mount(RpSourceSetup)

    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("作品资料已完整整理")
    await wrapper.get(`input[value='${"a".repeat(64)}']`).setValue()
    await wrapper.findAll("select")[1].setValue("b".repeat(64))
    await flushPromises()

    const latest = wrapper.emitted("change").at(-1)[0]
    expect(latest.enabled).toBe(true)
    expect(latest.setup).toEqual({
      source_revision_id: revision.id,
      progress_anchor_key: "a".repeat(64),
      player_identity: {
        kind: "source_character",
        reference_key: "b".repeat(64),
      },
      pinned_reference_keys: [],
    })
  })

  it("整理中会说明可以离开，且不显示开始所需选项", async () => {
    api.interactions.getSource.mockResolvedValue({
      ...revision,
      status: "organizing",
      progress_message: "正在完整整理当前导入版本",
      anchors: [],
      objects: [],
    })
    const wrapper = mount(RpSourceSetup)
    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()

    expect(wrapper.get(".rp-source-status").text()).toContain("正在完整整理")
    expect(wrapper.find(".rp-source-ready").exists()).toBe(false)
    expect(wrapper.emitted("change").at(-1)[0].setup).toBeNull()
  })

  it("早期剧情点不会列出尚未登场的玩家角色", async () => {
    const wrapper = mount(RpSourceSetup)
    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()

    const characterSelect = wrapper.findAll("select")[1]
    expect(characterSelect.text()).not.toContain("尚未登场的人")
    await wrapper.get("select").setValue("2")
    await wrapper.get(`input[value='${"d".repeat(64)}']`).setValue()
    await flushPromises()
    expect(wrapper.findAll("select")[1].text()).toContain("尚未登场的人")
  })

  it("自然语言匹配只展示候选，仍需用户点选确认", async () => {
    const wrapper = mount(RpSourceSetup)
    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()
    await wrapper.get(".rp-source-anchor-match input").setValue("刚抵达雾都")
    await wrapper.get(".rp-source-anchor-match button").trigger("click")
    await flushPromises()

    expect(wrapper.emitted("change").at(-1)[0].setup).toBeNull()
    await wrapper.get(".rp-source-anchor-candidates button").trigger("click")
    await wrapper.findAll("select")[1].setValue("b".repeat(64))
    await flushPromises()
    expect(wrapper.emitted("change").at(-1)[0].setup.progress_anchor_key)
      .toBe("a".repeat(64))
  })

  it("RP 导入只接受已验收的四种格式", () => {
    expect(RP_SOURCE_FILE_ACCEPT).toBe(".txt,.epub,.html,.htm")
    expect(validateImportFile(
      new File(["x"], "novel.mobi"),
      RP_SOURCE_FILE_ACCEPT,
    )).toContain("不支持")
    expect(validateImportFile(
      new File(["x"], "novel.epub"),
      RP_SOURCE_FILE_ACCEPT,
    )).toBeNull()
  })

  it("直接整理前先确认会使用模型额度", async () => {
    api.interactions.listSources.mockResolvedValue({
      items: [],
      projects: [{
        project_id: revision.project_id,
        title: revision.title,
        latest_revision: null,
      }],
    })
    const wrapper = mount(RpSourceSetup)
    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()

    await wrapper.get("button.primary").trigger("click")
    await flushPromises()

    const dialog = document.getElementById("rp-source-organize-confirm")
    expect(dialog).toBeTruthy()
    expect(dialog.textContent).toContain("使用我的模型额度")
    expect(api.interactions.sourceFromProject).not.toHaveBeenCalled()

    const confirmButton = [...dialog.querySelectorAll("button")]
      .find((button) => button.textContent.includes("开始完整整理"))
    confirmButton.click()
    await flushPromises()
    expect(api.interactions.sourceFromProject).toHaveBeenCalledWith({
      project_id: revision.project_id,
      authorization_confirmed: true,
    })
  })

  it("对象类型以中文标签展示，不暴露内部枚举", async () => {
    const wrapper = mount(RpSourceSetup)
    await wrapper.get("input[value='source']").setValue()
    await flushPromises()
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()
    await wrapper.get(`input[value='${"a".repeat(64)}']`).setValue()
    await flushPromises()

    const pins = wrapper.get(".rp-source-pins")
    expect(pins.text()).toContain("林默 · 人物")
    expect(pins.text()).not.toContain("character")
  })

  it("整理进度轮询失败时按阶梯退避并保持单次提示", async () => {
    vi.useFakeTimers()
    try {
      const organizing = {
        ...revision,
        status: "organizing",
        progress_message: "正在完整整理当前导入版本",
        anchors: [],
        objects: [],
      }
      let calls = 0
      api.interactions.getSource.mockImplementation(async () => {
        calls += 1
        if (calls === 1 || calls === 5) return organizing
        throw new Error("")
      })
      const wrapper = mount(RpSourceSetup)
      await wrapper.get("input[value='source']").setValue()
      await vi.advanceTimersByTimeAsync(0)
      await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
      await vi.advanceTimersByTimeAsync(0)
      expect(calls).toBe(1)

      await vi.advanceTimersByTimeAsync(2500)
      expect(calls).toBe(2)
      expect(wrapper.get(".rp-source-error").text()).toContain("整理进度暂时无法刷新")

      await vi.advanceTimersByTimeAsync(2500)
      expect(calls).toBe(2)

      await vi.advanceTimersByTimeAsync(500)
      expect(calls).toBe(3)

      await vi.advanceTimersByTimeAsync(5999)
      expect(calls).toBe(3)
      expect(wrapper.findAll(".rp-source-error")).toHaveLength(1)

      await vi.advanceTimersByTimeAsync(1)
      expect(calls).toBe(4)

      await vi.advanceTimersByTimeAsync(12000)
      expect(calls).toBe(5)
      expect(wrapper.findAll(".rp-source-error")).toHaveLength(0)
    } finally {
      vi.useRealTimers()
    }
  })
})
