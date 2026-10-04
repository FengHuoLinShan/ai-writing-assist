import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import WorldEntityRevisionHistory from "../../../vue/views/world/library/WorldEntityRevisionHistory.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { worldSession } from "../../../vue/views/world/worldSession.js"

const entity = {
  id: "entity-1",
  entity_type: "character",
  name: "林澈",
  summary: "雾港的调查者",
  public_info: "港务登记在册",
  hidden_truth: "",
  content_json: { aliases: [{ alias: "小林", status: "confirmed" }], _meta: { source: "manual" }, occupation: "调查员" },
  importance_level: "core",
  reveal_level: "author_only",
  status: "canonical",
  updated_at: "2026-10-04T02:00:00Z",
}

function revision(overrides = {}) {
  return {
    revision_id: "rev-1",
    entity_id: "entity-1",
    revision_reason: "manual_update",
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    writing_chapter_index: 3,
    change_note: null,
    changed_fields: ["summary", "hidden_truth"],
    changed_fields_exact: true,
    restored_from_revision_id: null,
    snapshot: {
      entity_type: "character",
      name: "林澈",
      summary: "雾港的调查员",
      public_info: "港务登记在册",
      hidden_truth: "暗桩",
      aliases: ["小林"],
      content_json: { occupation: "调查员" },
      importance: 0.9,
      importance_level: "core",
      reveal_level: "author_only",
      status: "canonical",
    },
    can_restore: true,
    ...overrides,
  }
}

let api
let toast

beforeEach(() => {
  toast = vi.fn()
  api = {
    world: {
      getEntityRevisions: vi.fn(async () => ({ items: [revision()], total: 1, skip: 0, limit: 20, current_updated_at: entity.updated_at })),
      rollbackEntityToRevision: vi.fn(async () => ({ ...entity, summary: "雾港的调查员", hidden_truth: "暗桩" })),
      setRevisionNote: vi.fn(async (payload) => ({ ...payload, updated_at: "2026-10-04T03:00:00Z" })),
    },
  }
  setBridgeOverrides({ api, toast })
})

afterEach(() => {
  resetBridgeOverrides()
  worldSession.changeHistory.queryEpoch = 0
})

async function openHistory(props = {}) {
  const wrapper = mount(WorldEntityRevisionHistory, {
    props: { entity, projectId: "p1", ...props },
    attachTo: document.body,
  })
  wrapper.find("details").element.open = true
  await wrapper.get("details").trigger("toggle")
  await flushPromises()
  return wrapper
}

describe("WorldEntityRevisionHistory 展示", () => {
  it("每条显示相对时间（悬停绝对时间）、词典原因、写作进度与改动字段", async () => {
    const wrapper = await openHistory()
    const item = wrapper.get("[data-revision-id='rev-1']")
    expect(item.text()).toContain("分钟前")
    expect(item.get("[title]").attributes("title")).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    expect(item.text()).toContain("手动编辑")
    expect(item.text()).toContain("写到第 3 章时")
    expect(item.text()).toContain("改动字段：概要、作者秘密")
    expect(item.text()).not.toContain("版本")
    wrapper.unmount()
  })

  it("推算的改动字段标注大致；旧记录不显示写作进度", async () => {
    api.world.getEntityRevisions.mockResolvedValueOnce({
      items: [revision({ changed_fields_exact: false }), revision({ revision_id: "rev-old", writing_chapter_index: null, changed_fields: null })],
      total: 2, skip: 0, limit: 20,
    })
    const wrapper = await openHistory()
    const items = wrapper.findAll("[data-revision-id]")
    expect(items[0].text()).toContain("（大致）")
    expect(items[1].text()).not.toContain("写到第")
    expect(items[1].text()).not.toContain("改动字段")
    wrapper.unmount()
  })

  it("can_restore=false 不显示恢复按钮并提示先恢复对象", async () => {
    api.world.getEntityRevisions.mockResolvedValueOnce({
      items: [revision({ can_restore: false })], total: 1, skip: 0, limit: 20,
    })
    const wrapper = await openHistory()
    expect(wrapper.find("[data-restore='rev-1']").exists()).toBe(false)
    expect(wrapper.text()).toContain("对象已移除，先把对象恢复回来才能恢复历史")
    wrapper.unmount()
  })

  it("展开对比用 VersionTextDiff 展示文本字段前 ↔ 后", async () => {
    const wrapper = await openHistory()
    await wrapper.get("[data-compare-toggle='rev-1']").trigger("click")
    const panel = wrapper.get("[data-compare-panel='rev-1']")
    expect(panel.text()).toContain("这次改动前")
    expect(panel.text()).toContain("现在")
    expect(panel.text()).toContain("调查员")
    expect(panel.text()).toContain("调查者")
    expect(panel.text()).toContain("作者秘密")
    wrapper.unmount()
  })
})

