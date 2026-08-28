<template>
  <section class="panel world-bible-graph" aria-labelledby="world-bible-graph-title">
    <div class="world-bible-panel__header">
      <div>
        <h2 id="world-bible-graph-title">关联图</h2>
        <div class="world-bible-page-meta">关联不等于变更影响；依赖影响未覆盖。</div>
      </div>
      <div class="world-bible-panel__actions" role="group" aria-label="关联图范围">
        <button class="btn btn-sm" data-action="bible-graph-depth-1" :disabled="!hasPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 1" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 1 }" @click="setGraphDepth(1)">当前页 · 1 跳</button>
        <button class="btn btn-sm" data-action="bible-graph-depth-2" :disabled="!hasPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 2" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 2 }" @click="setGraphDepth(2)">扩展到 2 跳</button>
        <button class="btn btn-sm" data-action="bible-graph-global" :aria-pressed="graphScope === 'global'" :class="{ 'btn-primary': graphScope === 'global' }" @click="setGraphScope('global')">全局</button>
      </div>
    </div>
    <p v-if="graphLoading" class="world-bible-empty-hint" role="status">正在加载关联图…</p>
    <div v-else-if="graphError" class="empty-state" role="alert">
      <p>{{ graphError }}</p><button class="btn btn-sm" data-action="bible-graph-retry" @click="loadKnowledgeGraph">重试</button>
    </div>
    <template v-else-if="knowledgeGraph">
      <p v-if="partialDetails.length" class="world-bible-projection-status__hint">
        结果已部分省略：{{ partialDetails.join('；') }}。
      </p>
      <p v-if="!knowledgeGraph.nodes?.length" class="world-bible-empty-hint">尚没有可展示的已采用关联。</p>
      <ul class="world-bible-graph__list" aria-label="关联图节点列表">
        <li v-for="node in knowledgeGraph.nodes || []" :key="node.id">
          <button class="btn world-bible-graph__node" :data-graph-node-kind="node.kind" :data-graph-node-id="node.id" @click="openNode(node)">
            <strong>{{ node.label || '未命名资料' }}</strong><span>{{ node.kind === 'world_bible_page' ? '世界书页' : '世界对象' }}</span>
          </button>
        </li>
      </ul>
      <ul v-if="graphEdges.length" class="world-bible-graph__edges" aria-label="关联图关联列表">
        <li v-for="edge in graphEdges" :key="edge.id">{{ edge.sourceLabel }} → {{ edge.kindLabel }}{{ edge.via_relation_id ? '（经关系）' : '' }} → {{ edge.targetLabel }}</li>
      </ul>
      <details class="world-bible-graph__visual">
        <summary>查看关系示意图（最多 40 个节点 / 80 条边）</summary>
        <svg v-if="graphLayout.nodes.length" class="world-bible-graph__svg" :viewBox="`0 0 560 ${Math.max(160, graphLayout.nodes.length * 72 + 40)}`" role="img" aria-label="世界书关联示意图">
          <line v-for="edge in graphLayout.edges" :key="edge.id" :x1="graphLayout.positions[edge.source_id].x" :y1="graphLayout.positions[edge.source_id].y" :x2="graphLayout.positions[edge.target_id].x" :y2="graphLayout.positions[edge.target_id].y" />
          <g v-for="node in graphLayout.nodes" :key="node.id" :transform="`translate(${graphLayout.positions[node.id].x}, ${graphLayout.positions[node.id].y})`"><circle r="22" /><text y="4">{{ node.label?.slice(0, 8) }}</text></g>
        </svg>
      </details>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"
import { knowledgeGraphLayout } from "./worldBiblePresentation.js"

const props = defineProps({
  projectId: { type: String, required: true },
  activePage: { type: Object, default: null },
})
const emit = defineEmits(["open-page", "open-entity"])
const api = getApi()
const knowledgeGraph = ref(null)
const graphLoading = ref(false)
const graphError = ref(null)
const graphScope = ref(props.activePage?.id ? "local" : "global")
const graphDepth = ref(1)
let requestGeneration = 0
let disposed = false

const hasPageRoot = computed(() => Boolean(props.activePage?.id))
const graphLayout = computed(() => knowledgeGraphLayout(knowledgeGraph.value?.nodes || [], knowledgeGraph.value?.edges || []))
const partialDetails = computed(() => {
  const result = knowledgeGraph.value || {}
  const counts = Object.entries(result.omitted_counts || {}).filter(([, value]) => Number(value) > 0)
  const reasons = result.truncated ? (result.truncation_reasons || []) : []
  return [...reasons, ...counts.map(([key, value]) => `${key} ${value}`)]
})
const graphEdges = computed(() => {
  const labels = new Map((knowledgeGraph.value?.nodes || []).map((node) => [node.id, node.label || "未命名资料"]))
  const kinds = { page_reference: "页面引用", page_entity_reference: "页面关联对象", entity_relation: "对象关系" }
  return (knowledgeGraph.value?.edges || []).map((edge) => ({
    ...edge,
    sourceLabel: labels.get(edge.source_id) || "不可用来源",
    targetLabel: labels.get(edge.target_id) || "不可用目标",
    kindLabel: kinds[edge.kind] || "关联",
  }))
})

function graphParams() {
  if (!props.activePage?.id) return { novel_id: props.projectId, scope: "global" }
  return {
    novel_id: props.projectId,
    scope: graphScope.value,
    root_type: "world_bible_page",
    root_id: props.activePage.id,
    depth: graphDepth.value,
  }
}

async function loadKnowledgeGraph() {
  if (!props.activePage?.id) graphScope.value = "global"
  const owner = { projectId: props.projectId, pageId: props.activePage?.id || null }
  const request = ++requestGeneration
  graphLoading.value = true
  graphError.value = null
  try {
    const result = await api.world.getKnowledgeGraph(graphParams())
    if (disposed || request !== requestGeneration || owner.projectId !== props.projectId || owner.pageId !== (props.activePage?.id || null)) return false
    knowledgeGraph.value = result
    return true
  } catch (error) {
    if (!disposed && request === requestGeneration && owner.projectId === props.projectId) graphError.value = error.message || "关联图加载失败"
    return false
  } finally {
    if (!disposed && request === requestGeneration && owner.projectId === props.projectId) graphLoading.value = false
  }
}

function setGraphDepth(depth) {
  if (!props.activePage?.id) {
    graphScope.value = "global"
  } else {
    graphDepth.value = depth === 2 ? 2 : 1
    graphScope.value = "local"
  }
  void loadKnowledgeGraph()
}

function setGraphScope(scope) {
  graphScope.value = scope === "global" || !props.activePage?.id ? "global" : "local"
  void loadKnowledgeGraph()
}

function openNode(node) {
  emit(node.kind === "world_bible_page" ? "open-page" : "open-entity", node.id)
}

watch(() => props.activePage?.id, (next, previous) => {
  if (next === previous) return
  graphScope.value = next ? "local" : "global"
  void loadKnowledgeGraph()
})
onMounted(() => { void loadKnowledgeGraph() })
onBeforeUnmount(() => {
  disposed = true
  requestGeneration += 1
})
</script>
