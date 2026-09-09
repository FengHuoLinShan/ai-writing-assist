<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getAppState } from '../../bridge/index.js'
import { copyMap } from './mapStructureEditor.js'
const props = defineProps({ projectId: String, nodeId: String, entityId: String, entityName: String, nodes: { type: Array, default: () => [] }, disabled: Boolean })
const rows = ref([]), selected = ref([]), loading = ref(false), saving = ref(false), error = ref(''), receipt = ref('')
let epoch = 0, alive = true
function path(node) {
  const parts = [node.title], seen = new Set([node.id])
  let parent = props.nodes.find(item => item.id === node.parent_id)
  while (parent && !seen.has(parent.id)) { seen.add(parent.id); parts.unshift(parent.title); parent = props.nodes.find(item => item.id === parent.parent_id) }
  return parts.join(' / ')
}
async function load() {
  if (loading.value || saving.value || props.disabled) return
  const token = ++epoch, projectId = props.projectId
  loading.value = true; error.value = ''; rows.value = []; selected.value = []
  try {
    for (const node of props.nodes.filter(node => node.id !== props.nodeId)) {
      const value = await getApi().world.getNodeMap(projectId, node.id)
      if (!alive || token !== epoch || getAppState()?.currentProjectId !== projectId) return
      if (!value.revision) continue
      for (const feature of value.revision.document.features.filter(feature => ['location', 'landmark', 'area'].includes(feature.kind))) rows.value.push({ key: `${node.id}:${feature.id}`, nodeId: node.id, label: `${path(node)} · ${feature.label}`, feature, revision: value.revision, result: '' })
    }
  } catch (err) { if (alive && token === epoch) error.value = err.message || '读取对应图元失败，请重试' }
  finally { if (alive && token === epoch) loading.value = false }
}
function selectionDisabled(row) { return saving.value || row.feature.entity_id === props.entityId || (rows.value.some(other => other.nodeId === row.nodeId && selected.value.includes(other.key)) && !selected.value.includes(row.key)) }
async function apply() {
  if (saving.value || props.disabled || !props.entityId) return
  const projectId = props.projectId, entityId = props.entityId, token = epoch
  const chosen = rows.value.filter(row => selected.value.includes(row.key)).map(row => ({ row, document: copyMap(row.revision.document), base: row.revision.id }))
  saving.value = true; let succeeded = 0, failed = 0
  try {
    for (const item of chosen) {
      if (!alive || token !== epoch || getAppState()?.currentProjectId !== projectId || props.entityId !== entityId) return
      try {
        if (item.document.features.some(feature => feature.id !== item.row.feature.id && feature.entity_id === entityId)) throw new Error('此地图已有该地点标记，请使用已有标记')
        item.document.features.find(feature => feature.id === item.row.feature.id).entity_id = entityId
        const saved = await getApi().world.saveMapRevision(projectId, item.row.nodeId, { base_revision_id: item.base, document: item.document })
        if (!alive || token !== epoch) return
        item.row.revision = saved; item.row.feature = saved.document.features.find(feature => feature.id === item.row.feature.id)
        item.row.result = '已保存关联'; selected.value = selected.value.filter(key => key !== item.row.key); succeeded += 1
      } catch (err) { item.row.result = err.message || '保存失败，仍保留原关联'; failed += 1 }
    }
    receipt.value = `已保存 ${succeeded} 张地图，失败 ${failed} 张。${failed ? '失败项仍已选中。' : ''}`
  } finally { if (alive && token === epoch) saving.value = false }
}
watch(() => [props.projectId, props.nodeId, props.entityId], () => { epoch += 1; rows.value = []; selected.value = []; loading.value = false; saving.value = false; receipt.value = '' })
onBeforeUnmount(() => { alive = false; epoch += 1 })
</script>
<template>
  <details v-if="entityId" class="map-bind-across"><summary>关联其他地图中的对应地点</summary><p>将明确选中的图元关联到“{{ entityName }}”；每张地图选择一个图元，不按同名自动处理。</p><p v-if="disabled">请先保存当前地图。</p><button class="btn btn-sm" :disabled="disabled || loading || saving" @click="load">{{ loading ? '正在读取地图…' : '查找对应图元' }}</button><p v-if="error" role="alert">{{ error }}</p><label v-for="row in rows" :key="row.key"><input v-model="selected" type="checkbox" :value="row.key" :disabled="selectionDisabled(row)" />{{ row.label }} <strong v-if="row.feature.entity_id && row.feature.entity_id !== entityId">（将替换原关联）</strong><span v-if="row.result">{{ row.result }}</span></label><button v-if="rows.length" class="btn btn-primary" :disabled="disabled || saving || !selected.length" @click="apply">{{ saving ? '正在逐图保存…' : `确认关联所选 ${selected.length} 张地图` }}</button><p v-if="receipt" role="status">{{ receipt }}</p></details>
</template>
<style scoped>
.map-bind-across label{display:flex;gap:8px;align-items:center;flex-wrap:wrap;min-height:44px}.map-bind-across button{min-height:44px}.map-bind-across{overflow-wrap:anywhere}
</style>
