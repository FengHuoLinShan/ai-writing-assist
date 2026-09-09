<template>
  <div v-if="open" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <section ref="dialogRef" class="modal-content chapter-map-dialog" role="dialog" aria-modal="true" aria-labelledby="chapter-map-title" tabindex="-1">
      <header class="modal-header">
        <h3 id="chapter-map-title">{{ entityId ? '查看地点地图' : '本章地图' }}</h3>
        <button type="button" class="btn-icon" aria-label="关闭地图查找" @click="requestClose">×</button>
      </header>
      <div class="modal-body">
        <p id="chapter-map-description" class="muted">{{ entityId ? '查看这个地点已关联的地图。' : `查找第 ${chapter} 章来源中已标记的地点。` }}打开后可从地图返回正文。</p>
        <form class="chapter-map-search" @submit.prevent="loadLinks">
          <label for="chapter-map-search">地点或地图名称</label>
          <div class="chapter-map-search__row">
            <input id="chapter-map-search" v-model="query" class="form-input" type="search" maxlength="100" placeholder="输入名称缩小范围" aria-describedby="chapter-map-description">
            <button type="submit" class="btn" :disabled="loading">查找</button>
          </div>
          <label v-if="!entityId" class="chapter-map-search__scope">
            <input v-model="wholeProject" type="checkbox" @change="loadLinks">
            在整部作品的地图中查找
          </label>
        </form>
        <p v-if="loading" role="status">正在查找地图地点…</p>
        <div v-else-if="error" role="alert" class="chapter-map-feedback">
          <p>{{ error }}</p>
          <button type="button" class="btn" @click="loadLinks">重试</button>
        </div>
        <template v-else>
          <p v-if="truncated" role="status" class="chapter-map-feedback">当前只显示部分地图地点，可以输入更具体的名称缩小范围，或打开地图继续查看。</p>
          <ul v-if="items.length" class="chapter-map-results" aria-label="匹配的地图地点">
            <li v-for="item in items" :key="`${item.node_id}:${item.feature_id}`">
              <button type="button" class="btn chapter-map-result" @click="openMap(item)">
                <span><strong>{{ item.feature_label || '未命名地点' }}</strong><small>{{ item.node_title || '未命名地图' }}</small></span>
                <span aria-hidden="true">查看 →</span>
              </button>
            </li>
          </ul>
          <div v-else class="chapter-map-feedback">
            <p>{{ truncated ? '本次查找暂未匹配到地点。' : query.trim() ? '没有找到匹配的地点或地图。' : entityId ? '这个地点暂未关联地图。' : wholeProject ? '请输入地点或地图名称，查找整部作品的地图。' : '本章暂未关联地图地点。' }}</p>
            <p class="muted">可以打开地图，在地点详情中补充来源或关联已有地点，再回来继续写作。</p>
          </div>
        </template>
      </div>
      <footer class="modal-footer">
        <button type="button" class="btn" @click="openMap()">打开地图</button>
        <button type="button" class="btn btn-primary" @click="requestClose">继续写作</button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from "vue"
import { getApi, getAppState, getRouter } from "../../../bridge/index.js"
import { useModalDialog } from "../../../composables/useModalDialog.js"

const props = defineProps({
  open: Boolean,
  projectId: { type: String, required: true },
  chapter: { type: Number, default: null },
  entityId: { type: String, default: null },
})
const emit = defineEmits(["close"])
const requestClose = () => emit("close")
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open, requestClose })
const query = ref("")
const wholeProject = ref(false)
const items = ref([])
const truncated = ref(false)
const loading = ref(false)
const error = ref("")
let generation = 0

async function loadLinks() {
  const requestGeneration = ++generation
  const projectId = props.projectId
  const chapter = props.chapter
  const entityId = props.entityId
  items.value = []
  truncated.value = false
  error.value = ""
  if (wholeProject.value && !query.value.trim() && !entityId) { loading.value = false; return }
  if (!props.open || !projectId || !chapter) return
  loading.value = true
  const ownsRequest = () => requestGeneration === generation && props.open
    && props.projectId === projectId && props.chapter === chapter && props.entityId === entityId
    && getAppState()?.currentProjectId === projectId
  try {
    const result = await getApi().world.findMapLinks(projectId, {
      ...(entityId ? { entity_id: entityId } : wholeProject.value ? {} : { chapter_index: chapter }),
      ...(query.value.trim() ? { q: query.value.trim() } : {}),
    })
    if (!ownsRequest()) return
    items.value = result.items
    truncated.value = result.truncated
  } catch {
    if (ownsRequest()) error.value = "地图地点暂时无法加载，正文仍保留在写作台。请重试。"
  } finally {
    if (ownsRequest()) loading.value = false
  }
}

function openMap(item) {
  if (!props.open || getAppState()?.currentProjectId !== props.projectId) return
  const params = new URLSearchParams({ novel_id: props.projectId, from_chapter: String(props.chapter) })
  if (item) {
    params.set("node_id", item.node_id)
    params.set("feature_id", item.feature_id)
  }
  // Closing the lookup before navigating also leaves the editor available if its leave guard blocks.
  requestClose()
  getRouter().navigate("map", null, true, params)
}

watch(() => [props.open, props.projectId, props.chapter, props.entityId], () => {
  ++generation
  query.value = ""
  wholeProject.value = false
  loading.value = false
  items.value = []
  truncated.value = false
  error.value = ""
  if (props.open) void loadLinks()
}, { immediate: true })
onBeforeUnmount(() => { ++generation })
</script>

<style scoped>
.chapter-map-dialog { width: min(36rem, calc(100vw - 2rem)); }
.chapter-map-search { display: grid; gap: .5rem; margin-block: 1rem; }
.chapter-map-search__row { display: flex; gap: .5rem; }
.chapter-map-search__row input { flex: 1; min-width: 0; }
.chapter-map-search__scope { display: flex; align-items: center; gap: .5rem; min-height: 44px; }
.chapter-map-results { display: grid; gap: .5rem; list-style: none; padding: 0; }
.chapter-map-result { display: flex; justify-content: space-between; gap: 1rem; width: 100%; text-align: left; white-space: normal; }
.chapter-map-result > span:first-child { display: grid; gap: .25rem; min-width: 0; overflow-wrap: anywhere; }
.chapter-map-result > span:last-child { flex-shrink: 0; }
.chapter-map-result small { color: var(--text-secondary); }
.chapter-map-feedback { padding-block: .5rem; overflow-wrap: anywhere; }
.chapter-map-dialog button { min-height: 44px; }
.chapter-map-dialog .btn-icon { min-width: 44px; }
</style>
