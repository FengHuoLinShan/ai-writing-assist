<template>
  <section class="panel world-bible-graph" aria-labelledby="world-bible-graph-title">
    <div class="world-bible-panel__header">
      <div>
        <h2 id="world-bible-graph-title">关联图</h2>
        <div class="world-bible-page-meta">查看当前资料与谁有关联，以及具体关系。扩大范围可查看间接关联。</div>
      </div>
      <div class="world-bible-panel__actions" role="group" aria-label="关联图范围">
        <button class="btn btn-sm" data-action="bible-graph-depth-1" :disabled="!hasPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 1" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 1 }" @click="setGraphDepth(1)">当前资料 · 直接关联</button>
        <button class="btn btn-sm" data-action="bible-graph-depth-2" :disabled="!hasPageRoot" :aria-pressed="graphScope === 'local' && graphDepth === 2" :class="{ 'btn-primary': graphScope === 'local' && graphDepth === 2 }" @click="setGraphDepth(2)">再看一层关联</button>
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
      <details open class="world-bible-graph__visual">
        <summary>关系示意图</summary>
        <label>缩放 <input v-model.number="zoom" type="range" min="0.1" max="2" step="0.05" /></label>
        <button class="btn btn-sm" @click="fitGraph">适合画布</button>
        <div ref="graphViewport" style="overflow:auto;max-height:65vh">
        <svg v-if="graphLayout.nodes.length" class="world-bible-graph__svg" :viewBox="`0 0 ${graphLayout.width} ${graphLayout.height}`" :style="{ width: `${graphLayout.width * zoom}px`, height: `${graphLayout.height * zoom}px` }" role="img" aria-label="世界书关联示意图">
          <line v-for="edge in graphLayout.edges" :key="edge.id" :x1="graphLayout.positions[edge.source_id].x" :y1="graphLayout.positions[edge.source_id].y" :x2="graphLayout.positions[edge.target_id].x" :y2="graphLayout.positions[edge.target_id].y" />
          <g v-for="node in graphLayout.nodes" :key="node.id" :transform="`translate(${graphLayout.positions[node.id].x}, ${graphLayout.positions[node.id].y})`"><title>{{ node.label }}</title><circle r="22" /><text y="4">{{ node.label?.slice(0, 8) }}</text></g>
        </svg>
        </div>
      </details>
      <p v-if="knowledgeGraph.nodes.length > graphLayout.nodes.length">图中显示前 {{ graphLayout.nodes.length }} 项，完整关联可在下方列表查看。</p>
      <ul class="world-bible-graph__list" aria-label="关联图节点列表">
        <li v-for="node in knowledgeGraph.nodes || []" :key="node.id">
          <button class="btn world-bible-graph__node" :data-graph-node-kind="node.kind" :data-graph-node-id="node.id" @click="openNode(node)">
            <strong>{{ node.label || '未命名资料' }}</strong><span>{{ node.kind === 'world_bible_page' ? '世界书页' : '世界对象' }}</span>
          </button>
        </li>
      </ul>
      <label class="world-bible-graph__filter">
        <input type="checkbox" v-model="dependencyOnly" data-field="graph-dependency-only" />
        只看已声明依赖（依赖/派生/冲突）
      </label>
      <ul v-if="visibleGraphEdges.length" class="world-bible-graph__edges" aria-label="关联图关联列表" data-section="graph-edges">
        <li v-for="edge in visibleGraphEdges" :key="edge.id" :class="`is-dependency-${edge.dependencyKind}`">
          {{ edge.sourceLabel }} → {{ edge.kindLabel }}{{ edge.via_relation_id ? '（经关系）' : '' }}<span v-if="edge.dependencyBadge" class="world-bible-graph__badge" :data-dependency="edge.dependencyKind">{{ edge.dependencyBadge }}</span> → {{ edge.targetLabel }}
          <button v-if="edge.kind === 'entity_relation'" class="btn btn-sm" @click="openRelation(edge)">查看关系依据</button>
        </li>
      </ul>
      <section v-if="relationLoading || relationDetail || relationError" class="card" aria-label="关系依据">
        <p v-if="relationLoading" role="status">正在读取关系…</p><p v-else-if="relationError" role="alert">{{ relationError }}</p>
        <template v-else><h3>{{ relationDetail.source_name }} → {{ detailTypeLabel(typeCatalog, 'relation', relationDetail.relation_type) }} → {{ relationDetail.target_name }}</h3><p>{{ relationDetail.description || '尚无描述' }}</p><blockquote>{{ relationDetail.quote || '尚未记录原文引用' }}</blockquote></template>
        <button class="btn btn-sm" @click="closeRelation">关闭关系依据</button>
      </section>

    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"
import { detailTypeLabel } from "../logic/worldTypeCatalog.js"
import { knowledgeGraphLayout } from "./worldBiblePresentation.js"

