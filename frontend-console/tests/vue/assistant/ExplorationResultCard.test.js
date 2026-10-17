import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import ExplorationResultCard from "../../../vue/components/assistant/ExplorationResultCard.vue"

const progress = vi.hoisted(() => ({ pollTaskProgress: vi.fn(() => ({ stop: vi.fn() })) }))
vi.mock("../../../shared/workflowProgress.js", async (importOriginal) => ({
  ...await importOriginal(),
  pollTaskProgress: progress.pollTaskProgress,
}))

enableAutoUnmount(afterEach)

const sandboxSource = {
  type: "story_exploration_result",
  root_id: "root-1",
  branch_id: "branch-1",
  result_id: "result-1",
  scale: "sandbox",
  label: "面包师的一天会怎样？",
  output_kind: "story.exploration.sandbox",
  payload: {
    question: "面包师的一天会怎样？",
    influence_chain: [
      { condition: "每天只有一小时重力减半", mechanism: "炉火与面团行为改变", effect: "面包需要重新计时", affected_refs: ["baker"], holds_when: "减半窗口在清晨", unknown: "对面团发酵的精确影响未知" },
    ],
    preconditions: ["城镇居民已适应节律"],
    unknowns: ["长期健康影响未知"],
    warnings: ["不读取章节，仅按规则推演"],
  },
}

function pollConfig() {
  expect(progress.pollTaskProgress).toHaveBeenCalled()
  return progress.pollTaskProgress.mock.calls.at(-1)[0]
}

beforeEach(() => {
  localStorage.clear()
  progress.pollTaskProgress.mockClear()
  progress.pollTaskProgress.mockImplementation(() => ({ stop: vi.fn() }))
})

afterEach(() => {
  resetBridgeOverrides()
  localStorage.clear()
})

function mountCard(source, api) {
  setBridgeOverrides({ api: { story: api }, state: { currentProjectId: "p1" } })
  return mount(ExplorationResultCard, { props: { source, projectId: "p1" } })
}

it("renders a sandbox chain with preconditions and unknowns", () => {
  const wrapper = mountCard(sandboxSource, {})
  const text = wrapper.text()
  expect(text).toContain("沙盘推演")
  expect(text).toContain("面包需要重新计时")
  expect(text).toContain("成立条件：减半窗口在清晨")
  expect(text).toContain("前提条件：城镇居民已适应节律")
  expect(text).toContain("未知：长期健康影响未知")
})

it("renders event diagnosis gaps and keeps the original draft untouched", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: {
      mode: "diagnose",
      original_excerpt: "信使不知道地址，却当天把信送到了本人手里",
      gaps: [{ description: "缺少信件收件地址的来源", why_needed: "没有地址无法投递", possible_fix_hint: "收件人是熟人可认出" }],
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("诊断缺口")
  expect(text).toContain("缺少信件收件地址的来源")
  expect(text).toContain("为什么需要：没有地址无法投递")
  expect(text).toContain("原案：信使不知道地址")
})

it.each([
  ["bridge", "补桥候选路径", "先问到收件人是渡口酒馆常客", "所需条件：能找到认得收件人的证人"],
  ["diagnose", "诊断缺口", null, null],
])("event mode %s renders its own sections", (mode, label, bridgeStep, conditions) => {
  const payload = mode === "bridge"
    ? {
        mode: "bridge",
        bridge_candidates: [{ steps: [bridgeStep, "凭体貌认人并当面交付"], required_conditions: [conditions.split("：")[1]], cost_or_risk: "可能认错人", holds: true }],
        unknowns: [],
        warnings: [],
      }
    : { mode: "diagnose", gaps: [{ description: "缺地址来源" }], unknowns: [], warnings: [] }
  const wrapper = mountCard({ ...sandboxSource, scale: "event", output_kind: "story.exploration.event", payload }, {})
  expect(wrapper.text()).toContain(label)
  if (bridgeStep) expect(wrapper.text()).toContain(bridgeStep)
  if (conditions) expect(wrapper.text()).toContain(conditions)
})

it("shows an unsolvable bridge with its missing items", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: { mode: "bridge", bridge_candidates: [], unsolvable: { reason: "禁止巧合时没有可信路径", missing: ["收件人与信使的任一共同熟人"] }, unknowns: [], warnings: [] },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("无法成立：禁止巧合时没有可信路径")
  expect(text).toContain("缺项：收件人与信使的任一共同熟人")
})

