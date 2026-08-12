/**
 * RagStatusPanel 组件测试 — 状态页渲染与检索记录加载。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import RagStatusPanel from "../../../vue/views/rag/components/RagStatusPanel.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { ragSearchSession, resetRagSearchSession } from "../../../vue/views/rag/ragSearchSession.js"

function makeStatusFields(overrides = {}) {
  return {
    totalChunks: 128,
    embeddingFailedCount: 2,
    retryableEmbeddingCount: 2,
    statusWarnings: [],
    statusDegraded: false,
    embeddingDim: 1024,
    configuredEmbeddingDim: 1024,
    indexedEmbeddingDim: 1024,
    embeddingDimensionMismatch: false,
    embeddingRuntime: { started: true, healthy: true, cache_stats: { hits: 8, misses: 2 } },
    metrics: { avg_latency_ms: 120, embedding_avg_ms: 45, degraded_rate: 0.02 },
    statusItems: [
      {
        chunk_index: 0,
        chapter_index: 1,
        char_count: 500,
        embedding_status: "done",
        entity_ids: ["e1"],
        character_ids: [],
        thread_ids: [],
        scene_id: "s1",
        text: "旧塔的铜铃",
      },
    ],
    indexFreshness: { canonical: { fresh: 10, total: 12 }, working: { fresh: 3, total: 4 } },
    ...overrides,
  }
}

function mountPanel({ statusFields = makeStatusFields(), ...props } = {}) {
  return mount(RagStatusPanel, {
    props: {
      statusFields,
      evidenceHealth: null,
      apiAvailable: true,
      rebuildForm: { contentMode: "canonical", start: "", end: "" },
      ...props,
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  resetRagSearchSession()
  ragSearchSession.rebuildProgress = null
  ragSearchSession.rebuildInfo = null
  ragSearchSession.prewarmState = "idle"
  ragSearchSession.prewarmWarning = ""
  setBridgeOverrides({ state: { currentProjectId: "p1" } })
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("状态页渲染", () => {
  it("概览指标与片段表", () => {
    const wrapper = mountPanel()
    expect(wrapper.text()).toContain("正常")
    expect(wrapper.text()).toContain("128")
    expect(wrapper.text()).toContain("10/12")
    expect(wrapper.findAll(".rag-chunk-table tbody tr")).toHaveLength(1)
    expect(wrapper.find(".rag-chunk-preview").text()).toContain("旧塔的铜铃")
  })

  it("未连接时显示断连空态", () => {
    const wrapper = mountPanel({
      statusFields: makeStatusFields({ totalChunks: null }),
      apiAvailable: false,
    })
    expect(wrapper.text()).toContain("与服务器连接断开")
  })

  it("降级警告与诊断默认展开", () => {
    const wrapper = mountPanel({
      statusFields: makeStatusFields({
        statusDegraded: true,
        statusWarnings: ["部分片段降级"],
        embeddingDimensionMismatch: true,
      }),
    })
    expect(wrapper.text()).toContain("索引不完整")
    expect(wrapper.find(".rag-diagnostics-card").attributes("open")).toBeDefined()
    expect(wrapper.text()).toContain("向量维度配置漂移")
  })

  it("诊断网格渲染运行时指标", () => {
    const wrapper = mountPanel()
    expect(wrapper.text()).toContain("ready")
    expect(wrapper.text()).toContain("120ms")
    expect(wrapper.text()).toContain("8/2")
  })

  it("预热警告产生后诊断自动展开，清除后收回（vanilla 重算语义）", async () => {
    const wrapper = mountPanel()
    expect(wrapper.find(".rag-diagnostics-card").attributes("open")).toBeUndefined()

    ragSearchSession.prewarmWarning = "Embedding 模型不可用"
    await wrapper.vm.$nextTick()
    expect(wrapper.find(".rag-diagnostics-card").attributes("open")).toBeDefined()
    expect(wrapper.text()).toContain("Embedding 模型不可用")

    ragSearchSession.prewarmWarning = ""
    await wrapper.vm.$nextTick()
    expect(wrapper.find(".rag-diagnostics-card").attributes("open")).toBeUndefined()
  })

  it("证据健康卡", () => {
    const wrapper = mountPanel({
      evidenceHealth: {
        health_state: "degraded",
        health_reasons: ["Scene 覆盖率不足"],
        scene_span_coverage: { precise_span_rate: 0.5 },
        rag_mapping_coverage: { eligible_mapping_rate: 0.25 },
        retrieval_summary: { query_count: 9, empty_count: 1 },
      },
    })
    expect(wrapper.text()).toContain("可以改进")
    expect(wrapper.text()).toContain("Scene 覆盖率不足")
    expect(wrapper.get('[data-author-action="can_improve"]').text()).toContain("不代表作品内容有错")
  })
})

describe("检索记录", () => {
  it("点击加载并渲染记录列表", async () => {
    globalThis.api.context.listRetrievalTraces = vi.fn(async () => ({
      items: [
        {
          retrieval_purpose: "写作台",
          content_mode: "canonical",
          candidate_count: 8,
          unique_count: 6,
          hydrated_count: 5,
          drop_counts: { dedup: 2 },
          created_at: "2026-07-18T08:00:00Z",
        },
      ],
    }))
    const wrapper = mountPanel()
    await wrapper.find('[data-action="load-retrieval-traces"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.findAll(".rag-retrieval-trace")).toHaveLength(1)
    })
    expect(wrapper.text()).toContain("写作台")
    expect(wrapper.text()).toContain("丢弃 2")
  })

  it("加载失败显示错误", async () => {
    globalThis.api.context.listRetrievalTraces = vi.fn(async () => {
      throw new Error("权限不足")
    })
    const wrapper = mountPanel()
    await wrapper.find('[data-action="load-retrieval-traces"]').trigger("click")
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain("检索记录加载失败")
    })
  })
})

describe("重建进度", () => {
  it("有进度时渲染 WorkflowProgressCard", () => {
    ragSearchSession.rebuildProgress = {
      taskId: "t1",
      label: "后台任务",
      statusLabel: "运行中",
      percent: 40,
      hasPercent: true,
      availableActions: ["retry"],
    }
    const wrapper = mountPanel()
    expect(wrapper.find(".workflow-progress").exists()).toBe(true)
    expect(wrapper.find('[data-action="retry-task"]').exists()).toBe(true)
  })

  it("rebuildInfo 提示", () => {
    ragSearchSession.rebuildInfo = "暂无可索引工作稿"
    const wrapper = mountPanel()
    expect(wrapper.text()).toContain("暂无可索引工作稿")
  })
})