describe("WorldEntityRevisionHistory 其他资料比较", () => {
  it("快照与当前一致时不把别名和内部标记误判为其他资料改动（键序无关）", async () => {
    const same = revision({
      snapshot: { ...revision().snapshot, summary: entity.summary, hidden_truth: "" },
    })
    api.world.getEntityRevisions.mockResolvedValueOnce({ items: [same], total: 1, skip: 0, limit: 20 })
    const reordered = { ...entity, content_json: { occupation: "调查员", _meta: { source: "manual" }, aliases: entity.content_json.aliases } }
    const wrapper = await openHistory({ entity: reordered })
    await wrapper.get("[data-compare-toggle='rev-1']").trigger("click")
    expect(wrapper.get("[data-compare-panel='rev-1']").text()).toContain("这份快照与当前内容一致")
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    const confirmPanel = wrapper.get("[data-restore-confirm='rev-1']")
    expect(confirmPanel.text()).not.toContain("其他资料")
    expect(confirmPanel.text()).toContain("当前内容与快照一致")
    wrapper.unmount()
  })

  it("只改了其他资料时对比面板并列展示前后内容，确认区列出其他资料", async () => {
    const contentOnly = revision({
      changed_fields: ["content"],
      snapshot: { ...revision().snapshot, summary: entity.summary, hidden_truth: "", content_json: { occupation: "医生" } },
    })
    api.world.getEntityRevisions.mockResolvedValueOnce({ items: [contentOnly], total: 1, skip: 0, limit: 20 })
    const wrapper = await openHistory()
    await wrapper.get("[data-compare-toggle='rev-1']").trigger("click")
    const panel = wrapper.get("[data-compare-panel='rev-1']")
    expect(panel.text()).not.toContain("这份快照与当前内容一致")
    const row = panel.get("[data-compare-json='content']")
    expect(row.text()).toContain("医生")
    expect(row.text()).toContain("调查员")
    expect(row.text()).not.toContain("_meta")
    expect(row.text()).not.toContain("小林")
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    expect(wrapper.get("[data-restore-confirm='rev-1']").text()).toContain("其他资料")
    wrapper.unmount()
  })
})

describe("WorldEntityRevisionHistory 备注", () => {
  it("补写备注经 setRevisionNote 保存，成功后展示并提示已保存", async () => {
    const wrapper = await openHistory()
    await wrapper.get("[data-note-edit='rev-1']").trigger("click")
    await wrapper.get("[data-note-input='rev-1']").setValue("  这章改了身份  ")
    await wrapper.get("[data-note-save='rev-1']").trigger("click")
    await flushPromises()
    expect(api.world.setRevisionNote).toHaveBeenCalledWith(
      { target_kind: "entity", revision_id: "rev-1", note: "这章改了身份" },
      "p1",
    )
    expect(toast).toHaveBeenCalledWith("备注已保存", "success")
    expect(wrapper.text()).toContain("备注：这章改了身份")
    wrapper.unmount()
  })

  it("保存失败保留输入并提示失败；空串表示删除备注", async () => {
    api.world.setRevisionNote.mockRejectedValueOnce(new Error("服务暂不可用"))
    const wrapper = await openHistory()
    await wrapper.get("[data-note-edit='rev-1']").trigger("click")
    await wrapper.get("[data-note-input='rev-1']").setValue("会失败的备注")
    await wrapper.get("[data-note-save='rev-1']").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("服务暂不可用")
    expect(wrapper.get("[data-note-input='rev-1']").element.value).toBe("会失败的备注")

    api.world.setRevisionNote.mockClear()
    await wrapper.get("[data-note-input='rev-1']").setValue("   ")
    await wrapper.get("[data-note-save='rev-1']").trigger("click")
    await flushPromises()
    expect(api.world.setRevisionNote).toHaveBeenCalledWith(
      { target_kind: "entity", revision_id: "rev-1", note: "" },
      "p1",
    )
    expect(wrapper.text()).not.toContain("备注：")
    wrapper.unmount()
  })
})