it("renders a scene line with rationale and withheld knowledge", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    payload: {
      target_ref: "c_b",
      line: "你是不是又没睡好？我带了热汤。",
      rationale: "B 只观察到疲惫，不知失业",
      action: "把汤递过去",
      knowledge_basis: ["B 的观察：A 连续两天很疲惫"],
      withheld: ["A 已失业（B 不知道）"],
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("你是不是又没睡好？我带了热汤。")
  expect(text).toContain("依据：B 只观察到疲惫，不知失业")
  expect(text).toContain("没有说出口：A 已失业（B 不知道）")
})

it("marks author edits as saved versions", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.author_edit",
    payload: {
      base_output_kind: "story.exploration.scene_line",
      base_result_id: "result-0",
      edited_payload: { target_ref: "c_b", line: "改后的对白", rationale: "", knowledge_basis: [], withheld: [], unknowns: [], warnings: [] },
      edit_note: "口气更收敛",
    },
  }, {})
  const text = wrapper.text()
  expect(wrapper.get(".exploration-result-card__badge").text()).toBe("已保存编辑")
  expect(text).toContain("改后的对白")
  expect(text).toContain("编辑说明：口气更收敛")
})

it("saves an edit as a new version and clears the local draft on success", async () => {
  const explorationSaveEdit = vi.fn(async () => ({ result_id: "result-edit-1" }))
  const wrapper = mountCard({ ...sandboxSource, scale: "scene_line", output_kind: "story.exploration.scene_line", payload: { ...sandboxSource.payload, line: "原始对白" } }, { explorationSaveEdit })
  const edit = wrapper.get(".exploration-result-card__op:nth-of-type(2)")
  await edit.get("textarea").setValue("改好的对白")
  await edit.findAll("button").find(button => button.text() === "保存编辑").trigger("click")
  await flushPromises()

  expect(explorationSaveEdit).toHaveBeenCalledWith("result-1", expect.objectContaining({
    novel_id: "p1",
    base_output_kind: "story.exploration.scene_line",
    edited_payload: expect.objectContaining({ line: "改好的对白" }),
  }))
  expect(wrapper.get('[role="status"]').text()).toContain("已保存编辑")
  expect(wrapper.get(".exploration-result-card__badge").text()).toBe("已保存编辑")
  expect(localStorage.getItem("novel_exploration_edit_v1:p1:result-1")).toBeNull()
})

it("keeps the draft and shows the failure when the server rejects the edit", async () => {
  const explorationSaveEdit = vi.fn(async () => { throw Object.assign(new Error("服务端保存失败"), { status: 500 }) })
  const wrapper = mountCard({ ...sandboxSource, scale: "scene_line", output_kind: "story.exploration.scene_line", payload: { ...sandboxSource.payload, line: "原始对白" } }, { explorationSaveEdit })
  const edit = wrapper.get(".exploration-result-card__op:nth-of-type(2)")
  await edit.get("textarea").setValue("还没保存成功的对白")
  await edit.findAll("button").find(button => button.text() === "保存编辑").trigger("click")
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toContain("保存未成功")
  expect(edit.get("textarea").element.value).toBe("还没保存成功的对白")
  expect(wrapper.find(".exploration-result-card__badge").exists()).toBe(false)
  expect(JSON.parse(localStorage.getItem("novel_exploration_edit_v1:p1:result-1")).text).toBe("还没保存成功的对白")
})

it("restores an unsaved draft from localStorage after remount", async () => {
  localStorage.setItem("novel_exploration_edit_v1:p1:result-1", JSON.stringify({ text: "刷新前写下的草稿", itemKey: "line", updatedAt: new Date().toISOString() }))
  const explorationSaveEdit = vi.fn(async () => ({ result_id: "result-edit-2" }))
  const wrapper = mountCard({ ...sandboxSource, scale: "scene_line", output_kind: "story.exploration.scene_line", payload: { ...sandboxSource.payload, line: "原始对白" } }, { explorationSaveEdit })
  // 草稿在挂载时恢复；编辑区处于已展开状态，可直接保存。
  const edit = wrapper.get(".exploration-result-card__op:nth-of-type(2)")
  expect(edit.get("textarea").element.value).toBe("刷新前写下的草稿")
  await edit.findAll("button").find(button => button.text() === "保存编辑").trigger("click")
  await flushPromises()
  expect(explorationSaveEdit).toHaveBeenCalledWith("result-1", expect.objectContaining({ edited_payload: expect.objectContaining({ line: "刷新前写下的草稿" }) }))
  expect(wrapper.get(".exploration-result-card__badge").text()).toBe("已保存编辑")
})

