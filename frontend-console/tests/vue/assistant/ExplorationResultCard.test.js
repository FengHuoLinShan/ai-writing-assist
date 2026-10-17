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

it("renders a goal-directed path with steps and rule constraints, without diagnose or bridge sections", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: {
      mode: "goal",
      original_excerpt: "信使当天把信送到了本人手里",
      goal_path: {
        goal: "信使当天把信送到本人手里",
        steps: [
          { action: "信使向守门人出示驿站登记摘录", condition: "登记摘录写明收信人当日进城", response: "守门人指认唯一的同姓进城者", consequence: "信使当场完成投递", cost_or_risk: "信使暴露了自己的任务" },
          { action: "凭指认当面交付", condition: "收信人确在城内", response: "收信人签收", consequence: "投递闭环", cost_or_risk: "可能投递给同名人" },
        ],
        rule_constraints: ["禁止巧合", "角色性格不得突变"],
        unsolvable: null,
      },
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("导向路径")
  expect(text).toContain("目标：信使当天把信送到本人手里")
  expect(text).toContain("禁止巧合")
  expect(text).toContain("角色性格不得突变")
  expect(text).toContain("行动：信使向守门人出示驿站登记摘录")
  expect(text).toContain("成立条件：登记摘录写明收信人当日进城")
  expect(text).toContain("对方响应：守门人指认唯一的同姓进城者")
  expect(text).toContain("后果：信使当场完成投递")
  expect(text).toContain("代价或风险：信使暴露了自己的任务")
  // 三态互斥：goal 模式不出现缺口或补桥区块
  expect(text).not.toContain("诊断缺口")
  expect(text).not.toContain("补桥候选路径")
  expect(text).not.toContain("为什么需要")
})

it("shows an unsolvable goal path with its missing items", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: {
      mode: "goal",
      original_excerpt: "证人没看到交接，却准确说出接头暗号",
      goal_path: {
        goal: "让证人在无接触的情况下得知暗号",
        steps: [{ action: "证人自行推断暗号", condition: "证人掌握推断依据", response: "证人给出暗号", consequence: "暗号泄露", cost_or_risk: "推断可能出错" }],
        rule_constraints: ["禁止巧合"],
        unsolvable: { reason: "证人没有接触路径，也没有推断依据", missing: ["证人与交接现场之间的任一接触路径"] },
      },
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("无法成立：证人没有接触路径，也没有推断依据")
  expect(text).toContain("缺项：证人与交接现场之间的任一接触路径")
})

it("renders per-subject info boundaries with knows, not_known and the missing-contact marker", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "event",
    output_kind: "story.exploration.event",
    payload: {
      mode: "diagnose",
      original_excerpt: "证人没看到交接，却准确说出接头暗号",
      gaps: [{ description: "证人与交接现场之间缺少接触路径", why_needed: "没有接触就无法得知暗号" }],
      info_boundary: [
        { subject_ref: "c_witness", knows: ["接头暗号的内容"], not_known: ["交接发生的地点与时间"], missing_contact_path: true },
        { subject_description: "守门人", knows: ["登记簿上有收信人"], not_known: [], missing_contact_path: false },
      ],
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("信息边界")
  expect(text).toContain("c_witness")
  expect(text).toContain("知道：接头暗号的内容")
  expect(text).toContain("不知道：交接发生的地点与时间")
  expect(text).toContain("缺接触路径")
  expect(text).toContain("守门人")
  expect(text).toContain("知道：登记簿上有收信人")
  // 主体描述可替代 ref；无缺失接触路径的主体不显示标记
  expect(text).toContain("诊断缺口")
  const missingTags = wrapper.findAll(".exploration-result-card__missing-tag")
  expect(missingTags).toHaveLength(1)
})