describe("WorldEntityRevisionHistory 恢复", () => {
  it("先影响确认再列改回字段与不变项，确认后调用回滚并提示", async () => {
    const wrapper = await openHistory()
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    const confirmPanel = wrapper.get("[data-restore-confirm='rev-1']")
    expect(confirmPanel.text()).toContain("概要")
    expect(confirmPanel.text()).toContain("作者秘密")
    expect(confirmPanel.text()).toContain("状态保持不变")
    expect(confirmPanel.text()).toContain("可以再撤回")

    await wrapper.get("[data-action='revision-restore-confirm']").trigger("click")
    await flushPromises()
    expect(api.world.rollbackEntityToRevision).toHaveBeenCalledWith(
      "entity-1",
      { revision_id: "rev-1", expected_updated_at: "2026-10-04T02:00:00Z" },
      "p1",
    )
    expect(toast).toHaveBeenCalledWith("已恢复，并记下了这次恢复", "success")
    expect(wrapper.emitted("restored")).toEqual([["entity-1"]])
    wrapper.unmount()
  })

  it("基线 409 提示刚在别处改过并重新读取，不提示成功", async () => {
    const conflict = Object.assign(new Error("请求冲突"), { status: 409, body: { error: "edit_baseline_stale" } })
    api.world.rollbackEntityToRevision.mockRejectedValueOnce(conflict)
    const wrapper = await openHistory()
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    await wrapper.get("[data-action='revision-restore-confirm']").trigger("click")
    await flushPromises()
    expect(wrapper.get("[data-restore-confirm='rev-1']").text()).toContain("这个设定刚在别处改过，已重新读取，请再确认一次")
    expect(toast).not.toHaveBeenCalledWith("已恢复，并记下了这次恢复", "success")
    // 重新加载历史并通知父级刷新实体（新基线经 props 回流）。
    expect(api.world.getEntityRevisions).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted("restored")).toEqual([["entity-1"]])
    wrapper.unmount()
  })

  it("其他失败显示作者可读错误，保留确认区可重试", async () => {
    api.world.rollbackEntityToRevision.mockRejectedValueOnce(Object.assign(new Error("该设定是核心设定，不能改成这个类型"), { status: 409, body: { error: "canon_gate" } }))
    const wrapper = await openHistory()
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    await wrapper.get("[data-action='revision-restore-confirm']").trigger("click")
    await flushPromises()
    expect(wrapper.get("[data-restore-confirm='rev-1']").text()).toContain("该设定是核心设定，不能改成这个类型")
    expect(wrapper.find("[data-restore-confirm='rev-1']").exists()).toBe(true)
    wrapper.unmount()
  })

  it("影响确认被拒绝时不进入确认区", async () => {
    // 独立项目 id 避开 useEditorialGuard 的模块级缓存；assistant 挂在 api 上。
    api.assistant = {
      editorialPolicy: vi.fn(async () => ({ feature_available: true })),
      editorialReviews: vi.fn(async () => [{ status: "running", scope: { scope: "book" } }]),
    }
    setBridgeOverrides({ api, toast, confirm: vi.fn(() => false) })
    const wrapper = await openHistory({ projectId: "p-editorial" })
    await wrapper.get("[data-restore='rev-1']").trigger("click")
    await flushPromises()
    expect(wrapper.find("[data-restore-confirm='rev-1']").exists()).toBe(false)
    wrapper.unmount()
  })
})

describe("WorldEntityRevisionHistory 晚到响应", () => {
  it("切换对象后旧历史的晚到响应不写入新对象", async () => {
    let resolve
    api.world.getEntityRevisions.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const wrapper = mount(WorldEntityRevisionHistory, { props: { entity, projectId: "p1" }, attachTo: document.body })
    wrapper.find("details").element.open = true
    await wrapper.get("details").trigger("toggle")
    await wrapper.setProps({ entity: { ...entity, id: "entity-2" }, projectId: "p1" })
    resolve({ items: [revision()], total: 1, skip: 0, limit: 20 })
    await flushPromises()
    expect(wrapper.text()).toContain("还没有改动记录")
    wrapper.unmount()
  })
})
