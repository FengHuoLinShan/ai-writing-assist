<template>
  <Teleport to="body">
  <div v-if="open" ref="overlayRef" class="modal-overlay map-source-overlay" @keydown="onKeydown" @focusin="onFocusin">
    <section ref="dialogRef" class="modal-content map-source-picker" role="dialog" aria-modal="true" aria-labelledby="map-source-title" tabindex="-1">
      <header class="modal-header">
        <h3 id="map-source-title">正文依据 · {{ feature.label }}</h3>
        <button type="button" class="btn-icon" aria-label="关闭正文依据" @click="requestClose">×</button>
      </header>
      <div class="modal-body">
        <p class="muted">选择已采用正文中的位置描述。关联只修改当前地图，保存地图后生效。</p>
        <template v-if="readingRef">
          <button type="button" class="btn btn-sm" @click="backToSearch">← 返回查找</button>
          <p><strong>第 {{ readingRef.chapter_index }} 章 · {{ preview?.title || readingTitle || '正文片段' }}</strong></p>
          <p v-if="reading" role="status">正在回读这段正文…</p>
          <div v-else-if="readError" role="alert"><p>{{ readError }}</p><button type="button" class="btn" @click="readSource(readingRef, readingTitle)">重试读取</button></div>
          <template v-else-if="preview">
            <p role="status">已回读所选正文版本 {{ readingRef.version_number }}，保存地图时会再次核对。{{ preview.index_fresh === false ? '资料索引仍待更新。' : '' }}</p>
            <p v-if="preview.degraded || preview.warnings?.length" class="muted">部分关联资料暂未完整返回；以下内容来自这段正文的直接回读。</p>
            <p class="muted">高亮部分是所选依据，周围文字仅供理解上下文。</p>
            <blockquote class="map-source-text"><span class="muted">{{ previewParts.before }}</span><mark>{{ previewParts.selected }}</mark><span class="muted">{{ previewParts.after }}</span></blockquote>
            <p v-if="alreadyLinked" role="status">这段正文已关联当前标记。</p>
            <p v-else-if="feature.sources.length >= 8" role="status">此标记已有 8 条依据，请先返回地图移出不需要的依据。</p>
            <button v-else type="button" class="btn btn-primary" @click="addSource">关联到“{{ feature.label }}”</button>
          </template>
        </template>
        <template v-else>
          <form class="map-source-search" @submit.prevent="search">
            <label for="map-source-query">地点名称或正文线索</label>
            <div><input id="map-source-query" v-model="query" class="form-input" type="search" maxlength="1000" required /><button type="submit" class="btn" :disabled="searching || !query.trim()">查找正文</button></div>
          </form>
          <p v-if="searching" role="status">正在查找正文…</p>
          <div v-else-if="searchError" role="alert"><p>{{ searchError }}</p><button type="button" class="btn" @click="search">重试查找</button></div>
          <template v-else>
            <p v-if="partial" role="status">当前只返回部分资料，请换更具体的线索继续查找，或在资料检索页检查整理进度。</p>
            <ul v-if="hits.length" class="map-source-hits" aria-label="正文搜索结果">
              <li v-for="(hit, index) in hits" :key="mapSourceRangeKey(hit.source_ref) || index">
                <strong>第 {{ hit.source_ref?.chapter_index || hit.chapter_index || '—' }} 章 · {{ hit.title || '正文片段' }}</strong>
                <p>{{ hit.snippet || '请回读正文查看内容。' }}</p>
                <p class="muted">{{ !mapSourceRangeKey(hit.source_ref) ? '正文版本引用不完整，请重新查找。' : hit.index_fresh === false ? '检索资料待更新，关联前将重新核对原文。' : '已采用正文 · 关联前需查看原文' }}</p>
                <button type="button" class="btn btn-sm" :disabled="!mapSourceRangeKey(hit.source_ref)" @click="readSource(hit.source_ref, hit.title)">查看原文</button>
              </li>
            </ul>
            <p v-else-if="searched" role="status">{{ partial ? '本次结果中暂未匹配到可关联正文。' : '没有找到可关联的已采用正文，请换一个地点名称或更具体的描述。' }}</p>
          </template>
        </template>
      </div>
      <footer class="modal-footer"><button type="button" class="btn" @click="requestClose">返回地图</button></footer>
    </section>
  </div>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getAppState } from '../../bridge/index.js'
import { useModalDialog } from '../../composables/useModalDialog.js'
import { copyMap, mapSourceRangeKey } from './mapStructureEditor.js'

const props = defineProps({
  open: Boolean,
  projectId: { type: String, required: true },
  feature: { type: Object, required: true },
  initialSource: { type: Object, default: null },
})
const emit = defineEmits(['close', 'add'])
const requestClose = () => emit('close')
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.open, requestClose })
const query = ref(''), hits = ref([]), searched = ref(false), searching = ref(false), searchError = ref(''), partial = ref(false)
const readingRef = ref(null), readingTitle = ref(''), preview = ref(null), reading = ref(false), readError = ref('')
let generation = 0
const alreadyLinked = computed(() => props.feature.sources.some(source => source.kind === 'source_range' && mapSourceRangeKey(source.source_ref) === mapSourceRangeKey(readingRef.value)))
const previewParts = computed(() => {
  const chars = Array.from(preview.value?.text || '')
  const start = preview.value?.highlight_start || 0, end = preview.value?.highlight_end || 0
  return { before: chars.slice(0, start).join(''), selected: chars.slice(start, end).join(''), after: chars.slice(end).join('') }
})
const active = token => props.open && token === generation && getAppState()?.currentProjectId === props.projectId