it("polls detail to terminal and renders the follow-up result", async () => {
  const explorationDetail = vi.fn(async () => ({ task_id: "task-detail-1", root_id: "root-1", branch_id: "branch-1" }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()

  expect(explorationDetail).toHaveBeenCalledWith("result-1", expect.objectContaining({ novel_id: "p1", operation_id: expect.any(String) }))
  expect(progress.pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-detail-1", novelId: "p1", workflowType: "story_exploration" }))

  const config = pollConfig()
  config.onDone({ done: true }, { task_id: "task-detail-1", status: "done", result: { result_id: "result-2", output_kind: "story.exploration.sandbox", payload: { influence_chain: [{ condition: "更深一层", effect: "集市改到午后" }], unknowns: [] } } })
  await flushPromises()
  expect(wrapper.text()).toContain("补充后的新结果")
  expect(wrapper.text()).toContain("集市改到午后")
  expect(wrapper.emitted("refresh")).toHaveLength(1)
})

it("emits refresh without inline payload when the task only reports completion", async () => {
  const explorationDetail = vi.fn(async () => ({ task_id: "task-detail-2" }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()
  pollConfig().onDone({ done: true }, { task_id: "task-detail-2", status: "done", result: {} })
  await flushPromises()
  expect(wrapper.get('[role="status"]').text()).toContain("刷新讨论后即可查看")
  expect(wrapper.emitted("refresh")).toHaveLength(1)
})

it("surfaces poll failures without hiding the saved result", async () => {
  const explorationDetail = vi.fn(async () => ({ task_id: "task-detail-3" }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()
  pollConfig().onFailed({ failed: true, errorMessage: "任务失败：预算已耗尽" })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain("预算已耗尽")
  expect(wrapper.text()).toContain("面包需要重新计时")
})

it("sends the selected item hash with a revise request", async () => {
  const explorationRevise = vi.fn(async () => ({ task_id: "task-revise-1" }))
  const wrapper = mountCard(sandboxSource, { explorationRevise })
  const revise = wrapper.get(".exploration-result-card__op:nth-of-type(1)")
  await revise.get("select").setValue("chain:0")
  await revise.get("textarea").setValue("只把这一环改得更保守")
  await revise.findAll("button").find(button => button.text() === "开始修订").trigger("click")
  await flushPromises()

  expect(explorationRevise).toHaveBeenCalledWith("result-1", expect.objectContaining({
    novel_id: "p1",
    revision_of: "result-1",
    instruction: "只把这一环改得更保守",
  }))
  const payload = explorationRevise.mock.calls[0][1]
  expect(payload.item_path).toBe("chain:0")
  expect(typeof payload.item_text).toBe("string")
  expect(payload.item_text.length).toBeGreaterThan(0)
  expect(progress.pollTaskProgress).toHaveBeenCalledWith(expect.objectContaining({ taskId: "task-revise-1" }))
})

it("compares against another result from the same start", async () => {
  const explorationHistory = vi.fn(async () => ({
    items: [
      { result_id: "result-1", label: "当前" },
      { result_id: "result-9", label: "重来分支", scale: "sandbox" },
    ],
  }))
  const explorationCompare = vi.fn(async () => ({
    first: { output_kind: "story.exploration.sandbox", payload: sandboxSource.payload },
    second: { output_kind: "story.exploration.sandbox", payload: { influence_chain: [{ condition: "减半在深夜", effect: "几乎无人察觉" }], unknowns: [] } },
  }))
  const wrapper = mountCard(sandboxSource, { explorationHistory, explorationCompare })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()
  expect(explorationHistory).toHaveBeenCalledWith({ novel_id: "p1", root_id: "root-1" })

  await compare.get("select").setValue("result-9")
  await compare.findAll("button").find(button => button.text() === "比较").trigger("click")
  await flushPromises()

  expect(explorationCompare).toHaveBeenCalledWith({ novel_id: "p1", first_result_id: "result-1", second_result_id: "result-9", mode: "same_start" })
  const compareText = wrapper.get(".exploration-result-card__compare").text()
  expect(compareText).toContain("面包需要重新计时")
  expect(compareText).toContain("几乎无人察觉")
  expect(compareText).not.toContain("变更条件")
})

it("runs a counterfactual comparison and renders the changed conditions", async () => {
  const explorationHistory = vi.fn(async () => ({
    items: [
      { result_id: "result-1", label: "当前" },
      { result_id: "result-9", label: "衍生分支", scale: "sandbox" },
    ],
  }))
  const explorationCompare = vi.fn(async () => ({
    mode: "counterfactual",
    changed_conditions: ["重力减半窗口从清晨改为深夜", "城镇居民尚未适应节律"],
    first: { output_kind: "story.exploration.sandbox", payload: sandboxSource.payload },
    second: { output_kind: "story.exploration.sandbox", payload: { influence_chain: [{ condition: "减半在深夜", effect: "几乎无人察觉" }], unknowns: [] } },
  }))
  const wrapper = mountCard(sandboxSource, { explorationHistory, explorationCompare })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()

  expect(compare.find('input[value="counterfactual"]').exists()).toBe(true)
  await compare.get("select").setValue("result-9")
  await compare.get('input[value="counterfactual"]').setValue()
  await compare.findAll("button").find(button => button.text() === "比较").trigger("click")
  await flushPromises()

  expect(explorationCompare).toHaveBeenCalledWith({ novel_id: "p1", first_result_id: "result-1", second_result_id: "result-9", mode: "counterfactual" })
  const compareText = wrapper.get(".exploration-result-card__compare").text()
  expect(compareText).toContain("变更条件")
  expect(compareText).toContain("重力减半窗口从清晨改为深夜")
  expect(compareText).toContain("城镇居民尚未适应节律")
})

it("shows the server reason when the counterfactual pair is unrelated", async () => {
  const explorationHistory = vi.fn(async () => ({
    items: [
      { result_id: "result-1", label: "当前" },
      { result_id: "result-8", label: "无关结果", scale: "sandbox" },
    ],
  }))
  const explorationCompare = vi.fn(async () => {
    throw Object.assign(new Error("409：两条结果既不互为反事实衍生，也不共享同一基线，无法做条件对照"), { status: 409 })
  })
  const wrapper = mountCard(sandboxSource, { explorationHistory, explorationCompare })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()
  await compare.get("select").setValue("result-8")
  await compare.get('input[value="counterfactual"]').setValue()
  await compare.findAll("button").find(button => button.text() === "比较").trigger("click")
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toContain("两条结果既不互为反事实衍生，也不共享同一基线，无法做条件对照")
  expect(wrapper.find(".exploration-result-card__compare").exists()).toBe(false)
})

it("hides the counterfactual mode for non-sandbox results", async () => {
  const explorationHistory = vi.fn(async () => ({ items: [{ result_id: "result-5", label: "另一事件结果" }] }))
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: { mode: "diagnose", gaps: [{ description: "缺地址来源" }], unknowns: [], warnings: [] },
  }, { explorationHistory })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()

  expect(compare.find(".exploration-result-card__modes").exists()).toBe(false)
  expect(compare.find('input[value="counterfactual"]').exists()).toBe(false)
})

it("keeps compare usable when history lists nested roots instead of flat items", async () => {
  const explorationHistory = vi.fn(async () => ({
    roots: [{ id: "root-1", branches: [{ id: "branch-2", results: [{ result_id: "result-7", label: "另一分支" }] }] }],
  }))
  const wrapper = mountCard(sandboxSource, { explorationHistory })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()
  expect(compare.get("select").element.innerHTML).toContain("result-7")
})

it("stops polling when the card unmounts", async () => {
  const stop = vi.fn()
  progress.pollTaskProgress.mockImplementation(() => ({ stop }))
  const explorationDetail = vi.fn(async () => ({ task_id: "task-detail-4" }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()
  wrapper.unmount()
  expect(stop).toHaveBeenCalled()
})