it("summarizes goal follow-up results with the target and steps", async () => {
  const explorationDetail = vi.fn(async () => ({ task_id: "task-detail-goal" }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()
  pollConfig().onDone({ done: true }, {
    task_id: "task-detail-goal",
    status: "done",
    result: {
      result_id: "result-goal",
      output_kind: "story.exploration.event",
      payload: {
        mode: "goal",
        original_excerpt: "信使当天把信送到了本人手里",
        goal_path: {
          goal: "信使当天把信送到本人手里",
          steps: [{ action: "出示登记摘录", condition: "摘录写明进城", response: "守门人指认", consequence: "完成投递", cost_or_risk: "暴露任务" }],
          rule_constraints: ["禁止巧合"],
          unsolvable: null,
        },
        unknowns: [],
        warnings: [],
      },
    },
  })
  await flushPromises()
  const followUpText = wrapper.get(".exploration-result-card__followup").text()
  expect(followUpText).toContain("目标：信使当天把信送到本人手里")
  expect(followUpText).toContain("出示登记摘录")
  expect(followUpText).toContain("完成投递")
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

it("renders multi-target scene lines as one block per target", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    payload: {
      target_ref: "",
      line: "",
      rationale: "两个目标各说一句",
      variants: [
        { target_ref: "c_evasive", line: "我只是在渡口等人。", rationale: "回避失业话题", action: "把目光移开", withheld: ["他其实刚被辞退"], unknowns: [], warnings: [] },
        { target_ref: "c_friend", target_label: "老友", line: "缺钱就说一声，别硬撑。", rationale: "察觉对方窘迫", unknowns: [], warnings: [] },
      ],
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  // 优先用 target_label；只有 ref 时显示 ref 本身
  expect(text).toContain("目标：c_evasive")
  expect(text).toContain("目标：老友")
  // 每块保留对白+依据+动作布局
  expect(text).toContain("我只是在渡口等人。")
  expect(text).toContain("依据：回避失业话题")
  expect(text).toContain("动作：把目光移开")
  expect(text).toContain("没有说出口：他其实刚被辞退")
  expect(text).toContain("缺钱就说一声，别硬撑。")
  expect(wrapper.findAll(".exploration-result-card__variant")).toHaveLength(2)
})

it("shows an empty state when a scene line result has no line and no variants", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    payload: { target_ref: "", line: "", rationale: "这一轮没有产出对白", unknowns: [], warnings: [] },
  }, {})
  expect(wrapper.text()).toContain("这条结果没有给出对白内容。")
  expect(wrapper.find("blockquote.exploration-result-card__line").exists()).toBe(false)
})

it("renders the spatial assessment with verdict, constraints and unknowns", () => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    payload: {
      target_ref: "",
      line: "",
      rationale: "按已确认的房间资料核对",
      spatial_assessment: {
        supported: true,
        constraints: ["两人必须隔桌相对，门在背后"],
        unknowns: ["桌上是否有遮挡物未确认"],
      },
      unknowns: [],
      warnings: [],
    },
  }, {})
  const text = wrapper.text()
  expect(text).toContain("空间诊断")
  expect(text).toContain("结论：支持")
  expect(text).toContain("两人必须隔桌相对，门在背后")
  expect(text).toContain("未知：桌上是否有遮挡物未确认")
})

it.each([
  [false, "不支持"],
  [null, "无法判定"],
])("renders the spatial verdict %s when supported=%s", (supported, verdict) => {
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    payload: {
      target_ref: "",
      line: "",
      rationale: "资料不足以判定",
      spatial_assessment: { supported, constraints: [], unknowns: [] },
      unknowns: [],
      warnings: [],
    },
  }, {})
  expect(wrapper.text()).toContain(`结论：${verdict}`)
})

