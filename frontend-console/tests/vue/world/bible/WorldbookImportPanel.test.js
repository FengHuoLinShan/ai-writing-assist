import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"

import WorldbookImportPanel from "../../../../vue/views/world/bible/WorldbookImportPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"

let api
let navigate
let toast
let confirmFn

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
  confirmFn = vi.fn(() => true)
  setBridgeOverrides({
    api,
    router: { navigate },
    toast,
    confirm: confirmFn,
  })
})

afterEach(() => resetBridgeOverrides())

function mdFile(relPath, content) {
  const file = new File([content], relPath.split("/").pop(), { type: "text/markdown" })
  Object.defineProperty(file, "webkitRelativePath", { value: relPath })
  Object.defineProperty(file, "text", { value: vi.fn(async () => content), configurable: true })
  return file
}

async function selectDirectory(wrapper, files) {
  const input = wrapper.get("input[type='file']")
  Object.defineProperty(input.element, "files", { value: files, configurable: true })
  await input.trigger("change")
  await flushPromises()
}

describe("WorldbookImportPanel", () => {
  it("目录内容保持本地直到预览；应用范围严格等于预览范围", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-1",
      source_format: "obsidian",
      preview_hash: "a".repeat(64),
      counts: { create: 2, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [
        { source_key: "b1".padEnd(64, "0"), title: "理法之环", path: "concepts/真名回响/理法之环.md", action: "create", reason: "新来源" },
        { source_key: "b2".padEnd(64, "0"), title: "本体定位", path: "concepts/真名回响/本体定位.md", action: "create", reason: "新来源" },
      ],
      ignored_paths: ["理法之环/.obsidian/app.json"],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
      link_details: [
        {
          source_key: "b1".padEnd(64, "0"),
          truncated: false,
          details: [
            {
              raw: "[[本体定位]]",
              target: "本体定位",
              alias: "",
              anchor: "",
              origin: "free_text",
              state: "resolved",
              resolved_path: "concepts/真名回响/本体定位.md",
              resolved_title: "本体定位",
            },
          ],
        },
      ],
    })
    api.world.applyWorldbookImport.mockResolvedValue({
      draft_ids: ["draft-1", "draft-2"],
      conflict_ids: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    const entry = mdFile("理法之环/concepts/真名回响/理法之环.md", "---\ntitle: 理法之环\n---\n参见 [[本体定位]]。")
    const related = mdFile("理法之环/concepts/真名回响/本体定位.md", "本体定位正文")
    const image = new File(["binary"], "map.png", { type: "image/png" })
    Object.defineProperty(image, "webkitRelativePath", { value: "理法之环/map.png" })
    Object.defineProperty(image, "text", { value: vi.fn(async () => "must not read") })
    await selectDirectory(wrapper, [entry, related, image])

    // 首批以理法之环为入口自动纳入；关联页面只提示，不自动扩展
    expect(wrapper.text()).toContain("已选 1 页")
    expect(wrapper.text()).toContain("直接关联中未纳入的页面（1）")
    expect(wrapper.text()).toContain("本体定位")
    expect(api.world.previewWorldbookImport).not.toHaveBeenCalled()
    expect(image.text).not.toHaveBeenCalled()

    // 作者扩展层级：纳入候选后显示新增文件数与大小
    await wrapper.get('[data-action="worldbook-import-adopt"]').trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("已选 2 页")
    expect(wrapper.text()).toContain("新增 1 页")

    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(api.world.previewWorldbookImport).toHaveBeenCalledTimes(1)
    const [novelId, manifest] = api.world.previewWorldbookImport.mock.calls[0]
    expect(novelId).toBe("p1")
    expect(manifest).toEqual({
      source_format: "auto",
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      files: [
        { path: "理法之环/concepts/真名回响/理法之环.md", content: "---\ntitle: 理法之环\n---\n参见 [[本体定位]]。" },
        { path: "理法之环/concepts/真名回响/本体定位.md", content: "本体定位正文" },
      ],
    })
    expect(image.text).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("新建 2")
    expect(wrapper.text()).toContain("资料集「理法之环」")
    expect(wrapper.text()).toContain("完整快照")
    expect(wrapper.text()).toContain("Obsidian Vault")

    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(confirmFn).toHaveBeenCalledWith("只会创建或更新未发布工作稿；冲突不会覆盖，是否继续？")
    expect(api.world.applyWorldbookImport).toHaveBeenCalledWith("import-1", "p1", "a".repeat(64))
    expect(navigate).toHaveBeenCalledWith("world", "bible", true, new URLSearchParams("draft_id=draft-1"))
    expect(toast).toHaveBeenCalledWith(expect.stringContaining("导入完成"), "success")
  })

  it("预览区分未发布工作稿与已发布页目标，不把导入当成已发布", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-6",
      source_format: "obsidian",
      preview_hash: "b".repeat(64),
      counts: { create: 1, update: 1, preserve: 0, conflict: 0, missing: 0 },
      items: [
        { source_key: "c1".padEnd(64, "0"), title: "理法之环", path: "concepts/真名回响/理法之环.md", action: "update", target_kind: "draft", target_id: "draft-1", reason: "仅来源变化，可安全更新工作稿" },
        { source_key: "c2".padEnd(64, "0"), title: "星锻环", path: "concepts/星锻环.md", action: "create", target_kind: "page", target_id: "page-9", reason: "新来源" },
      ],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "continue",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("环/理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()

    // 每一项展示真实目标状态：工作稿 vs 已发布页（预览清单是页面里最后一个列表）
    const lists = wrapper.findAll("ul.worldbook-import-items")
    const itemsText = lists[lists.length - 1].text()
    expect(itemsText).toContain("安全更新 · 工作稿 · concepts/真名回响/理法之环.md")
    expect(itemsText).toContain("新建工作稿 · 已发布页 · concepts/星锻环.md")
    // 汇总披露：已发布页的更新同样只落工作稿，发布需另行确认
    expect(wrapper.text()).toContain("应用只会创建或更新未发布工作稿；发布仍需在工作台逐页确认。")
    expect(wrapper.text()).toContain("其中 1 项目标已是已发布页，应用后生成对应工作稿。")
  })

  it("预览展示未纳入、名称歧义与未解析引用，不按同名猜身份", async () => {
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    const entry = mdFile("环世界/理法之环.md", "见 [[本体定位]]、[[星锻环]] 与 [[魔法 API]]。")
    const target = mdFile("环世界/本体定位.md", "正文")
    const dupA = mdFile("环世界/places/星锻环.md", "甲")
    const dupB = mdFile("环世界/concepts/星锻环.md", "乙")
    await selectDirectory(wrapper, [entry, target, dupA, dupB])

    expect(wrapper.text()).toContain("直接关联中未纳入的页面（1）")
    expect(wrapper.text()).toContain("名称歧义（1）")
    expect(wrapper.text()).toContain("同名多页，不会按名称猜测")
    expect(wrapper.text()).toContain("未解析引用（1）")
    expect(wrapper.text()).toContain("魔法 API")
  })

  it("恢复预览保持冻结快照，接续旧导入展示对照与上下文失效披露", async () => {
    api.world.getWorldbookImport.mockResolvedValue({
      suggestion_id: "import-2",
      source_format: "obsidian",
      preview_hash: "c".repeat(64),
      counts: { create: 0, update: 1, preserve: 1, conflict: 0, missing: 0 },
      items: [],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "adopt_legacy",
      commit_mode: "full_snapshot",
      legacy_bindings: [
        { source_key: "k1".padEnd(64, "0"), legacy_source_path: "理法之环/concepts/真名回响/理法之环.md", rel_path: "concepts/真名回响/理法之环.md" },
        { source_key: "k2".padEnd(64, "0"), legacy_source_path: "理法之环/concepts/星锻环.md", rel_path: "concepts/星锻环.md" },
      ],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true, suggestionId: "import-2" },
    })
    await flushPromises()
    expect(api.world.getWorldbookImport).toHaveBeenCalledWith("import-2", "p1")
    expect(wrapper.text()).toContain("将接续绑定的旧导入（2）")
    expect(wrapper.text()).toContain("理法之环/concepts/星锻环.md")
    expect(wrapper.text()).toContain("接续旧导入")
    expect(wrapper.text()).toContain("作者 AI 上下文确认会失效")

    // 接续应用前的确认文案披露副作用
    api.world.applyWorldbookImport.mockResolvedValue({ draft_ids: ["draft-9"], conflict_ids: [] })
    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(confirmFn).toHaveBeenCalledWith(expect.stringContaining("作者 AI 上下文确认会失效"))
  })

  it("新资料集重名时按机器码用作者语言提示继续维护或换名", async () => {
    api.world.previewWorldbookImport.mockRejectedValue(Object.assign(
      new Error("请求参数错误：Dataset name already exists in this project: 理法之环; continue maintaining it or choose another name"),
      {
        status: 400,
        // explainError 只认 api.js 透传的机器码，不依赖报错文案措辞
        body: { error: "worldbook_dataset_exists" },
        detail: "Dataset name already exists in this project: 理法之环; continue maintaining it or choose another name",
      },
    ))
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("继续维护")
    expect(wrapper.text()).toContain("换一个名字")
  })

  it("过期预览与应用失败不改动站内资产，取消时不发应用请求", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-3",
      source_format: "generic",
      preview_hash: "d".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    api.world.applyWorldbookImport.mockRejectedValue(Object.assign(new Error("请求冲突"), { status: 409 }))
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()

    // 作者取消：不发应用请求
    confirmFn.mockReturnValue(false)
    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(api.world.applyWorldbookImport).not.toHaveBeenCalled()

    // 过期（409）：用作者语言提示，预览保留可重试
    confirmFn.mockReturnValue(true)
    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(api.world.applyWorldbookImport).toHaveBeenCalledWith("import-3", "p1", "d".repeat(64))
    expect(wrapper.text()).toContain("预览已过期")
    expect(wrapper.text()).toContain("刚才没有改动站内资料")
    expect(wrapper.get('[data-action="worldbook-import-apply"]').exists()).toBe(true)
  })

  it("入口读取失败停在本地，不发请求也不改动站内资产", async () => {
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    const broken = mdFile("理法之环.md", "正文")
    Object.defineProperty(broken, "text", { value: vi.fn(async () => { throw new Error("read failed") }) })
    await selectDirectory(wrapper, [broken])
    expect(wrapper.text()).toContain("读取「理法之环」失败")
    expect(wrapper.text()).toContain("站内资料没有变化")
    expect(wrapper.find('[data-action="worldbook-import-preview"]').exists()).toBe(false)
    expect(api.world.previewWorldbookImport).not.toHaveBeenCalled()
  })

  it("预览后修改导入语义会使预览失效，须重新预览才能应用", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-4",
      source_format: "obsidian",
      preview_hash: "e".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-action="worldbook-import-apply"]').exists()).toBe(true)

    // 改语义后旧预览立即失效：应用入口消失并明示须重新预览
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环续卷")
    expect(wrapper.find('[data-action="worldbook-import-apply"]').exists()).toBe(false)
    expect(wrapper.text()).toContain("之前的预览已失效")

    // 重新预览后应用的是新语义的预览
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(api.world.previewWorldbookImport).toHaveBeenCalledTimes(2)
    expect(api.world.previewWorldbookImport.mock.calls[1][1].dataset_name).toBe("理法之环续卷")
    expect(wrapper.get('[data-action="worldbook-import-apply"]').exists()).toBe(true)
  })

  it("预览后扩展范围会使预览失效，重新预览覆盖新增页面", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-5",
      source_format: "obsidian",
      preview_hash: "f".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    const entry = mdFile("理法之环/理法之环.md", "参见 [[本体定位]]。")
    const related = mdFile("理法之环/本体定位.md", "本体定位正文")
    await selectDirectory(wrapper, [entry, related])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(api.world.previewWorldbookImport.mock.calls[0][1].files).toHaveLength(1)
    expect(wrapper.get('[data-action="worldbook-import-apply"]').exists()).toBe(true)

    // 预览后纳入候选页：旧预览失效，应用入口消失
    await wrapper.get('[data-action="worldbook-import-adopt"]').trigger("click")
    await flushPromises()
    expect(wrapper.find('[data-action="worldbook-import-apply"]').exists()).toBe(false)
    expect(wrapper.text()).toContain("之前的预览已失效")

    // 重新预览覆盖新增页面；应用的是最新范围
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()
    expect(api.world.previewWorldbookImport).toHaveBeenCalledTimes(2)
    expect(api.world.previewWorldbookImport.mock.calls[1][1].files).toHaveLength(2)
    expect(api.world.previewWorldbookImport.mock.calls[1][1].files.map((file) => file.path)).toEqual([
      "理法之环/理法之环.md",
      "理法之环/本体定位.md",
    ])
    await wrapper.get('[data-action="worldbook-import-apply"]').trigger("click")
    await flushPromises()
    expect(api.world.applyWorldbookImport).toHaveBeenCalledWith("import-5", "p1", "f".repeat(64))
  })

  it("预览展示引用缺口计数、发布阻断披露与问题页标记", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-7",
      source_format: "obsidian",
      preview_hash: "7".repeat(64),
      counts: { create: 2, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [
        {
          source_key: "d1".padEnd(64, "0"),
          title: "理法之环",
          path: "concepts/理法之环.md",
          action: "create",
          reason: "新来源",
          link_summary: { resolved: 2, ambiguous: 1, unresolved: 2, unselected: 1 },
        },
        {
          source_key: "d2".padEnd(64, "0"),
          title: "本体定位",
          path: "concepts/本体定位.md",
          action: "create",
          reason: "新来源",
          link_summary: { resolved: 0, ambiguous: 0, unresolved: 1, unselected: 0 },
        },
      ],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("环/理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()

    // 聚合四态计数：两页合计；已解析只计总数，不逐条罗列
    expect(wrapper.find('[aria-label="引用解析统计"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("引用：已解析 2 条")
    expect(wrapper.text()).toContain("名称歧义 1 条")
    expect(wrapper.text()).toContain("未解析 3 条")
    expect(wrapper.text()).toContain("未纳入 1 条")
    // 披露后果与出路，不得弱化「会阻断发布」
    expect(wrapper.text()).toContain("2 页存在未解析、名称歧义或未纳入的引用")
    expect(wrapper.text()).toContain("链接会保留原文，但发布校验会因悬空链接被阻断")
    expect(wrapper.text()).toContain("可扩大所选范围或清理链接后重新导入")
    // 问题页在清单行内追加标记，可定位；无问题的页不加噪音
    expect(wrapper.text()).toContain("新来源；引用：名称歧义 1 条、未解析 2 条、未纳入 1 条")
    expect(wrapper.text()).toContain("新来源；引用：未解析 1 条")
  })

  it("引用计数全部为 0 时预览不渲染任何引用 UI", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-8",
      source_format: "generic",
      preview_hash: "8".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [
        {
          source_key: "e1".padEnd(64, "0"),
          title: "理法之环",
          path: "理法之环.md",
          action: "create",
          reason: "新来源",
          link_summary: { resolved: 0, ambiguous: 0, unresolved: 0, unselected: 0 },
        },
      ],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[aria-label="引用解析统计"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain("引用：")
    expect(wrapper.text()).not.toContain("悬空链接")
    // 预览本身正常，应用入口不受影响
    expect(wrapper.get('[data-action="worldbook-import-apply"]').exists()).toBe(true)
  })

  it("引用全部解析时只显示计数，不显示阻断披露", async () => {
    api.world.previewWorldbookImport.mockResolvedValue({
      suggestion_id: "import-9",
      source_format: "obsidian",
      preview_hash: "9".repeat(64),
      counts: { create: 1, update: 0, preserve: 0, conflict: 0, missing: 0 },
      items: [
        {
          source_key: "f1".padEnd(64, "0"),
          title: "理法之环",
          path: "concepts/理法之环.md",
          action: "create",
          reason: "新来源",
          link_summary: { resolved: 4, ambiguous: 0, unresolved: 0, unselected: 0 },
        },
      ],
      ignored_paths: [],
      dataset_name: "理法之环",
      dataset_intent: "new",
      commit_mode: "full_snapshot",
      legacy_bindings: [],
    })
    const wrapper = mount(WorldbookImportPanel, {
      props: { projectId: "p1", open: true },
    })
    await selectDirectory(wrapper, [mdFile("环/理法之环.md", "正文")])
    await wrapper.get('[data-action="worldbook-import-dataset-name"]').setValue("理法之环")
    await wrapper.get('[data-action="worldbook-import-preview"]').trigger("click")
    await flushPromises()

    expect(wrapper.find('[aria-label="引用解析统计"]').exists()).toBe(true)
    expect(wrapper.text()).toContain("引用：已解析 4 条")
    expect(wrapper.text()).not.toContain("悬空链接")
    expect(wrapper.text()).not.toContain("引用：名称歧义")
  })
})
