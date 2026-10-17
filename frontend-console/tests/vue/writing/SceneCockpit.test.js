import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import SceneCockpit from "../../../vue/views/writing/components/SceneCockpit.vue"

const scene = {
  id: "s1",
  title: "Scene <script>",
  scene_index: 2,
  narrative_tag: "turn",
  goal: "找到线索",
  must_happen: "打开门",
  must_not_happen: "暴露身份",
  core_conflict: "时间不足",
  emotional_beat: "犹豫到决断",
  source: "第一章",
  foreshadowing: "钥匙",
}

function mountCockpit(overrides = {}) {
  return mount(SceneCockpit, {
    props: {
      projectId: "p1",
      chapter: 1,
      scene,
      scenes: [scene],
      allScenes: [scene],
      ...overrides,
    },
  })
}

describe("SceneCockpit", () => {
  let wrapper
  const api = {
    world: { listEntities: vi.fn(async () => ({ items: [], total: 0 })) },
    story: {
      sceneDirectorHistory: vi.fn(async () => ({
        roots: [], branches: [], rounds: [],
        references: [{ id: "director-reference-1", name: "灯下停顿", annotation: "", content_copy: { materials: [] } }],
        recoverable_branches: [], recoverable_references: [],
      })),
    },
  }

  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
    setBridgeOverrides({ api })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    resetBridgeOverrides()
  })

  it("显示本场、对象、提醒、导演四个标签，并在当前 Scene 读写导演参考选择", async () => {
    wrapper = mountCockpit()
    expect(wrapper.find("script").exists()).toBe(false)
    expect(wrapper.text()).toContain("Scene <script>")
    expect(wrapper.findAll('[role="tab"]').map((tab) => tab.text())).toEqual(["本场", "对象", "提醒", "导演"])

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "对象").trigger("click")
    expect(wrapper.text()).toContain("没有明确的 POV 或对象关联")
    expect(wrapper.text()).not.toContain("阿青")
    expect(wrapper.findAll("button").some((button) => button.text() === "打开查证资料")).toBe(true)

    await wrapper.findAll('[role="tab"]').find((tab) => tab.text() === "导演").trigger("click")
    await flushPromises()
    expect(wrapper.get('[data-panel="director"] .scene-director').attributes("data-director-scene")).toBe("s1")
    expect(api.story.sceneDirectorHistory).toHaveBeenCalledWith("p1", "s1")
    expect(wrapper.text()).toContain("保存的参考剧本")
    await wrapper.get('[data-panel="director"] .scene-director__reference-use input').setValue(true)
    expect(wrapper.emitted("update:director-reference-ids")).toEqual([[ ["director-reference-1"] ]])
  })

  it("默认显示白名单本场摘要，扩展资料需显式点击", async () => {
    wrapper = mountCockpit({
      scene: {
        ...scene,
        structure_meta: { outcome: "拿到钥匙", private_prompt: "不应展示" },
      },
    })
    expect(wrapper.get(".scene-lens").text()).toContain("拿到钥匙")
    expect(wrapper.text()).not.toContain("不应展示")
    expect(wrapper.emitted("load-lens")).toBeUndefined()
    await wrapper.get(".scene-lens__load button").trigger("click")
    expect(wrapper.emitted("load-lens")).toHaveLength(1)
  })

  it("扩展资料失败时保留静态摘要并可重试", async () => {
    wrapper = mountCockpit({
      lens: { loading: false, data: null, error: "网络暂时不可用" },
    })
    expect(wrapper.get(".scene-lens").text()).toContain("找到线索")
    expect(wrapper.get(".scene-lens").text()).toContain("静态摘要已保留")
    await wrapper.get(".scene-lens__load button").trigger("click")
    expect(wrapper.emitted("load-lens")).toHaveLength(1)
  })

  it("只消费作者语言的 Scene Lens 三字段条目", () => {
    wrapper = mountCockpit({
      lens: {
        loading: false,
        error: null,
        data: {
          role_visible_knowledge: [{ label: "当前 POV：阿青", summary: "只知道铜铃", availability: true }],
          scene_world_state: [{ label: "人物位置", summary: "暂无可靠记录", availability: false }],
          warnings: [],
        },
      },
    })

    expect(wrapper.text()).toContain("只知道铜铃")
    expect(wrapper.text()).toContain("暂无可靠记录")
    expect(wrapper.get(".scene-lens__section li.is-unavailable").exists()).toBe(true)
  })

  it("本场摘要只渲染一份，不再重复旧设定模块", () => {
    wrapper = mountCockpit()
    expect(wrapper.findAll(".scene-lens")).toHaveLength(1)
    expect(wrapper.get(".scene-lens").text()).toContain("找到线索")
    expect(wrapper.find("[data-cockpit-module]").exists()).toBe(false)
  })

  it("由本章资料内层标题发出 rail 折叠请求", async () => {
    wrapper = mountCockpit()
    await wrapper.get('[aria-label="收起本章资料"]').trigger("click")
    expect(wrapper.emitted("toggle-collapse")).toHaveLength(1)

    await wrapper.setProps({ railCollapsed: true })
    expect(wrapper.classes()).toContain("is-collapsed")
    expect(wrapper.find(".cockpit-tabs").exists()).toBe(false)
    expect(wrapper.get('[aria-label="展开本章资料"]').attributes("aria-expanded")).toBe("false")
  })

  it("在顶部手选本章 Scene，跨章只作标记", async () => {
    const crossChapter = { ...scene, id: "s2", title: "跨章会面", chapter_ids: ["1", "2"] }
    wrapper = mountCockpit({ scenes: [scene, crossChapter], allScenes: [scene, crossChapter] })

    expect(wrapper.findAll(".scene-cockpit-switcher__item")).toHaveLength(2)
    expect(wrapper.findAll(".scene-cockpit-switcher__item")[1].text()).toContain("跨章")
    await wrapper.findAll(".scene-cockpit-switcher__item")[1].trigger("click")
    expect(wrapper.emitted("select-scene")[0]).toEqual(["s2"])
  })

  it("关联弹窗支持连续关联、新建以及打开工作台", async () => {
    const associateScene = vi.fn(async () => ({ id: "s2" }))
    const createScene = vi.fn(async () => ({ id: "s3" }))
    const unlinked = { id: "s2", title: "旅店暗号", scene_index: 3, status: "draft", chapter_ids: [] }
    wrapper = mountCockpit({ allScenes: [scene, unlinked], associateScene, createScene })

    await wrapper.findAll("button").find((button) => button.text().includes("关联场景")).trigger("click")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(associateScene).toHaveBeenCalledWith("s2")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
    await wrapper.setProps({ allScenes: [scene, { ...unlinked, chapter_ids: ["1"] }] })
    expect(wrapper.get('[aria-label="旅店暗号已关联"]').text()).toBe("✓")

    await wrapper.findAll("button").find((button) => button.text().includes("新建场景")).trigger("click")
    await wrapper.get("#scene-associate-title-input").setValue("  钟楼会面  ")
    await wrapper.get(".scene-associate-create").trigger("submit")
    expect(createScene).toHaveBeenCalledWith("钟楼会面")
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)

    await wrapper.findAll("button").find((button) => button.text().includes("打开场景工作台")).trigger("click")
    expect(wrapper.emitted("organize")).toHaveLength(1)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })

  it("在助手中探索按钮携带当前场景与编辑器选区打开助手", async () => {
    const workspace = document.createElement("div")
    workspace.id = "workspace-content"
    const island = document.createElement("div")
    island.className = "vue-island"
    island.dataset.projectId = "p1"
    const editor = document.createElement("textarea")
    editor.id = "writing-editor"
    editor.value = "她把钥匙放回原处，没有回头。"
    editor.selectionStart = 2
    editor.selectionEnd = 4
    island.appendChild(editor)
    workspace.appendChild(island)
    document.body.appendChild(workspace)
    const opener = vi.fn(async () => ({}))
    setBridgeOverrides({ state: { currentProjectId: "p1", viewStates: { writing: { projectId: "p1" } } }, assistantOpener: opener })

    try {
      wrapper = mountCockpit()
      await wrapper.findAll("button").find((button) => button.text() === "在助手中探索这句/这场").trigger("click")
      await flushPromises()
      expect(opener).toHaveBeenCalledTimes(1)
      expect(opener.mock.calls[0][0]).toMatchObject({
        projectId: "p1",
        context: { page: "scene", scope: "current", task_hint: "design", scene_id: "s1", selection: "钥匙" },
      })
    } finally {
      workspace.remove()
    }
  })

  it("助手未就绪时提示错误并保留本页", async () => {
    const toast = vi.fn()
    setBridgeOverrides({
      state: { currentProjectId: "p1" },
      assistantOpener: vi.fn(async () => {
        throw new Error("项目助手正在准备，请稍后从顶部打开。")
      }),
      toast,
    })
    wrapper = mountCockpit()
    await wrapper.findAll("button").find((button) => button.text() === "在助手中探索这句/这场").trigger("click")
    await flushPromises()
    expect(toast).toHaveBeenCalledWith("项目助手正在准备，请稍后从顶部打开。", "error")
    expect(wrapper.text()).toContain("找到线索")
  })

  it("关联失败时保留当前行并可原位重试", async () => {
    const associateScene = vi.fn()
      .mockRejectedValueOnce(new Error("网络暂时不可用"))
      .mockResolvedValueOnce({ id: "s2" })
    const unlinked = { id: "s2", title: "旅店暗号", scene_index: 3, status: "draft", chapter_ids: [] }
    const wrapper = mountCockpit({ allScenes: [scene, unlinked], associateScene })
    await wrapper.findAll("button").find((button) => button.text().includes("关联场景")).trigger("click")

    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(wrapper.text()).toContain("网络暂时不可用")
    expect(wrapper.get('[aria-label="关联 旅店暗号"]').exists()).toBe(true)
    await wrapper.get('[aria-label="关联 旅店暗号"]').trigger("click")
    expect(associateScene).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[role="dialog"]').exists()).toBe(true)
  })
})