const props = defineProps({
  projectId: { type: String, required: true },
  activePage: { type: Object, default: null },
  activeEntityId: { type: String, default: null },
  typeCatalog: { type: Object, default: () => ({}) },
})
const emit = defineEmits(["open-page", "open-entity"])
const api = getApi()
const knowledgeGraph = ref(null)
const graphLoading = ref(false)
const graphError = ref(null)
const rootId = computed(() => props.activeEntityId || props.activePage?.id || null)
const graphScope = ref(rootId.value ? "local" : "global")
const graphDepth = ref(1)
let requestGeneration = 0
let disposed = false

const hasPageRoot = computed(() => Boolean(rootId.value))
const graphLayout = computed(() => knowledgeGraphLayout(knowledgeGraph.value?.nodes || [], knowledgeGraph.value?.edges || [], 40, rootId.value))
const partialDetails = computed(() => {
  const result = knowledgeGraph.value || {}
  const counts = Object.entries(result.omitted_counts || {}).filter(([, value]) => Number(value) > 0)
  const reasons = result.truncated ? (result.truncation_reasons || []) : []
  return [...reasons, ...counts.map(([key, value]) => `${key} ${value}`)]
})
const relationDetail = ref(null), relationLoading = ref(false), relationError = ref("")
let relationEpoch = 0
function closeRelation() { relationEpoch += 1; relationDetail.value = null; relationError.value = ""; relationLoading.value = false }
async function openRelation(edge) {
  const token = ++relationEpoch
  relationLoading.value = true; relationError.value = ""; relationDetail.value = null
  try {
    const result = await api.world.getEntityRelations(edge.source_id, props.projectId)
    if (disposed || token !== relationEpoch) return
    relationDetail.value = (result.items || []).find(item => item.id === edge.id) || null
    if (!relationDetail.value) relationError.value = "该关系已变化，请刷新关联图后重试。"
  } catch (error) { if (!disposed && token === relationEpoch) relationError.value = error.message || "关系读取失败" }
  finally { if (!disposed && token === relationEpoch) relationLoading.value = false }
}
const zoom = ref(1), graphViewport = ref(null)
function fitGraph() {
  const width = graphViewport.value?.clientWidth
  if (width) zoom.value = Math.max(0.1, Math.min(1, Math.floor(width / graphLayout.value.width * 20) / 20))
}
const dependencyOnly = ref(false)
const dependencyBadges = { requires: "依赖", derives: "派生", conflicts: "冲突" }
const graphEdges = computed(() => {
  const labels = new Map((knowledgeGraph.value?.nodes || []).map((node) => [node.id, node.label || "未命名资料"]))
  const kinds = { page_reference: "页面引用", page_entity_reference: "页面关联对象", entity_relation: "对象关系" }
  return (knowledgeGraph.value?.edges || []).map((edge) => {
    const dependencyKind = dependencyBadges[edge.dependency_relation] ? edge.dependency_relation : "informs"
    return {
      ...edge,
      sourceLabel: labels.get(edge.source_id) || "不可用来源",
      targetLabel: labels.get(edge.target_id) || "不可用目标",
      kindLabel: edge.relation_type ? detailTypeLabel(props.typeCatalog, "relation", edge.relation_type) : kinds[edge.kind] || "关联",
      dependencyKind,
      dependencyBadge: dependencyBadges[edge.dependency_relation] || "",
    }
  })
})
const visibleGraphEdges = computed(() => dependencyOnly.value
  ? graphEdges.value.filter((edge) => edge.dependencyKind !== "informs")
  : graphEdges.value)

function graphParams() {
  if (!rootId.value) return { novel_id: props.projectId, scope: "global" }
  return {
    novel_id: props.projectId,
    scope: graphScope.value,
    root_type: props.activeEntityId ? "core_entity" : "world_bible_page",
    root_id: rootId.value,
    depth: graphDepth.value,
  }
}

async function loadKnowledgeGraph() {
  if (!rootId.value) graphScope.value = "global"
  const owner = { projectId: props.projectId, pageId: rootId.value || null }
  const request = ++requestGeneration
  graphLoading.value = true
  graphError.value = null
  try {
    const result = await api.world.getKnowledgeGraph(graphParams())
    if (disposed || request !== requestGeneration || owner.projectId !== props.projectId || owner.pageId !== (rootId.value || null)) return false
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
  if (!rootId.value) {
    graphScope.value = "global"
  } else {
    graphDepth.value = depth === 2 ? 2 : 1
    graphScope.value = "local"
  }
  void loadKnowledgeGraph()
}

function setGraphScope(scope) {
  graphScope.value = scope === "global" || !rootId.value ? "global" : "local"
  void loadKnowledgeGraph()
}

function openNode(node) {
  emit(node.kind === "world_bible_page" ? "open-page" : "open-entity", node.id)
}

watch(() => rootId.value, (next, previous) => {
  if (next === previous) return
  closeRelation()
  zoom.value = 1
  graphScope.value = next ? "local" : "global"
  void loadKnowledgeGraph()
})
onMounted(() => { void loadKnowledgeGraph() })
onBeforeUnmount(() => {
  disposed = true
  requestGeneration += 1
})
</script>