it.each([
  ["multi-target", {
    target_ref: "",
    line: "",
    rationale: "两个目标各一句",
    variants: [
      { target_ref: "c_a", line: "第一条对白。", rationale: "a 的动机", unknowns: [], warnings: [] },
      { target_ref: "c_b", line: "第二条对白。", rationale: "b 的动机", unknowns: [], warnings: [] },
    ],
    unknowns: [],
    warnings: [],
  }, "第一条对白。", "第二条对白。"],
  ["spatial", {
    target_ref: "",
    line: "",
    rationale: "按资料核对",
    spatial_assessment: { supported: false, constraints: ["门必须在东侧"], unknowns: [] },
    unknowns: [],
    warnings: [],
  }, "空间诊断：不支持；约束：门必须在东侧", null],
])("summarizes %s scene_line follow-ups with the compact form", async (_shape, payload, contained, absent) => {
  const explorationDetail = vi.fn(async () => ({ task_id: `task-detail-${_shape}` }))
  const wrapper = mountCard(sandboxSource, { explorationDetail })
  await wrapper.findAll("button").find(button => button.text() === "说详细点").trigger("click")
  await flushPromises()
  pollConfig().onDone({ done: true }, {
    task_id: `task-detail-${_shape}`,
    status: "done",
    result: { result_id: `result-${_shape}`, output_kind: "story.exploration.scene_line", payload },
  })
  await flushPromises()
  const followUpText = wrapper.get(".exploration-result-card__followup").text()
  expect(followUpText).toContain(contained)
  if (absent) expect(followUpText).not.toContain(absent)
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

const lockReceipt = paths => ({
  result_id: "result-1",
  output_kind: "story.exploration.lock_set",
  payload: { locked_items: paths.map(item_path => ({ item_path, item_content_hash: `hash-${item_path}`, label: item_path })) },
})

it("sends the lock request from the item toggle and flips aria-pressed", async () => {
  const explorationLock = vi.fn(async () => lockReceipt(["chain:0"]))
  const wrapper = mountCard(sandboxSource, { explorationLock })
  const lockButton = wrapper.get(".exploration-result-card__lock")
  expect(lockButton.attributes("aria-pressed")).toBe("false")
  expect(lockButton.text()).toContain("锁定")
  expect(lockButton.text()).not.toContain("已锁定")

  await lockButton.trigger("click")
  await flushPromises()

  expect(explorationLock).toHaveBeenCalledTimes(1)
  expect(explorationLock).toHaveBeenCalledWith("result-1", expect.objectContaining({
    novel_id: "p1",
    operation_id: expect.any(String),
    lock: true,
    item_path: "chain:0",
    item_text: "面包需要重新计时",
  }))
  expect(wrapper.get(".exploration-result-card__lock").attributes("aria-pressed")).toBe("true")
  expect(wrapper.get(".exploration-result-card__lock").text()).toContain("已锁定")
  expect(wrapper.get('[role="status"]').text()).toContain("已锁定该条目")
})

it("disables the revise entry with an unlock hint after locking the selected item", async () => {
  const explorationLock = vi.fn(async () => lockReceipt(["chain:0"]))
  const wrapper = mountCard(sandboxSource, { explorationLock })
  await wrapper.get(".exploration-result-card__lock").trigger("click")
  await flushPromises()

  const revise = wrapper.get(".exploration-result-card__op:nth-of-type(1)")
  const option = revise.get('option[value="chain:0"]')
  expect(option.element.disabled).toBe(true)
  expect(option.text()).toContain("已锁定，先解锁")
  expect(revise.get(".exploration-result-card__hint").text()).toContain("已锁定，先解锁")
  await revise.get("textarea").setValue("尝试修订被锁定的条目")
  const reviseButton = revise.findAll("button").find(button => button.text() === "开始修订")
  expect(reviseButton.element.disabled).toBe(true)
})

it("restores the revise entry after unlocking the item", async () => {
  const explorationLock = vi.fn(async () => lockReceipt([]))
  const wrapper = mountCard({ ...sandboxSource, locked_items: ["chain:0"] }, { explorationLock })
  expect(wrapper.get(".exploration-result-card__lock").attributes("aria-pressed")).toBe("true")

  await wrapper.get(".exploration-result-card__lock").trigger("click")
  await flushPromises()

  expect(explorationLock).toHaveBeenCalledWith("result-1", expect.objectContaining({ lock: false, item_path: "chain:0" }))
  expect(wrapper.get(".exploration-result-card__lock").attributes("aria-pressed")).toBe("false")
  const revise = wrapper.get(".exploration-result-card__op:nth-of-type(1)")
  expect(revise.get('option[value="chain:0"]').element.disabled).toBe(false)
  expect(revise.find(".exploration-result-card__hint").exists()).toBe(false)
  await revise.get("textarea").setValue("解锁后继续修订")
  expect(revise.findAll("button").find(button => button.text() === "开始修订").element.disabled).toBe(false)
})

it("shows the server reason and keeps the state when locking hits a drift 409", async () => {
  const explorationLock = vi.fn(async () => { throw Object.assign(new Error("409：条目内容已与当前结果不一致，请刷新后重试"), { status: 409 }) })
  const wrapper = mountCard(sandboxSource, { explorationLock })
  await wrapper.get(".exploration-result-card__lock").trigger("click")
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toContain("条目内容已与当前结果不一致，请刷新后重试")
  expect(wrapper.get(".exploration-result-card__lock").attributes("aria-pressed")).toBe("false")
})

it("marks items locked on mount from source.locked_items", () => {
  const wrapper = mountCard({ ...sandboxSource, locked_items: ["chain:0"] }, {})
  const lockButton = wrapper.get(".exploration-result-card__lock")
  expect(lockButton.attributes("aria-pressed")).toBe("true")
  expect(lockButton.text()).toContain("已锁定")
  const revise = wrapper.get(".exploration-result-card__op:nth-of-type(1)")
  expect(revise.get('option[value="chain:0"]').element.disabled).toBe(true)
  expect(revise.get('option[value="chain:0"]').text()).toContain("已锁定，先解锁")
  expect(revise.findAll("button").find(button => button.text() === "开始修订").element.disabled).toBe(true)
})

it("shows locked item counts in the compare column headers", async () => {
  const explorationHistory = vi.fn(async () => ({
    items: [
      { result_id: "result-1", label: "当前" },
      { result_id: "result-9", label: "重来分支", scale: "sandbox" },
    ],
  }))
  const explorationCompare = vi.fn(async () => ({
    mode: "same_start",
    first: { output_kind: "story.exploration.sandbox", payload: sandboxSource.payload, locked_items: ["chain:0"] },
    second: {
      output_kind: "story.exploration.sandbox",
      payload: { influence_chain: [{ condition: "减半在深夜", effect: "几乎无人察觉" }], unknowns: [] },
      locked_items: ["chain:0", "line"],
    },
  }))
  const wrapper = mountCard(sandboxSource, { explorationHistory, explorationCompare })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()
  await compare.get("select").setValue("result-9")
  await compare.findAll("button").find(button => button.text() === "比较").trigger("click")
  await flushPromises()

  const compareText = wrapper.get(".exploration-result-card__compare").text()
  expect(compareText).toContain("当前结果已锁定 1 项")
  expect(compareText).toContain("对比结果已锁定 2 项")
})

it("shows the server 409 reason when saving an edit that targets a locked item", async () => {
  const explorationSaveEdit = vi.fn(async () => { throw Object.assign(new Error("409：该条目已被锁定，请先解锁后再编辑"), { status: 409 }) })
  const wrapper = mountCard({
    ...sandboxSource,
    scale: "scene_line",
    output_kind: "story.exploration.scene_line",
    locked_items: ["line"],
    payload: { ...sandboxSource.payload, line: "原始对白" },
  }, { explorationSaveEdit })
  expect(wrapper.get(".exploration-result-card__lock").attributes("aria-pressed")).toBe("true")

  const edit = wrapper.get(".exploration-result-card__op:nth-of-type(2)")
  await edit.get("textarea").setValue("对锁定对白的修改")
  await edit.findAll("button").find(button => button.text() === "保存编辑").trigger("click")
  await flushPromises()

  expect(explorationSaveEdit).toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toContain("该条目已被锁定，请先解锁后再编辑")
  expect(wrapper.find(".exploration-result-card__badge").exists()).toBe(false)
})

// --- M3-A 对照视图受影响项 / 关系展示 ---

const sandboxSecondPayload = { influence_chain: [{ condition: "减半在深夜", effect: "几乎无人察觉" }], unknowns: [] }

function compareSides(overrides = {}) {
  return {
    first: { output_kind: "story.exploration.sandbox", payload: sandboxSource.payload, locked_items: [], ...overrides.first },
    second: { output_kind: "story.exploration.sandbox", payload: sandboxSecondPayload, locked_items: [], ...overrides.second },
  }
}

async function runCompare(receipt, { counterfactual = false } = {}) {
  const explorationHistory = vi.fn(async () => ({
    items: [
      { result_id: "result-1", label: "当前" },
      { result_id: "result-9", label: "重来分支", scale: "sandbox" },
    ],
  }))
  const explorationCompare = vi.fn(async () => receipt)
  const wrapper = mountCard(sandboxSource, { explorationHistory, explorationCompare })
  const compare = wrapper.get(".exploration-result-card__op:nth-of-type(3)")
  compare.element.open = true
  await compare.trigger("toggle")
  await flushPromises()
  if (counterfactual) await compare.get('input[value="counterfactual"]').setValue()
  await compare.get("select").setValue("result-9")
  await compare.findAll("button").find(button => button.text() === "比较").trigger("click")
  await flushPromises()
  return { wrapper, compare }
}

it("marks a parent-child same-start compare and lists its affected items", async () => {
  const receipt = {
    ...compareSides(),
    relation: "parent_child",
    affected_items_granularity: "exact",
    affected_items: [
      { item_path: "chain:0", status: "changed", base_excerpt: "面包需要重新计时", derived_excerpt: "面包几乎不需要烤" },
    ],
  }
  const { wrapper } = await runCompare(receipt)
  const compareText = wrapper.get(".exploration-result-card__compare").text()
  expect(compareText).toContain("后代修订对照")
  expect(compareText).toContain("受影响 1 项")
  expect(compareText).toContain("影响链 1")
  expect(compareText).toContain("面包几乎不需要烤")
})

it("renders the three affected-item statuses with excerpts side by side", async () => {
  const receipt = {
    ...compareSides(),
    mode: "counterfactual",
    changed_conditions: ["重力减半窗口从清晨改为深夜"],
    affected_items_granularity: "exact",
    affected_items: [
      { item_path: "chain:0", status: "changed", base_excerpt: "面包需要重新计时", derived_excerpt: "几乎无人察觉" },
      { item_path: "chain:1", status: "added", base_excerpt: "", derived_excerpt: "集市改到午后" },
      { item_path: "chain:2", status: "removed", base_excerpt: "面匠提前收工", derived_excerpt: "" },
    ],
  }
  const { wrapper } = await runCompare(receipt, { counterfactual: true })
  const compare = wrapper.get(".exploration-result-card__compare")
  expect(compare.findAll(".exploration-result-card__affected-status--changed")).toHaveLength(1)
  expect(compare.findAll(".exploration-result-card__affected-status--added")).toHaveLength(1)
  expect(compare.findAll(".exploration-result-card__affected-status--removed")).toHaveLength(1)
  const items = compare.findAll(".exploration-result-card__affected-item")
  expect(items).toHaveLength(3)
  expect(items[0].text()).toContain("变更")
  expect(items[0].text()).toContain("基线：面包需要重新计时")
  expect(items[0].text()).toContain("对照：几乎无人察觉")
  expect(items[1].text()).toContain("新增")
  expect(items[1].text()).toContain("基线：（无）")
  expect(items[1].text()).toContain("对照：集市改到午后")
  expect(items[2].text()).toContain("移除")
  expect(items[2].text()).toContain("基线：面匠提前收工")
  expect(items[2].text()).toContain("对照：（无）")
  // 计数摘要与既有变更条件标签并存
  expect(compare.text()).toContain("受影响 3 项")
  expect(compare.text()).toContain("重力减半窗口从清晨改为深夜")
})

it("shows the conservative disclosure hint instead of an affected list", async () => {
  const receipt = {
    ...compareSides(),
    mode: "counterfactual",
    changed_conditions: ["两侧行不同构，逐项差异无法表达"],
    affected_items: [],
    affected_items_granularity: "conservative",
  }
  const { wrapper } = await runCompare(receipt, { counterfactual: true })
  const compare = wrapper.get(".exploration-result-card__compare")
  expect(compare.text()).toContain("粒度不足，仅保守披露")
  expect(compare.find(".exploration-result-card__affected-list").exists()).toBe(false)
  expect(compare.find(".exploration-result-card__compare-summary").exists()).toBe(false)
  expect(compare.text()).not.toContain("受影响 0 项")
  // 既有变更条件标签不受影响
  expect(compare.text()).toContain("变更条件")
  expect(compare.text()).toContain("两侧行不同构，逐项差异无法表达")
})

it("shows the affected count summary for counterfactual comparisons", async () => {
  const receipt = {
    ...compareSides(),
    mode: "counterfactual",
    changed_conditions: [],
    affected_items_granularity: "exact",
    affected_items: [
      { item_path: "chain:0", status: "changed", base_excerpt: "面包需要重新计时", derived_excerpt: "几乎无人察觉" },
      { item_path: "chain:1", status: "added", base_excerpt: "", derived_excerpt: "集市改到午后" },
    ],
  }
  const { wrapper } = await runCompare(receipt, { counterfactual: true })
  const summary = wrapper.get(".exploration-result-card__compare-summary")
  expect(summary.text()).toContain("受影响 2 项")
  // 非父子对照不显示关系标签
  expect(summary.text()).not.toContain("后代修订对照")
})

it.each([
  ["chain:1", "影响链 2"],
  ["gap:0", "缺口 1"],
  ["bridge:2", "补桥 3"],
  ["line", "对白"],
])("labels affected item path %s as %s", async (itemPath, label) => {
  const receipt = {
    ...compareSides(),
    mode: "counterfactual",
    changed_conditions: [],
    affected_items_granularity: "exact",
    affected_items: [{ item_path: itemPath, status: "changed", base_excerpt: "基线摘录", derived_excerpt: "对照摘录" }],
  }
  const { wrapper } = await runCompare(receipt, { counterfactual: true })
  expect(wrapper.get(".exploration-result-card__compare").text()).toContain(label)
})

it("keeps the compare view unchanged when no affected items are returned", async () => {
  const receipt = { ...compareSides(), relation: "same_start" }
  const { wrapper } = await runCompare(receipt)
  const compare = wrapper.get(".exploration-result-card__compare")
  // 原有渲染保持不变：两列正文可见，无摘要行与受影响区块
  expect(compare.text()).toContain("面包需要重新计时")
  expect(compare.text()).toContain("几乎无人察觉")
  expect(compare.find(".exploration-result-card__compare-summary").exists()).toBe(false)
  expect(compare.find(".exploration-result-card__affected").exists()).toBe(false)
  expect(compare.text()).not.toContain("后代修订对照")
  expect(compare.text()).not.toContain("受影响项")
})