async function search() {
  const text = query.value.trim()
  if (!text || !props.open) return
  const token = ++generation
  searching.value = true; searched.value = true; searchError.value = ''; hits.value = []; partial.value = false
  try {
    const result = await getApi().context.searchEvidence({ novel_id: props.projectId, query: text, content_mode: 'canonical', visibility: { mode: 'author' }, scopes: ['manuscript'], include_pending_objects: false, top_k: 20 })
    if (!active(token)) return
    hits.value = result.hits.filter(hit => hit.kind === 'manuscript' && (!hit.source_ref || hit.source_ref.content_mode === 'canonical'))
    partial.value = Boolean(result.degraded || result.warnings?.length || result.missing_chapters?.length || result.total > result.hits.length)
  } catch {
    if (active(token)) searchError.value = '正文暂时无法查找，地图编辑仍保留。请重试。'
  } finally { if (active(token)) searching.value = false }
}

async function readSource(sourceRef, title = '') {
  if (!props.open) return
  const token = ++generation
  readingRef.value = copyMap(sourceRef || {}); readingTitle.value = title; preview.value = null; readError.value = ''; reading.value = true
  if (!mapSourceRangeKey(sourceRef)) {
    reading.value = false; readError.value = '这段正文缺少完整的版本引用，请返回查找重新选择。'; return
  }
  try {
    const result = await getApi().context.readEvidence({ novel_id: props.projectId, content_mode: 'canonical', visibility: { mode: 'author' }, source_ref: sourceRef, before: 0, after: 0 })
    if (!active(token)) return
    const chars = Array.from(result.text || ''), start = result.highlight_start, end = result.highlight_end
    if (mapSourceRangeKey(result.source_ref) !== mapSourceRangeKey(sourceRef)
      || !Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end > chars.length
      || !chars.slice(start, end).join('').trim()) throw Object.assign(new Error('source changed'), { status: 409 })
    preview.value = result
  } catch (error) {
    if (active(token)) readError.value = [400, 404, 409].includes(Number(error?.status))
      ? '这段正文的版本已变化或不可用，请返回查找当前正文。原有地图依据仍保留，未自动替换。'
      : '原文暂时无法读取，当前地图没有变化。请重试。'
  } finally { if (active(token)) reading.value = false }
}

function backToSearch() { ++generation; readingRef.value = null; reading.value = false; preview.value = null; readError.value = '' }
function addSource() {
  if (!active(generation) || reading.value || !preview.value || alreadyLinked.value || props.feature.sources.length >= 8) return
  const ref = preview.value.source_ref
  emit('add', { kind: 'source_range', id: ref.draft_id, source_hash: ref.source_hash, source_ref: copyMap(ref), quote: Array.from(previewParts.value.selected).slice(0, 1000).join('') })
}
watch([() => props.open, () => props.projectId, () => props.feature.id, () => props.initialSource], () => {
  ++generation; query.value = props.feature.label; hits.value = []; searched.value = false; searching.value = false; searchError.value = ''; partial.value = false
  readingRef.value = null; reading.value = false; preview.value = null; readError.value = ''
  if (props.open && props.initialSource) void readSource(props.initialSource.source_ref, '')
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { ++generation })
</script>

<style scoped>
.map-source-overlay{justify-content:flex-end;align-items:stretch}.map-source-overlay>.map-source-picker{margin:0;max-height:100dvh;height:100dvh;width:min(680px,100vw);max-width:100vw;overflow:hidden;border-radius:var(--radius-md) 0 0 var(--radius-md)}
.map-source-picker>.modal-header,.map-source-picker>.modal-footer{flex-shrink:0}.map-source-picker>.modal-body{min-height:0}
.map-source-picker { width: min(44rem, calc(100vw - 2rem)); }
.map-source-picker h3, .map-source-picker p { overflow-wrap: anywhere; }
.map-source-search { display: grid; gap: var(--space-2); margin-block: var(--space-4); }
.map-source-search > div { display: flex; gap: var(--space-2); }
.map-source-search input { min-width: 0; flex: 1; }
.map-source-search button { flex-shrink: 0; }
.map-source-hits { list-style: none; padding: 0; display: grid; gap: var(--space-3); }
.map-source-hits li { border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--space-3); overflow-wrap: anywhere; }
.map-source-text { margin: var(--space-3) 0; padding: var(--space-3); border-left: 3px solid var(--border); white-space: pre-wrap; overflow-wrap: anywhere; }
.map-source-text mark { background: color-mix(in srgb, var(--accent) 16%, var(--bg-panel)); color: var(--text-primary); }
.map-source-picker button { min-height: 44px; white-space: normal; }
.map-source-picker .btn-icon { min-width: 44px; }
</style>
