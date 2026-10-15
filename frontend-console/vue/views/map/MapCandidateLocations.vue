<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'

const props = defineProps({ projectId: { type: String, required: true }, locations: { type: Array, default: () => [] }, disabled: Boolean, truncated: Boolean })
const emit = defineEmits(['state', 'adopted', 'stale'])
const selected = ref([]), completed = ref([]), busy = ref(false), error = ref('')
const candidates = computed(() => props.locations.filter(item => ['candidate', 'draft'].includes(item.status) && !completed.value.includes(item.entity_id)))
const selectedCandidates = computed(() => candidates.value.filter(item => item.can_adopt !== false && selected.value.includes(item.entity_id)))
let epoch = 0, alive = true
watch([selected, busy], () => emit('state', { selected: selectedCandidates.value.length > 0, busy: busy.value }), { deep: true })
async function adopt() {
  const items = [...selectedCandidates.value], projectId = props.projectId, token = epoch
  if (props.disabled || busy.value || !items.length || items.length > 20) return
  busy.value = true; error.value = ''
  try {
    const confirmed = await confirmAsync(`在世界资料中正式采用：${items.map(item => item.name).join('、')}？会按原文前缀与当前作者权限重新核对。地图保存需要单独确认；未勾选的地点保留候选。`, '确认采用地点', { confirmAction: getConfirmAction() })
    if (!confirmed || !alive || epoch !== token) return
    for (const item of items) {
      await getApi().world.promoteEntity(item.entity_id, projectId, { expected_source_hash: item.source_hash })
      if (!alive || epoch !== token) return
      completed.value.push(item.entity_id)
    }
    selected.value = []
    busy.value = false
    emit('state', { selected: false, busy: false })
    emit('adopted')
  } catch (failure) {
    if (alive && epoch === token) {
      error.value = (failure.message || '地点采用未完成。') + ' 已成功的地点保留；请先到世界资料核对。地图操作需要单独确认，不能跳过原门禁。'
      if (failure.status === 409) {
        busy.value = false
        emit('state', { selected: false, busy: false })
        emit('stale', error.value)
      }
    }
  } finally { if (alive && epoch === token) busy.value = false }
}
watch(() => props.projectId, () => { epoch++; selected.value = []; completed.value = []; busy.value = false; error.value = '' })
onBeforeUnmount(() => { alive = false; epoch++; emit('state', { selected: false, busy: false }) })
</script>

<template>
  <section v-if="locations.length || truncated" class="map-candidate-locations" aria-label="可选同时采用候选地点">
    <strong>可选：同时采用绑定的候选地点</strong>
    <p>默认保留候选绑定。勾选后单独确认世界资料采用；地图操作与地点采用分别保存。</p>
    <div v-for="item in candidates" :key="item.entity_id"><label><input v-model="selected" type="checkbox" :value="item.entity_id" :disabled="disabled || busy || item.can_adopt === false">同时采用地点“{{ item.name }}”</label><p v-if="item.can_adopt === false" role="status">{{ item.block_reason || '当前无法采用，请到世界资料核对原文与权限。' }}</p></div>
    <p v-for="id in completed" :key="id">地点“{{ locations.find(item => item.entity_id === id)?.name }}”已采用。</p>
    <p v-if="truncated">另有候选地点未列出，请分批到世界资料核对。</p>
    <p v-if="selectedCandidates.length > 20" role="alert">每批最多采用 20 个地点，请减少选择。</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="selectedCandidates.length" class="btn" type="button" :disabled="disabled || busy || selectedCandidates.length > 20" @click="adopt">{{ busy ? '正在核对地点采用…' : '先确认采用所选 ' + selectedCandidates.length + ' 个地点' }}</button>
  </section>
</template>

<style scoped>
.map-candidate-locations { display: grid; gap: .5rem; margin-block: .75rem; }
label { display: flex; align-items: center; gap: .5rem; min-height: 44px; }
p { margin: 0; overflow-wrap: anywhere; }
</style>
