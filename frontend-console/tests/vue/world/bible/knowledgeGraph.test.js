import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, mount } from "@vue/test-utils"
import { nextTick } from "vue"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import WorldBibleTab from "../../../../vue/views/world/bible/WorldBibleTab.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../../vue/bridge/index.js"
import { knowledgeGraphLayout } from "../../../../vue/views/world/bible/useWorldBible.js"

const page = { id: "p1", novel_id: "n1", title: "北境", page_type: "location", status: "canonical", sections_json: [], linked_asset_refs_json: [] }
const graph = { nodes: [{ id: "p1", kind: "world_bible_page", label: "北境" }, { id: "e1", kind: "core_entity", label: "银币" }], edges: [{ id: "edge", kind: "page_entity_reference", source_id: "p1", target_id: "e1", via_relation_id: "r1" }], truncated: false, truncation_reasons: [], omitted_counts: { bad_or_unavailable_ref: 0, page_scan_overflow: 0 } }
let getKnowledgeGraph
let navigate

function mountGraph(pages = [page]) {
  return mount(WorldBibleTab, { props: { projectId: "n1", bible: { pages, categories: [], drafts: [], synopsis: null, pageTemplates: [], activationProfiles: [] } }, attachTo: document.body })
}

enableAutoUnmount(afterEach)
beforeEach(() => {
  getKnowledgeGraph = vi.fn(async () => graph)
  navigate = vi.fn()
  setBridgeOverrides({ state: { currentProjectId: "n1" }, router: { navigate, refresh: vi.fn() }, api: { world: { getKnowledgeGraph } }, toast: vi.fn(), confirm: vi.fn(() => true), confirmAction: vi.fn(), showModalHtml: vi.fn(), closeModal: vi.fn(), esc: String })
})
afterEach(() => { resetBridgeOverrides(); document.body.innerHTML = "" })

describe("World Bible 关联图", () => {
  it("uses the knowledge graph API with the default current-page one-hop scope and expands explicitly", async () => {
    const wrapper = mountGraph()
    await wrapper.get("[data-mode='graph']").trigger("click")
    await nextTick()
    expect(getKnowledgeGraph).toHaveBeenLastCalledWith(expect.objectContaining({ novel_id: "n1", scope: "local", root_type: "world_bible_page", root_id: "p1", depth: 1 }))
    await wrapper.get("[data-action='bible-graph-depth-2']").trigger("click")
    await nextTick()
    expect(getKnowledgeGraph).toHaveBeenLastCalledWith(expect.objectContaining({ scope: "local", depth: 2 }))
    await wrapper.get("[data-action='bible-graph-global']").trigger("click")
    await nextTick()
    expect(getKnowledgeGraph).toHaveBeenLastCalledWith(expect.objectContaining({ scope: "global" }))
  })

  it("opens pages and objects from its accessible node list", async () => {
    const wrapper = mountGraph()
    await wrapper.get("[data-mode='graph']").trigger("click"); await nextTick()
    await wrapper.get("[data-graph-node-id='p1']").trigger("click")
    expect(wrapper.find("#bible-title").exists()).toBe(true)
    expect(wrapper.get("[data-mode='editor']").attributes("aria-pressed")).toBe("true")
    await wrapper.get("[data-mode='graph']").trigger("click"); await nextTick()
    await wrapper.get("[data-graph-node-id='e1']").trigger("click")
    expect(navigate).toHaveBeenCalledWith("world", "objects", true, new URLSearchParams({ entity_id: "e1" }))
  })

  it("shows truncation, retries errors, and discards late responses", async () => {
    let resolveFirst
    getKnowledgeGraph.mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
    getKnowledgeGraph.mockRejectedValueOnce(new Error("网络错误"))
    const wrapper = mountGraph()
    await wrapper.get("[data-mode='graph']").trigger("click")
    await wrapper.get("[data-action='bible-graph-depth-2']").trigger("click")
    resolveFirst({ ...graph, nodes: [{ id: "late", kind: "core_entity", label: "旧响应" }] })
    await nextTick(); await nextTick()
    expect(wrapper.text()).toContain("网络错误")
    getKnowledgeGraph.mockResolvedValueOnce({ ...graph, truncated: true, truncation_reasons: ["result_cap"], omitted_counts: { bad_or_unavailable_ref: 2 } })
    await wrapper.get("[data-action='bible-graph-retry']").trigger("click"); await nextTick()
    expect(wrapper.text()).toContain("结果已部分省略")
    expect(wrapper.text()).toContain("bad_or_unavailable_ref 2")
  })

  it("does not show zero omissions, exposes edge text, and keeps global mode without a page root", async () => {
    const wrapper = mountGraph()
    await wrapper.get("[data-mode='graph']").trigger("click"); await nextTick()
    expect(wrapper.text()).not.toContain("结果已部分省略")
    expect(wrapper.get("[aria-label='关联图关联列表']").text()).toContain("北境 → 页面关联对象（经关系） → 银币")

    const empty = mountGraph([])
    await empty.get("[data-mode='graph']").trigger("click"); await nextTick()
    expect(empty.get("[data-action='bible-graph-depth-1']").attributes("disabled")).toBeDefined()
    expect(empty.get("[data-action='bible-graph-depth-2']").attributes("disabled")).toBeDefined()
    expect(empty.get("[data-action='bible-graph-global']").classes()).toContain("btn-primary")
    expect(empty.get("[data-action='bible-graph-global']").attributes("aria-pressed")).toBe("true")
    expect(getKnowledgeGraph).toHaveBeenLastCalledWith({ novel_id: "n1", scope: "global" })
  })

  it("keeps a deterministic capped SVG aid and a 390px list-first structure", () => {
    const layout = knowledgeGraphLayout(Array.from({ length: 45 }, (_, i) => ({ id: String(i), kind: "core_entity" })), [])
    expect(layout.nodes).toHaveLength(40)
    expect(knowledgeGraphLayout([{ id: "a", kind: "core_entity" }], []).positions).toEqual(knowledgeGraphLayout([{ id: "a", kind: "core_entity" }], []).positions)
    const component = readFileSync(resolve(import.meta.dirname, "../../../../vue/views/world/bible/WorldBibleTab.vue"), "utf8")
    const css = readFileSync(resolve(import.meta.dirname, "../../../../styles.css"), "utf8")
    expect(component).not.toContain("v-html")
    expect(css).toContain("@media (max-width: 390px)")
  })
})
