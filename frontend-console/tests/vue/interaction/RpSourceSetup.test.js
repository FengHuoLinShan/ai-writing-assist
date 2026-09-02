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

function deferred() {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

function revisionFor({ id, projectId, title, status = "ready" }) {
  return {
    ...revision,
    id,
    project_id: projectId,
    title,
    status,
    progress_message: status === "organizing"
      ? "正在完整整理当前导入版本"
      : revision.progress_message,
    anchors: status === "organizing" ? [] : revision.anchors,
    objects: status === "organizing" ? [] : revision.objects,
  }
}

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

async function openSourceSelection(wrapper) {
  await wrapper.get("input[value='source']").setValue()
  await wrapper.get(".rp-source-next").trigger("click")
  await flushPromises()
}

async function chooseAvailableProject(wrapper) {
  await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
  await flushPromises()
}

async function continueToIdentity(wrapper) {
  await wrapper.get(".rp-source-next").trigger("click")
  await flushPromises()
}

describe("RP 作品资料设置", () => {
  it("从资料方式开始，只展开当前一步并支持键盘返回摘要", async () => {
    const wrapper = mount(RpSourceSetup, { attachTo: document.body })

    expect(wrapper.get("[aria-current='step']").text()).toContain("选择资料来源")
    expect(wrapper.find(".rp-source-projects").exists()).toBe(false)
    expect(wrapper.text()).toContain("使用你在账户中连接的 AI 服务")
    expect(wrapper.text()).toContain("请求经本站后端代发")
    expect(wrapper.text()).toContain("Key 不会进入浏览器或作品")

    await openSourceSelection(wrapper)
    expect(wrapper.get("[aria-current='step']").text()).toContain("选择作品或文件")
    expect(document.activeElement).toBe(wrapper.get(".rp-source-step-panel > h3").element)
    const previous = wrapper.get(".rp-source-steps li.complete button")
    expect(previous.text()).toContain("使用已有作品资料")
    previous.element.focus()
    await previous.trigger("click")
    expect(document.activeElement).toBe(wrapper.get(".rp-source-step-panel > h3").element)
    expect(wrapper.find(".rp-source-projects").exists()).toBe(false)
  })

  it("直接描述时跳到角色与开场，并在刷新后恢复当前步骤", async () => {
    const wrapper = mount(RpSourceSetup)
    await wrapper.get(".rp-source-next").trigger("click")
    await flushPromises()

    expect(wrapper.get("[aria-current='step']").text()).toContain("角色与开场")
    expect(wrapper.findAll(".rp-source-steps > li")).toHaveLength(2)
    expect(wrapper.text()).not.toContain("选择作品或文件")
    expect(wrapper.text()).not.toContain("准备作品资料")
    expect(wrapper.emitted("change").at(-1)[0]).toEqual(expect.objectContaining({
      enabled: false,
      openingReady: true,
      setup: null,
      step: 4,
    }))
    wrapper.unmount()

    const restored = mount(RpSourceSetup)
    expect(restored.get("[aria-current='step']").text()).toContain("角色与开场")
    expect(restored.emitted("change").at(-1)[0].openingReady).toBe(true)
  })

  it("只有版本、剧情点和玩家身份都确认后才产出 source setup", async () => {
    const wrapper = mount(RpSourceSetup)

    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)

    expect(wrapper.text()).toContain("作品资料已完整整理")
    await wrapper.get(`input[value='${"a".repeat(64)}']`).setValue()
    expect(wrapper.text()).not.toContain("玩家身份")
    expect(wrapper.emitted("change").at(-1)[0].openingReady).toBe(false)
    await continueToIdentity(wrapper)
    await wrapper.get("select").setValue("b".repeat(64))
    await flushPromises()

    const latest = wrapper.emitted("change").at(-1)[0]
    expect(latest.enabled).toBe(true)
    expect(latest.openingReady).toBe(true)
    expect(latest.setup).toEqual({
      source_revision_id: revision.id,
      progress_anchor_key: "a".repeat(64),
      player_identity: {
        kind: "source_character",
        reference_key: "b".repeat(64),
      },
      pinned_reference_keys: [],
    })
    expect(sessionStorage.getItem("rpSourceSetupDraft:v1")).toContain('"step":4')
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
    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)

    expect(wrapper.get(".rp-source-status").text()).toContain("正在完整整理")
    expect(wrapper.find(".rp-source-ready").exists()).toBe(false)
    expect(wrapper.emitted("change").at(-1)[0].setup).toBeNull()
  })

  it("早期剧情点不会列出尚未登场的玩家角色", async () => {
    const wrapper = mount(RpSourceSetup)
    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)

    await wrapper.get(`input[value='${"a".repeat(64)}']`).setValue()
    await continueToIdentity(wrapper)
    let characterSelect = wrapper.get("select")
    expect(characterSelect.text()).not.toContain("尚未登场的人")
    await wrapper.get(".rp-source-steps li.complete:nth-child(3) button").trigger("click")
    await wrapper.get("select").setValue("2")
    await wrapper.get(`input[value='${"d".repeat(64)}']`).setValue()
    await continueToIdentity(wrapper)
    await flushPromises()
    characterSelect = wrapper.get("select")
    expect(characterSelect.text()).toContain("尚未登场的人")
  })

  it("自然语言匹配只展示候选，仍需用户点选确认", async () => {
    const wrapper = mount(RpSourceSetup)
    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)
    await wrapper.get(".rp-source-anchor-match input").setValue("刚抵达雾都")
    await wrapper.get(".rp-source-anchor-match button").trigger("click")
    await flushPromises()

    expect(wrapper.emitted("change").at(-1)[0].setup).toBeNull()
    await wrapper.get(".rp-source-anchor-candidates button").trigger("click")
    expect(wrapper.emitted("change").at(-1)[0].setup).toBeNull()
    await continueToIdentity(wrapper)
    await wrapper.get("select").setValue("b".repeat(64))
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

  it("直接整理前确认会使用账户连接的 AI 服务", async () => {
    api.interactions.listSources.mockResolvedValue({
      items: [],
      projects: [{
        project_id: revision.project_id,
        title: revision.title,
        latest_revision: null,
      }],
    })
    const wrapper = mount(RpSourceSetup)
    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)

    await wrapper.get("button.primary").trigger("click")
    await flushPromises()

    const dialog = document.getElementById("rp-source-organize-confirm")
    expect(dialog).toBeTruthy()
    expect(dialog.textContent).toContain("使用你在账户中连接的 AI 服务")
    expect(dialog.textContent).toContain("Key 不会进入浏览器或作品")
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
    await openSourceSelection(wrapper)
    await chooseAvailableProject(wrapper)
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
      await wrapper.get(".rp-source-next").trigger("click")
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

  it("快速切换作品时丢弃上一部作品的晚到版本", async () => {
    const projectA = revisionFor({
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      projectId: "11111111-1111-4111-8111-111111111111",
      title: "作品 A",
    })
    const projectB = revisionFor({
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      projectId: "22222222-2222-4222-8222-222222222222",
      title: "作品 B",
    })
    const requestA = deferred()
    const requestB = deferred()
    api.interactions.listSources.mockResolvedValue({
      items: [projectA, projectB],
      projects: [projectA, projectB].map((item) => ({
        project_id: item.project_id,
        title: item.title,
        latest_revision: item,
      })),
    })
    api.interactions.getSource.mockImplementation((id) => (
      id === projectA.id ? requestA.promise : requestB.promise
    ))
    const wrapper = mount(RpSourceSetup)
    await openSourceSelection(wrapper)
    const projectButtons = wrapper.findAll(".rp-source-projects > button")
      .filter((button) => button.text().startsWith("作品"))

    await projectButtons[0].trigger("click")
    await projectButtons[1].trigger("click")
    requestB.resolve(projectB)
    await flushPromises()
    expect(wrapper.get(".rp-source-revision").text()).toContain("作品 B")

    requestA.resolve(projectA)
    await flushPromises()
    expect(wrapper.get(".rp-source-revision").text()).toContain("作品 B")
    expect(JSON.parse(sessionStorage.getItem("rpSourceSetupDraft:v1")).revisionId)
      .toBe(projectB.id)
  })

  it("换作品后丢弃旧轮询的晚到版本", async () => {
    vi.useFakeTimers()
    try {
      const organizing = revisionFor({
        id: revision.id,
        projectId: revision.project_id,
        title: revision.title,
        status: "organizing",
      })
      const latePoll = deferred()
      api.interactions.getSource
        .mockResolvedValueOnce(organizing)
        .mockImplementationOnce(() => latePoll.promise)
      const wrapper = mount(RpSourceSetup)
      await wrapper.get("input[value='source']").setValue()
      await wrapper.get(".rp-source-next").trigger("click")
      await vi.advanceTimersByTimeAsync(0)
      await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
      await vi.advanceTimersByTimeAsync(0)
      await vi.advanceTimersByTimeAsync(2500)

      const switchButton = wrapper.findAll("button")
        .find((button) => button.text() === "换一部作品")
      await switchButton.trigger("click")
      latePoll.resolve(revision)
      await flushPromises()

      expect(wrapper.get("[aria-current='step']").text()).toContain("选择作品或文件")
      expect(wrapper.findAll("button").some((button) => button.text().startsWith("继续使用")))
        .toBe(false)
      expect(JSON.parse(sessionStorage.getItem("rpSourceSetupDraft:v1")).revisionId)
        .toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it("切换作品后不接收旧歧义确认与剧情匹配结果", async () => {
    const projectB = revisionFor({
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      projectId: "22222222-2222-4222-8222-222222222222",
      title: "作品 B",
    })
    const ambiguityRequest = deferred()
    const matchRequest = deferred()
    const ambiguous = {
      ...revision,
      status: "needs_confirmation",
      progress_message: "还需确认 1 项关键指代",
      ambiguities: [{
        ambiguity_key: "lin-mo",
        label: "林默",
        reason: "同名人物",
        choices: [{ choice_key: "b".repeat(64), label: "林默", entity_type: "character" }],
      }],
    }
    api.interactions.listSources.mockResolvedValue({
      items: [ambiguous, projectB],
      projects: [ambiguous, projectB].map((item) => ({
        project_id: item.project_id,
        title: item.title,
        latest_revision: item,
      })),
    })
    api.interactions.getSource.mockImplementation(async (id) => (
      id === projectB.id ? projectB : ambiguous
    ))
    api.interactions.resolveSourceAmbiguity.mockImplementation(() => ambiguityRequest.promise)
    api.interactions.matchSourceAnchors.mockImplementation(() => matchRequest.promise)
    const wrapper = mount(RpSourceSetup)
    await openSourceSelection(wrapper)
    await wrapper.findAll(".rp-source-projects > button")[0].trigger("click")
    await flushPromises()

    await wrapper.get(".rp-source-ambiguities button").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "换一部作品").trigger("click")
    await wrapper.findAll(".rp-source-projects > button")
      .find((button) => button.text().startsWith("作品 B"))
      .trigger("click")
    await flushPromises()
    ambiguityRequest.resolve(revision)
    await flushPromises()
    expect(wrapper.get(".rp-source-revision").text()).toContain("作品 B")

    await wrapper.get(".rp-source-anchor-match input").setValue("抵达雾都")
    await wrapper.get(".rp-source-anchor-match button").trigger("click")
    await wrapper.findAll("button").find((button) => button.text() === "换一部作品").trigger("click")
    matchRequest.resolve({ items: revision.anchors })
    await flushPromises()
    expect(wrapper.find(".rp-source-anchor-candidates").exists()).toBe(false)
    expect(wrapper.get("[aria-current='step']").text()).toContain("选择作品或文件")
  })
})
