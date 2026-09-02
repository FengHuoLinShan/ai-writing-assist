import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"

const confirmAiReference = vi.hoisted(() => vi.fn())
vi.mock("../../../shared/aiReferenceModal.js", () => ({ confirmAiReference }))

import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import MapWorkspaceView from "../../../vue/views/map/MapWorkspaceView.vue"

enableAutoUnmount(afterEach)

const page = (overrides = {}) => ({
  id: "candidate-1",
  node_id: "node-1",
  run_id: "run-1",
  title: "沉钟港",
  generation_status: "review_ready",
  review_status: "candidate",
  updated_at: "2026-08-12T00:00:00Z",
  created_at: "2026-08-12T00:00:00Z",
  evidence: {
    supported: ["世界设定明确为港口"],
    visual_fill: ["码头间距"],
    conflicts: ["城门方位记载不一致"],
  },
  source_manifest: [],
  annotations: [],
  image_url: `/private/${overrides.id || "candidate-1"}`,
  ...overrides,
})

const tree = (pages, mode) => ({
  mode,
  total_pages: pages.length,
  nodes: [{
    id: "node-1",
    title: "沉钟港",
    level: "city",
    pages,
    children: [],
  }],
})

describe("AI 地图册工作台", () => {
  let api
  let toast
  let confirm
  let router

  beforeEach(() => {
    confirmAiReference.mockReset()
    confirmAiReference.mockResolvedValue({ id: "confirm-default" })
    api = globalThis.api
    toast = vi.fn()
    confirm = vi.fn(() => true)
    router = { navigate: vi.fn() }
    for (const name of [
      "getMapAtlas", "getMapAtlasPageHistory", "createMapAtlasRun", "getMapAtlasRun",
      "getLatestMapAtlasRun", "getMapAtlasRunResults", "stopMapAtlasRun",
      "resumeMapAtlasRun", "reviewMapAtlasPage", "retryMapAtlasPage",
      "regenerateMapAtlasPage", "editMapAtlasPage", "updateMapAtlasAnnotation",
      "getMapAtlasPagePrompt", "updateMapAtlasPagePrompt", "confirmMapAtlasPrompts",
      "uploadMapAtlasPage", "updateMapAtlasNode",
      "fetchMapAtlasImage",
    ]) api.world[name].mockReset()
    setBridgeOverrides({ api, toast, confirm, router })
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:atlas")
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {})
    api.world.getMapAtlas.mockResolvedValue(tree([], "atlas"))
    api.world.getLatestMapAtlasRun.mockResolvedValue(null)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([], "review"))
    api.world.getMapAtlasPageHistory.mockResolvedValue([])
    api.world.fetchMapAtlasImage.mockResolvedValue(new Blob(["png"], { type: "image/png" }))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    resetBridgeOverrides()
    vi.restoreAllMocks()
  })

  it("空地图册以一键生成为主操作", async () => {
    api.world.getMapAtlas.mockResolvedValue(tree([], "atlas"))
    api.world.getLatestMapAtlasRun.mockResolvedValue(null)

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.get(".atlas-primary-actions .btn-primary").text()).toBe("一键生成地图册")
    expect(wrapper.text()).toContain("还没有本次生成结果")
    expect(wrapper.get(".atlas-generation-settings").attributes("open")).toBeDefined()
    expect(wrapper.find(".atlas-tabs").exists()).toBe(false)
  })

  it("已有地图册默认收起生成设置但保留可读摘要", async () => {
    api.world.getMapAtlas.mockResolvedValue(tree([
      page({ review_status: "adopted" }),
    ], "atlas"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    const settings = wrapper.get(".atlas-generation-settings")
    expect(settings.attributes("open")).toBeUndefined()
    expect(settings.get("summary").text()).toContain("横版 · 标准 · 仅正式资料 · 不含室内图")
    expect(wrapper.get(".atlas-tabs").exists()).toBe(true)
  })

  it("可选在生图前编辑、复制并确认全部画面说明", async () => {
    vi.useFakeTimers()
    const pending = page({ generation_status: "prepared", image_url: null, has_generation_prompt: true })
    const run = { id: "run-1", status: "prompt_review", planned_page_count: 1, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([pending], "review"))
    api.world.getMapAtlasPagePrompt.mockResolvedValue({ page_id: pending.id, prompt: "东侧临海，北侧是山口", generation_choice: "internal", editable: true, updated_at: pending.updated_at })
    api.world.updateMapAtlasPagePrompt.mockImplementation(async (_novelId, _pageId, body) => ({ page_id: pending.id, prompt: body.prompt, generation_choice: body.generation_choice, editable: true, updated_at: "2026-08-12T00:00:01Z" }))
    api.world.confirmMapAtlasPrompts.mockResolvedValue({ ...run, status: "generating" })
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(async () => {}) } })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.text()).toContain("生图前检查")
    await wrapper.get(".atlas-prompt-editor textarea").setValue("西侧河流汇入港口")
    await wrapper.find("input[value='external']").setValue(true)
    vi.advanceTimersByTime(800); await flushPromises()
    expect(api.world.updateMapAtlasPagePrompt).toHaveBeenCalledWith("novel-1", pending.id, expect.objectContaining({ prompt: "西侧河流汇入港口", generation_choice: "external", expected_updated_at: pending.updated_at }))
    await wrapper.get(".atlas-prompt-editor button").trigger("click")
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("西侧河流汇入港口")
    await wrapper.get(".atlas-prompt-review header .btn-primary").trigger("click"); await flushPromises()
    expect(api.world.confirmMapAtlasPrompts).toHaveBeenCalledWith("novel-1", "run-1", [{ page_id: pending.id, expected_updated_at: "2026-08-12T00:00:01Z" }])
  })

  it("切换页面前保存原页，冲突时不切换且保留编辑", async () => {
    const first = page({ id: "page-a", node_id: "node-a", generation_status: "prepared", image_url: null })
    const second = page({ id: "page-b", node_id: "node-b", generation_status: "prepared", image_url: null })
    const run = { id: "run-1", status: "prompt_review", planned_page_count: 2, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue({ mode: "review", total_pages: 2, nodes: [
      { id: "node-a", title: "A", level: "city", pages: [first], children: [] },
      { id: "node-b", title: "B", level: "city", pages: [second], children: [] },
    ] })
    api.world.getMapAtlasPagePrompt.mockImplementation(async (_novel, id) => ({ page_id: id, prompt: id, generation_choice: "internal", editable: true, updated_at: "v1" }))
    api.world.updateMapAtlasPagePrompt.mockRejectedValue({ status: 409 })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-prompt-editor textarea").setValue("修改 A")
    await wrapper.findAll(".atlas-prompt-review nav button")[1].trigger("click")
    await flushPromises()

    expect(api.world.updateMapAtlasPagePrompt).toHaveBeenCalledWith("novel-1", "page-a", expect.objectContaining({ prompt: "修改 A" }))
    expect(wrapper.get(".atlas-prompt-editor textarea").element.value).toBe("修改 A")
    expect(wrapper.text()).toContain("已在别处更新")
  })

  it("上传失败保留图片和表单以便重试", async () => {
    api.world.uploadMapAtlasPage.mockRejectedValue(new Error("网络中断"))
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" }, attachTo: document.body })
    await flushPromises(); await wrapper.get(".atlas-primary-actions > .btn-sm").trigger("click")
    const file = new File(["png"], "map.png", { type: "image/png" })
    const input = wrapper.get(".atlas-upload-modal input[type='file']")
    Object.defineProperty(input.element, "files", { value: [file], configurable: true })
    await input.trigger("change")
    await wrapper.get(".atlas-upload-modal input.form-input").setValue("北境")
    await wrapper.get(".atlas-upload-modal footer .btn-primary").trigger("click"); await flushPromises()
    expect(wrapper.get(".atlas-upload-modal").text()).toContain("网络中断")
    expect(wrapper.get(".atlas-upload-modal input.form-input").element.value).toBe("北境")
    expect(wrapper.get(".atlas-upload-modal img").attributes("src")).toBe("blob:atlas")
    expect(input.element.files[0]).toBe(file)
    expect(wrapper.get(".atlas-upload-modal footer .btn-primary").text()).toBe("重试上传")
  })

  it("上传对话框困住焦点，关闭路径确认脏表单并恢复触发按钮", async () => {
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" }, attachTo: document.body })
    await flushPromises()
    const trigger = wrapper.get(".atlas-primary-actions > .btn-sm")
    trigger.element.focus()
    await trigger.trigger("click")
    await flushPromises()

    const overlay = wrapper.get(".modal-overlay")
    const close = wrapper.get(".atlas-upload-modal [aria-label='关闭']").element
    const lastSelect = wrapper.findAll(".atlas-upload-modal select").at(-1).element
    expect(document.activeElement).toBe(wrapper.get(".atlas-upload-modal input[type='file']").element)
    close.focus()
    overlay.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(lastSelect)
    lastSelect.focus()
    overlay.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(close)

    await wrapper.get(".atlas-upload-modal input.form-input").setValue("北境")
    confirm.mockReturnValueOnce(false).mockReturnValueOnce(true)
    overlay.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    expect(confirm).toHaveBeenLastCalledWith("放弃未上传的地图？")
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(true)
    overlay.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await flushPromises()
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)

    await trigger.trigger("click")
    await flushPromises()
    await wrapper.get(".atlas-upload-modal input.form-input").setValue("南境")
    await wrapper.get(".modal-overlay").trigger("click")
    await flushPromises()
    expect(confirm).toHaveBeenLastCalledWith("放弃未上传的地图？")
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
  })

  it("外部生成预填以打开时内容为基线，只有后续修改才确认放弃", async () => {
    const external = page({ generation_status: "prompt_only", image_url: null, has_generation_prompt: true })
    api.world.getLatestMapAtlasRun.mockResolvedValue({ id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 })
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([external], "review"))
    api.world.getMapAtlasPagePrompt.mockResolvedValue({ page_id: external.id, prompt: "北面是山，东面是海", generation_choice: "external", editable: false, updated_at: external.updated_at })
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" }, attachTo: document.body })
    await flushPromises()

    const open = async () => {
      await wrapper.get(".atlas-prompt-only .btn-primary").trigger("click")
      await flushPromises()
      expect(wrapper.get(".atlas-upload-modal input.form-input").element.value).toBe("沉钟港")
    }

    await open()
    await wrapper.get(".atlas-upload-modal [aria-label='关闭']").trigger("click")
    expect(confirm).not.toHaveBeenCalled()

    await open()
    wrapper.get(".modal-overlay").element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await flushPromises()
    expect(confirm).not.toHaveBeenCalled()

    await open()
    await wrapper.get(".modal-overlay").trigger("click")
    expect(confirm).not.toHaveBeenCalled()

    await open()
    await wrapper.get(".atlas-upload-modal input.form-input").setValue("沉钟港东区")
    confirm.mockReturnValueOnce(false)
    await wrapper.get(".modal-overlay").trigger("click")
    expect(confirm).toHaveBeenCalledWith("放弃未上传的地图？")
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(true)
  })

  it("上传期间 Escape、遮罩和关闭按钮都不能误关，取消仍中止原请求", async () => {
    let uploadSignal = null
    api.world.uploadMapAtlasPage.mockImplementation((_projectId, _payload, _progress, { signal }) => {
      uploadSignal = signal
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => {
        const error = new Error("aborted")
        error.name = "AbortError"
        reject(error)
      }))
    })
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" }, attachTo: document.body })
    await flushPromises(); await wrapper.get(".atlas-primary-actions > .btn-sm").trigger("click")
    const input = wrapper.get(".atlas-upload-modal input[type='file']")
    Object.defineProperty(input.element, "files", { value: [new File(["png"], "map.png", { type: "image/png" })], configurable: true })
    await input.trigger("change")
    await wrapper.get(".atlas-upload-modal input.form-input").setValue("北境")
    await wrapper.get(".atlas-upload-modal footer .btn-primary").trigger("click")
    await vi.waitFor(() => expect(uploadSignal).not.toBeNull())

    const overlay = wrapper.get(".modal-overlay")
    expect(wrapper.get(".atlas-upload-modal").attributes("aria-busy")).toBe("true")
    expect(wrapper.get(".atlas-upload-modal [aria-label='关闭']").attributes("disabled")).toBeDefined()
    overlay.element.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }))
    await overlay.trigger("click")
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(true)
    expect(confirm).not.toHaveBeenCalled()

    await wrapper.get(".atlas-upload-modal footer button").trigger("click")
    await flushPromises()
    expect(uploadSignal.aborted).toBe(true)
    expect(wrapper.find(".atlas-upload-modal").exists()).toBe(true)
  })

  it("上传对话框卸载时释放背景、预览 URL 和进行中的请求", async () => {
    let uploadSignal = null
    api.world.uploadMapAtlasPage.mockImplementation((_projectId, _payload, _progress, { signal }) => {
      uploadSignal = signal
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => {
        const error = new Error("aborted")
        error.name = "AbortError"
        reject(error)
      }))
    })
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" }, attachTo: document.body })
    await flushPromises(); await wrapper.get(".atlas-primary-actions > .btn-sm").trigger("click")
    const input = wrapper.get(".atlas-upload-modal input[type='file']")
    Object.defineProperty(input.element, "files", { value: [new File(["png"], "map.png", { type: "image/png" })], configurable: true })
    await input.trigger("change")
    await wrapper.get(".atlas-upload-modal input.form-input").setValue("北境")
    await wrapper.get(".atlas-upload-modal footer .btn-primary").trigger("click")
    await vi.waitFor(() => expect(uploadSignal).not.toBeNull())
    const pageHeader = wrapper.get(".atlas-header").element
    expect(pageHeader.hasAttribute("inert")).toBe(true)

    wrapper.unmount()
    await flushPromises()
    expect(pageHeader.hasAttribute("inert")).toBe(false)
    expect(uploadSignal.aborted).toBe(true)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:atlas")
  })

  it("上传候选可在采用前修改名称和位置", async () => {
    const candidate = page({ node_id: "manual-1" })
    const run = { id: "upload-1", run_kind: "upload", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue({ mode: "review", total_pages: 1, nodes: [{ id: "manual-1", title: "旧名", level: "region", status: "provisional", parent_id: null, updated_at: "v1", pages: [candidate], children: [] }] })
    api.world.updateMapAtlasNode.mockResolvedValue({})

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises(); await wrapper.get(".atlas-page > .atlas-edit summary").trigger("click")
    await wrapper.get(".atlas-node-form input.form-input").setValue("北境地图")
    await wrapper.get(".atlas-node-form button").trigger("click"); await flushPromises()
    expect(api.world.updateMapAtlasNode).toHaveBeenCalledWith("novel-1", "manual-1", expect.objectContaining({ title: "北境地图", expected_updated_at: "v1" }))
  })

  it("上传到已采用节点时不允许改名，仍可调整位置", async () => {
    const candidate = page({ node_id: "node-1" })
    const run = { id: "upload-1", run_kind: "upload", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue({ mode: "review", total_pages: 1, nodes: [{ id: "node-1", title: "已采用地图", level: "region", status: "adopted", parent_id: null, updated_at: "v1", pages: [candidate], children: [] }] })
    api.world.updateMapAtlasNode.mockResolvedValue({})

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises(); await wrapper.get(".atlas-page > .atlas-edit summary").trigger("click")
    expect(wrapper.find(".atlas-node-form input.form-input").exists()).toBe(false)
    await wrapper.get(".atlas-node-form button").trigger("click"); await flushPromises()
    expect(api.world.updateMapAtlasNode.mock.calls[0][2]).not.toHaveProperty("title")
  })

  it("外部生成页刷新后仍可复制说明且不显示图片加载", async () => {
    const external = page({ generation_status: "prompt_only", image_url: null, has_generation_prompt: true })
    api.world.getLatestMapAtlasRun.mockResolvedValue({ id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 })
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([external], "review"))
    api.world.getMapAtlasPagePrompt.mockResolvedValue({ page_id: external.id, prompt: "北面是山，东面是海", generation_choice: "external", editable: false, updated_at: external.updated_at })
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn(async () => {}) } })
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.text()).toContain("画面说明已确认，等待外部图片")
    expect(wrapper.get(".atlas-prompt-only").text()).toContain("北面是山")
    expect(wrapper.get(".atlas-prompt-only").text()).not.toContain("正在加载图片")
    await wrapper.get(".atlas-prompt-only button").trigger("click")
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("北面是山，东面是海")
  })

  it("画面说明保存在途时继续编辑，等待新值保存后才切页", async () => {
    let resolveFirst
    const firstSave = new Promise(resolve => { resolveFirst = resolve })
    const first = page({ id: "page-a", node_id: "node-a", generation_status: "prepared", image_url: null })
    const second = page({ id: "page-b", node_id: "node-b", generation_status: "prepared", image_url: null })
    api.world.getLatestMapAtlasRun.mockResolvedValue({ id: "run-1", status: "prompt_review", planned_page_count: 2, completed_page_count: 0 })
    api.world.getMapAtlasRunResults.mockResolvedValue({ mode: "review", total_pages: 2, nodes: [{ id: "node-a", title: "A", level: "city", pages: [first], children: [] }, { id: "node-b", title: "B", level: "city", pages: [second], children: [] }] })
    api.world.getMapAtlasPagePrompt.mockImplementation(async (_novel, id) => ({ page_id: id, prompt: id, generation_choice: "internal", editable: true, updated_at: "v1" }))
    api.world.updateMapAtlasPagePrompt.mockReturnValueOnce(firstSave).mockImplementationOnce(async (_novel, id, body) => ({ page_id: id, ...body, editable: true, updated_at: "v3" }))
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } }); await flushPromises()
    const textarea = wrapper.get(".atlas-prompt-editor textarea")
    await textarea.setValue("第一版")
    await textarea.trigger("input")
    const switching = wrapper.findAll(".atlas-prompt-review nav button")[1].trigger("click")
    await textarea.setValue("第二版")
    resolveFirst({ page_id: "page-a", prompt: "第一版", generation_choice: "internal", editable: true, updated_at: "v2" })
    await switching; await flushPromises()
    expect(api.world.updateMapAtlasPagePrompt).toHaveBeenCalledTimes(2)
    expect(api.world.updateMapAtlasPagePrompt.mock.calls[1][2].prompt).toBe("第二版")
    expect(wrapper.get(".atlas-prompt-editor textarea").element.value).toBe("page-b")
  })

  it("画面说明检查可立即暂停并继续", async () => {
    const pending = page({ generation_status: "prepared", image_url: null })
    const run = { id: "run-1", status: "prompt_review", review_image_prompts: true, planned_page_count: 1, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run); api.world.getMapAtlasRunResults.mockResolvedValue(tree([pending], "review"))
    api.world.getMapAtlasPagePrompt.mockResolvedValue({ page_id: pending.id, prompt: "x", generation_choice: "internal", editable: true, updated_at: "v1" })
    api.world.stopMapAtlasRun.mockResolvedValue({ run_id: "run-1", stop_requested: true })
    api.world.resumeMapAtlasRun.mockResolvedValue(run)
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } }); await flushPromises()
    await wrapper.get(".atlas-run-actions button").trigger("click"); await flushPromises()
    expect(api.world.stopMapAtlasRun).toHaveBeenCalledWith("novel-1", "run-1")
    expect(wrapper.get(".atlas-run").text()).toContain("0 / 1 页")
    expect(wrapper.text()).toContain("继续检查")
    await wrapper.get(".atlas-run-actions .btn-primary").trigger("click"); await flushPromises()
    expect(api.world.resumeMapAtlasRun).toHaveBeenCalledWith("novel-1", "run-1", false)
  })

  it("地图位置默认保持，只在明确选择时发送位置", async () => {
    const adopted = page({ review_status: "adopted" })
    api.world.getMapAtlas.mockResolvedValue(tree([adopted], "atlas")); api.world.updateMapAtlasNode.mockResolvedValue({})
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } }); await flushPromises(); await wrapper.findAll(".atlas-tabs button")[1].trigger("click"); await flushPromises()
    await wrapper.get(".atlas-page > .atlas-edit summary").trigger("click"); await wrapper.get(".atlas-node-form button").trigger("click"); await flushPromises()
    expect(api.world.updateMapAtlasNode.mock.calls[0][2]).not.toHaveProperty("before_node_id")
    await wrapper.findAll(".atlas-node-form select")[2].setValue("__append__"); await wrapper.get(".atlas-node-form button").trigger("click"); await flushPromises()
    expect(api.world.updateMapAtlasNode.mock.calls[1][2]).toMatchObject({ before_node_id: null })
  })

  it("资料不足时说明补充方式并识别同名 API 错误", async () => {
    const run = { id: "run-1", status: "failed", error_code: "insufficient_sources", planned_page_count: 0, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.createMapAtlasRun.mockRejectedValue({ detail: { code: "insufficient_sources" } })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.text()).toContain("已确认资料不足")
    expect(wrapper.text()).toContain("补充并发布世界书")
    expect(wrapper.text()).toContain("加入工作稿资料")

    await wrapper.get(".atlas-primary-actions .btn-primary").trigger("click")
    await flushPromises()
    expect(wrapper.get(".atlas-alert").text()).toContain("已确认资料不足")
  })

  it("只显示服务端安全摘要，旧 run 不显示摘要并说明空间资料降级", async () => {
    api.world.getLatestMapAtlasRun.mockResolvedValue({ id: "run-1", status: "failed", error_code: "spatial_evidence_unavailable", planned_page_count: 0, completed_page_count: 0, evidence_summary: { locations_checked: 1, spatial_facts_used: 2, conflicts: 1 } })
    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.get(".atlas-evidence-summary").text()).toContain("1 处资料不一致")
    expect(wrapper.text()).toContain("空间资料提取暂时不可用")
    wrapper.unmount()

    api.world.getLatestMapAtlasRun.mockResolvedValue({ id: "old", status: "completed", planned_page_count: 0, completed_page_count: 0, evidence_summary: null })
    const old = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(old.find(".atlas-evidence-summary").exists()).toBe(false)
  })

  it("首次读取完成前禁止抢跑创建", async () => {
    let resolveAtlas
    api.world.getMapAtlas.mockReturnValue(new Promise(resolve => { resolveAtlas = resolve }))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    const generate = wrapper.get(".atlas-primary-actions .btn-primary")
    expect(generate.attributes("disabled")).toBeDefined()
    await generate.trigger("click")
    expect(api.world.createMapAtlasRun).not.toHaveBeenCalled()
    resolveAtlas(tree([], "atlas"))
    await flushPromises()
  })

  it("页签和当前层级对辅助技术可读", async () => {
    const candidate = page({ evidence: {} })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.findAll(".atlas-tabs button")[0].attributes("aria-pressed")).toBe("true")
    expect(wrapper.get(".atlas-tabs").attributes("role")).toBe("tablist")
    expect(wrapper.findAll(".atlas-tabs button")[0].attributes("aria-selected")).toBe("true")
    expect(wrapper.get(".atlas-browser").attributes("role")).toBe("tabpanel")
    expect(wrapper.get(".atlas-run progress").attributes("aria-label")).toBe("地图册生成进度")
    expect(wrapper.get(".atlas-tree button").attributes("aria-current")).toBe("true")
  })

  it("图片连接失效时只显示友好说明和设置入口", async () => {
    api.world.createMapAtlasRun.mockRejectedValue({ detail: { code: "image_auth_failed" } })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-primary-actions .btn-primary").trigger("click")
    await flushPromises()

    expect(wrapper.get(".atlas-alert").text()).toContain("OpenAI 图片连接已失效")
    await wrapper.get(".atlas-alert button").trigger("click")
    expect(router.navigate).toHaveBeenCalledWith("settings")
  })

  it("候选与旧图独立展示，冲突候选确认后只执行新增", async () => {
    const candidate = page()
    const adopted = page({ id: "adopted-1", review_status: "adopted", evidence: {} })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getMapAtlas.mockResolvedValue(tree([adopted], "atlas"))
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))
    api.world.reviewMapAtlasPage.mockResolvedValue(candidate)

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.text()).toContain("地图册已有图片")
    expect(wrapper.text()).toContain("新候选")
    expect(wrapper.text()).toContain("AI 为画面补全")
    expect(wrapper.text()).toContain("不属于正式设定")
    await wrapper.get(".atlas-review-actions .btn-primary").trigger("click")
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith("这张图涉及资料冲突。确认仍将它加入地图册吗？")
    expect(api.world.reviewMapAtlasPage).toHaveBeenCalledWith(
      "novel-1",
      "candidate-1",
      "adopt",
      { expected_updated_at: candidate.updated_at, confirm_conflicts: true },
    )
    expect(toast).toHaveBeenCalledWith("已增加，原有图片未改变", "success")
  })

  it("采用或拒绝失败时不会弹出成功提示", async () => {
    const candidate = page({ evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))
    api.world.reviewMapAtlasPage.mockRejectedValue(new Error("页面已在别处更新"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-review-actions .btn-primary").trigger("click")
    await flushPromises()

    expect(wrapper.text()).toContain("页面已在别处更新")
    expect(toast).not.toHaveBeenCalledWith("已增加，原有图片未改变", "success")
  })

  it("等待停止期间禁止新生成和所有写操作", async () => {
    const candidate = page({ evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const removed = page({ id: "removed-1", run_id: "run-0", review_status: "deprecated" })
    const run = { id: "run-1", status: "generating", stop_requested: true, planned_page_count: 2, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))
    api.world.getMapAtlasPageHistory.mockResolvedValue([removed])

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.get(".atlas-primary-actions .btn-primary").attributes("disabled")).toBeDefined()
    expect(wrapper.get(".atlas-review-actions .btn-primary").attributes("disabled")).toBeDefined()
    expect(wrapper.get(".atlas-history button").attributes("disabled")).toBeDefined()
    wrapper.unmount()
  })

  it("已停止后可以继续生成", async () => {
    const run = { id: "run-1", status: "paused", stop_requested: true, planned_page_count: 2, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.resumeMapAtlasRun.mockResolvedValue({ ...run, status: "generating", stop_requested: false })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    const resume = wrapper.get(".atlas-run-actions .btn-primary")
    expect(resume.text()).toBe("继续生成")
    expect(resume.attributes("disabled")).toBeUndefined()
    await resume.trigger("click")
    await flushPromises()

    expect(api.world.resumeMapAtlasRun).toHaveBeenCalledWith("novel-1", "run-1", false)
  })

  it("普通失败的 partial 不空跑继续且不阻塞补全更新", async () => {
    const failed = page({ generation_status: "failed", image_url: null })
    const run = { id: "run-1", status: "partial", error_code: "moderation_blocked", planned_page_count: 1, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([failed], "review"))
    api.world.createMapAtlasRun.mockResolvedValue({ ...run, id: "run-2", status: "planning", error_code: null })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.find(".atlas-run-actions .btn-primary").exists()).toBe(false)
    const update = wrapper.get(".atlas-primary-actions .btn-primary")
    expect(update.attributes("disabled")).toBeUndefined()
    await update.trigger("click")
    await flushPromises()

    expect(api.world.createMapAtlasRun).toHaveBeenCalledTimes(1)
    expect(api.world.resumeMapAtlasRun).not.toHaveBeenCalled()
  })

  it("忽略写操作之前发出的晚到轮询", async () => {
    vi.useFakeTimers()
    const candidate = page({ evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const adopted = page({ review_status: "adopted", evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const generating = { id: "run-1", status: "generating", planned_page_count: 1, completed_page_count: 0 }
    const done = { ...generating, status: "review_ready", completed_page_count: 1 }
    let resolveOldPoll
    api.world.getLatestMapAtlasRun.mockResolvedValueOnce(generating).mockResolvedValue(done)
    api.world.getMapAtlas.mockResolvedValueOnce(tree([], "atlas")).mockResolvedValue(tree([adopted], "atlas"))
    api.world.getMapAtlasRunResults
      .mockResolvedValueOnce(tree([candidate], "review"))
      .mockResolvedValueOnce(tree([adopted], "review"))
      .mockResolvedValueOnce(tree([candidate], "review"))
    api.world.getMapAtlasRun.mockReturnValue(new Promise(resolve => { resolveOldPoll = resolve }))
    api.world.reviewMapAtlasPage.mockResolvedValue(adopted)

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    vi.advanceTimersByTime(2500)
    await flushPromises()
    expect(api.world.getMapAtlasRun).toHaveBeenCalledTimes(1)

    await wrapper.get(".atlas-review-actions .btn-primary").trigger("click")
    await flushPromises()
    resolveOldPoll(generating)
    await flushPromises()

    expect(wrapper.text()).not.toContain("加入地图册")
    expect(api.world.reviewMapAtlasPage).toHaveBeenCalledTimes(1)
  })

  it("确认可能重复费用后的失败会留在页面", async () => {
    const run = { id: "run-1", status: "partial", stop_requested: false, error_code: "retry_requires_confirmation", planned_page_count: 1, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.resumeMapAtlasRun
      .mockRejectedValueOnce({ detail: { code: "retry_requires_confirmation" } })
      .mockRejectedValueOnce({ detail: { code: "image_quota_exhausted" } })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-run-actions .btn-primary").trigger("click")
    await flushPromises()

    expect(api.world.resumeMapAtlasRun).toHaveBeenNthCalledWith(2, "novel-1", "run-1", true)
    expect(wrapper.text()).toContain("OpenAI 图片额度不足")
  })

  it("区分已拒绝与已移出历史，并说明全部拒绝后原图册不变", async () => {
    const rejected = page({ review_status: "rejected" })
    const historicalRejected = page({ id: "rejected-old", run_id: "run-0", review_status: "rejected" })
    const removed = page({ id: "removed-1", run_id: "run-0", review_status: "deprecated" })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([rejected], "review"))
    api.world.getMapAtlasPageHistory.mockResolvedValue([historicalRejected, removed])

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()

    expect(wrapper.text()).toContain("本次候选均未加入")
    expect(wrapper.text()).toContain("已决定不加入")
    expect(wrapper.text()).toContain("已从地图册移出")
    expect(wrapper.findAll(".atlas-history button")).toHaveLength(1)
  })

  it("刷新后仍可进入旧轮未决候选并处理", async () => {
    const oldCandidate = page({ id: "candidate-old", run_id: "run-a", title: "旧轮沉钟港", evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const latestCandidate = page({ id: "candidate-new", run_id: "run-b", title: "新轮沉钟港", evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const oldRun = { id: "run-a", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    const latestRun = { id: "run-b", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(latestRun)
    api.world.getMapAtlasPageHistory.mockResolvedValue([oldCandidate])
    api.world.getMapAtlasRun.mockImplementation(async (_novelId, runId) => runId === oldRun.id ? oldRun : latestRun)
    api.world.getMapAtlasRunResults.mockImplementation(async (_novelId, runId) => tree(
      [runId === oldRun.id ? oldCandidate : latestCandidate],
      "review",
    ))
    api.world.reviewMapAtlasPage.mockResolvedValue(oldCandidate)

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.get(".atlas-page-header h2").text()).toBe("新轮沉钟港")

    await wrapper.get(".atlas-history button").trigger("click")
    await flushPromises()

    expect(api.world.getMapAtlasRun).toHaveBeenCalledWith("novel-1", "run-a")
    expect(wrapper.get(".atlas-page-header h2").text()).toBe("旧轮沉钟港")
    expect(wrapper.find(".atlas-history").exists()).toBe(false)
    expect(wrapper.get(".atlas-run-actions button").text()).toBe("返回最新一轮")

    await wrapper.get(".atlas-review-actions .btn-primary").trigger("click")
    await flushPromises()
    expect(api.world.reviewMapAtlasPage).toHaveBeenCalledWith(
      "novel-1",
      "candidate-old",
      "adopt",
      { expected_updated_at: oldCandidate.updated_at, confirm_conflicts: false },
    )
  })

  it("显示可能重复扣费页面并逐页确认重试", async () => {
    const pending = page({ generation_status: "retry_requires_confirmation", image_url: null })
    const run = { id: "run-1", status: "partial", error_code: "retry_requires_confirmation", planned_page_count: 1, completed_page_count: 0 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([pending], "review"))
    api.world.retryMapAtlasPage.mockResolvedValue(pending)

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.text()).toContain("上次图片请求可能已产生费用")
    await wrapper.get(".atlas-review-actions .btn-primary").trigger("click")
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith("上次图片请求可能已经产生费用。确定再次调用并可能重复扣费吗？")
    expect(api.world.retryMapAtlasPage).toHaveBeenCalledWith("novel-1", "candidate-1", true)
  })

  it("可以按地点名称选择多张已采用地图作为修改参考", async () => {
    const candidate = page({ evidence: { supported: [], visual_fill: [], conflicts: [] } })
    const adopted = Array.from({ length: 8 }, (_, index) => page({ id: `adopted-${index + 1}`, review_status: "adopted", evidence: {} }))
    const derived = page({ id: "derived-1", run_id: "run-edit", generation_status: "prepared", image_url: null })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getMapAtlas.mockResolvedValue(tree(adopted, "atlas"))
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))
    api.world.editMapAtlasPage.mockResolvedValue(derived)
    api.world.getMapAtlasRun.mockResolvedValue({ ...run, id: "run-edit", status: "generating" })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-edit summary").trigger("click")
    await wrapper.get(".atlas-edit textarea").setValue("增加北境河流")
    const references = wrapper.findAll(".atlas-references input")
    expect(wrapper.get(".atlas-references legend").text()).toContain("最多 7 张")
    for (const reference of references.slice(0, 7)) await reference.setValue(true)
    expect(references[7].attributes("disabled")).toBeDefined()
    await wrapper.get(".atlas-edit div .btn").trigger("click")
    await flushPromises()

    expect(wrapper.get(".atlas-references").text()).toContain("沉钟港")
    expect(wrapper.get(".atlas-references").text()).not.toContain("adopted-1")
    expect(api.world.editMapAtlasPage).toHaveBeenCalledWith("novel-1", "candidate-1", {
      instruction: "增加北境河流",
      referencePageIds: adopted.slice(0, 7).map(item => item.id),
      mask: null,
    })
  })

  it("只读取当前候选与当前对比图，切换时释放旧 URL", async () => {
    let urlIndex = 0
    URL.createObjectURL.mockImplementation(() => `blob:atlas-${++urlIndex}`)
    const candidate = page({ evidence: {} })
    const oldOne = page({ id: "old-1", review_status: "adopted", evidence: {} })
    const oldTwo = page({ id: "old-2", review_status: "adopted", evidence: {} })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getMapAtlas.mockResolvedValue(tree([oldOne, oldTwo], "atlas"))
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(api.world.fetchMapAtlasImage.mock.calls.map(call => call[1]).sort()).toEqual(["candidate-1", "old-1"])

    await wrapper.get("select[aria-label='切换地图册已有图片']").setValue("old-2")
    await flushPromises()
    expect(api.world.fetchMapAtlasImage).toHaveBeenCalledWith("novel-1", "old-2")
    expect(URL.revokeObjectURL).toHaveBeenCalled()
  })

  it("图片读取失败会显示就地重试", async () => {
    const candidate = page({ evidence: {} })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))
    api.world.fetchMapAtlasImage.mockRejectedValueOnce(new Error("S3 unavailable"))
      .mockResolvedValue(new Blob(["png"], { type: "image/png" }))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    expect(wrapper.text()).toContain("图片读取失败")
    await wrapper.get(".atlas-image-state button").trigger("click")
    await flushPromises()

    expect(api.world.fetchMapAtlasImage).toHaveBeenCalledTimes(2)
    expect(wrapper.find(".atlas-image-canvas img").exists()).toBe(true)
  })

  it("方图标注使用实际图片矩形，热点和浏览缩放仍可交互", async () => {
    const candidate = page({
      width: 1024,
      height: 1024,
      evidence: {},
      annotations: [{ id: "annotation-1", label: "北门", position_x: 0.25, position_y: 0.75, target_node_id: null }],
    })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    const canvas = wrapper.get(".atlas-image-canvas")
    expect(canvas.attributes("style")).toContain("aspect-ratio: 1024 / 1024")
    expect(wrapper.get(".atlas-annotation").attributes("style")).toContain("left: 25%")
    expect(wrapper.get(".atlas-annotation").attributes("disabled")).toBeUndefined()
    expect(wrapper.get(".atlas-zoom input").attributes("disabled")).toBeUndefined()
  })

  it("拖动标注后吞掉紧随的点击，不误跳到目标节点", async () => {
    vi.stubGlobal("matchMedia", vi.fn(query => ({
      matches: query === "(pointer: fine)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })))
    const annotation = { id: "annotation-1", label: "北门", position_x: 0.25, position_y: 0.75, target_node_id: "node-2", updated_at: "2026-08-12T00:00:00Z" }
    const first = page({ id: "adopted-1", review_status: "adopted", evidence: {}, annotations: [annotation] })
    const second = page({ id: "adopted-2", node_id: "node-2", title: "北门城区", review_status: "adopted", evidence: {} })
    api.world.getMapAtlas.mockResolvedValue({
      mode: "atlas",
      total_pages: 2,
      nodes: [
        { id: "node-1", title: "沉钟港", level: "city", pages: [first], children: [] },
        { id: "node-2", title: "北门城区", level: "district", pages: [second], children: [] },
      ],
    })
    api.world.updateMapAtlasAnnotation.mockResolvedValue({ ...annotation, position_x: 0.5, position_y: 0.5 })

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.findAll(".atlas-tabs button")[1].trigger("click")
    await flushPromises()
    const canvas = wrapper.get(".atlas-image-canvas")
    canvas.element.getBoundingClientRect = () => ({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100 })
    const hotspot = wrapper.get(".atlas-annotation")
    await hotspot.trigger("pointerdown", { clientX: 50, clientY: 75 })
    globalThis.dispatchEvent(new MouseEvent("pointermove", { clientX: 100, clientY: 50 }))
    globalThis.dispatchEvent(new MouseEvent("pointerup", { clientX: 100, clientY: 50 }))
    await hotspot.trigger("click")
    await flushPromises()

    expect(api.world.updateMapAtlasAnnotation).toHaveBeenCalledTimes(1)
    expect(wrapper.get(".atlas-page-header h2").text()).toBe("沉钟港")
  })

  it("人物与设定来源保留精确对象深链，不向作者暴露 ID", async () => {
    const candidate = page({
      evidence: {},
      source_manifest: [{ title: "沉钟港", summary: "已采用地点", open_target: { kind: "core_entity", id: "entity-secret-id" } }],
    })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-evidence details summary").trigger("click")
    await wrapper.get(".atlas-source button").trigger("click")

    const query = router.navigate.mock.calls[0][3]
    expect(router.navigate).toHaveBeenCalledWith("world", "objects", true, expect.any(URLSearchParams))
    expect(query.get("entity_id")).toBe("entity-secret-id")
    expect(query.get("q")).toBe("沉钟港")
    expect(wrapper.text()).not.toContain("entity-secret-id")
  })

  it("工作稿明确标记为非正式设定，正文来源保留跳转目标", async () => {
    const candidate = page({
      evidence: {},
      source_manifest: [
        { source_type: "world_bible_draft", source_status: "working", title: "港口工作稿", summary: "尚未发布", open_target: { kind: "world_bible_draft", draft_id: "draft-1" } },
        { source_type: "rag", title: "第三章正文", summary: "港口描写", open_target: { kind: "writing", chapter_index: 3, chunk_id: "chunk-1" } },
      ],
    })
    const run = { id: "run-1", status: "review_ready", planned_page_count: 1, completed_page_count: 1 }
    api.world.getLatestMapAtlasRun.mockResolvedValue(run)
    api.world.getMapAtlasRunResults.mockResolvedValue(tree([candidate], "review"))

    const wrapper = mount(MapWorkspaceView, { props: { projectId: "novel-1" } })
    await flushPromises()
    await wrapper.get(".atlas-evidence details summary").trigger("click")

    expect(wrapper.text()).toContain("工作稿（非正式设定）")
    const buttons = wrapper.findAll(".atlas-source button")
    await buttons[0].trigger("click")
    await buttons[1].trigger("click")
    expect(router.navigate).toHaveBeenNthCalledWith(1, "world", "bible", true, expect.any(URLSearchParams))
    expect(router.navigate.mock.calls[0][3].get("draft_id")).toBe("draft-1")
    expect(router.navigate).toHaveBeenNthCalledWith(2, "writing", null, true, expect.any(URLSearchParams))
    expect(router.navigate.mock.calls[1][3].get("chapter_index")).toBe("3")
  })
})
