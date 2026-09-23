<template>
  <details ref="panel" class="map-scene-panel" @toggle="opened">
    <summary>按场景查看人物位置</summary>
    <p class="map-caption">作者视图 · 最后一次出现不代表此刻仍在原处。仅核对已有事件，不生成新设定。</p>
    <label>看到哪个场景
      <select v-model="sceneId" class="form-select" @change="loadContext">
        <option value="">请选择场景</option>
        <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || `场景 ${scene.scene_index + 1}` }}</option>
      </select>
    </label>
    <button class="btn btn-sm" :disabled="busy || !sceneId" @click="loadContext">刷新人物位置</button>
    <p v-if="busy" role="status">正在读取场景记录…</p>
    <p v-if="error" role="alert">{{ error }} <button class="btn btn-sm" @click="loadScenes">重新读取</button></p>
    <p v-else-if="loaded && !scenes.length">还没有可回看的场景。整理场景后可在这里核对人物位置。</p>
    <template v-if="context">
      <p v-if="context.freshness === 'partial'" role="status">部分地图来源已变化，相关人物只列文字，等待核对。</p>
      <p v-if="!context.presence_items.length">本书还没有可展示的人物位置。</p>
      <ul class="map-presence-list">
        <li v-for="item in locatedPeople" :key="item.character_id">
          <strong>{{ item.character_name }}</strong>
          <span>{{ presenceLabel(item) }}</span>
          <small v-if="item.source_receipt.source === 'agent_curation'">代理精修</small>
          <button v-if="item.feature_id" class="btn btn-sm" @click="$emit('locate', item.feature_id)">在地图上查看</button>
          <button v-if="item.source_receipt.chapter_index" class="btn btn-sm" @click="openSource(item.source_receipt)">查看第 {{ item.source_receipt.chapter_index }} 章依据</button>
        </li>
      </ul>
      <details v-if="unknownPeople.length">
        <summary>{{ unknownPeople.length }} 名人物位置未确定</summary>
        <p class="map-caption">{{ unknownPeople.map(item => item.character_name).join('、') }}。未找到这个截止点前的明确位置依据，不在地图上推定位置。</p>
      </details>
      <details v-if="context.history.length"><summary>出现记录与未知行程</summary>
        <ol><li v-for="(item, index) in context.history" :key="index">{{ item.character_name }} · 场景 {{ item.scene_index + 1 }} · {{ item.location }}</li></ol>
        <p v-for="(route, index) in context.routes" :key="index">{{ characterName(route.character_id) }}：{{ route.from_location }} → {{ route.to_location }} · {{ route.status === 'unknown' ? '中间路线未知' : '有移动事件依据；距离与耗时未核定' }}</p>
      </details>
      <p v-for="note in context.omissions" :key="note" class="map-caption">{{ note }}</p>
      <p class="map-caption">当前不展示物品保管、人物所知或读者视角。</p>
    </template>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi } from '../../bridge/index.js'
const props = defineProps({ projectId: { type: String, required: true }, nodeId: { type: String, required: true }, revisionId: { type: String, required: true } })
const emit = defineEmits(['locate', 'open-source'])
const panel = ref(null)
const scenes = ref([]), sceneId = ref(''), context = ref(null), busy = ref(false), loaded = ref(false), error = ref('')
const locatedPeople = computed(() => (context.value?.presence_items || []).filter(item => item.presence_kind !== 'unknown'))
const unknownPeople = computed(() => (context.value?.presence_items || []).filter(item => item.presence_kind === 'unknown'))
let epoch = 0
const api = () => getApi()
async function loadScenes() {
  const token = ++epoch
  busy.value = true; error.value = ''; context.value = null
  try {
    const result = await api().outline.listScenesOrdered(props.projectId)
    if (token !== epoch) return
    scenes.value = result.filter(scene => ['draft', 'canonical'].includes(scene.status)); loaded.value = true
    if (!scenes.value.some(scene => scene.id === sceneId.value)) sceneId.value = ''
  } catch (err) { if (token === epoch) error.value = err.message || '暂时无法读取场景。' }
  finally { if (token === epoch) busy.value = false }
}
async function loadContext() {
  const token = ++epoch
  context.value = null; error.value = ''; busy.value = Boolean(sceneId.value)
  if (!sceneId.value) return
  try {
    const result = await api().world.getMapSceneContext(props.projectId, props.nodeId, sceneId.value)
    if (token !== epoch) return
    if (result.map_revision !== props.revisionId) { error.value = '地图已有新版本，请刷新地图后再查看人物位置。'; return }
    context.value = result
  } catch (err) { if (token === epoch) error.value = err.message || '暂时无法读取位置；旧结果已收起。' }
  finally { if (token === epoch) busy.value = false }
}
function opened(event) { if (event.target === event.currentTarget && event.target.open && !loaded.value) void loadScenes() }
function presenceLabel(item) {
  if (item.presence_kind === 'unknown') return '位置未确定'
  return `${item.presence_kind === 'confirmed_in_scene' ? '本场出现于' : '最后出现于'}${item.location}${item.presence_kind === 'last_observed' ? `（场景 ${item.scene_index + 1}）` : ''}`
}
function characterName(id) { return context.value.presence_items.find(item => item.character_id === id)?.character_name || '人物' }
function openSource(receipt) { emit('open-source', { source_ref: { chapter_index: receipt.chapter_index } }) }
watch(() => [props.projectId, props.nodeId, props.revisionId], () => { epoch++; scenes.value = []; sceneId.value = ''; context.value = null; loaded.value = busy.value = false; error.value = ''; if (panel.value?.open) void loadScenes() })
onBeforeUnmount(() => { epoch++ })
</script>

<style scoped>
.map-scene-panel { padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); }
.map-scene-panel summary { cursor: pointer; min-height: 44px; font-weight: 600; }
.map-scene-panel label { display: grid; gap: .5rem; margin-block: .75rem; }
.map-scene-panel select { width: 100%; max-width: 32rem; }
.map-presence-list { list-style: none; padding: 0; }
.map-presence-list li { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; padding-block: .6rem; border-bottom: 1px solid var(--border); }
.map-presence-list span { flex: 1 1 12rem; overflow-wrap: anywhere; }
.map-scene-panel button { min-height: 44px; }
.map-caption { color: var(--text-secondary); }
</style>
