<template>
  <details class="map-rehearsal">
    <summary>排演路线 <span>只看明确道路，帮助安排转场</span></summary>
    <p>这是临时排演，不改变地图和故事事实；待核对的连接不参与排演。</p>
    <div class="map-rehearsal-add"><label>添加起点、终点或经过地点<select v-model="nextStop" class="form-select"><option value="">请选择地点</option><option v-for="feature in places" :key="feature.id" :value="feature.id">{{ feature.label }}</option></select></label><button class="btn btn-sm" :disabled="!nextStop || stops.length >= 20 || stops.at(-1) === nextStop" @click="add">加入顺序</button><button v-if="stops.length" class="btn btn-sm" @click="$emit('update:stops', [])">清空排演</button></div>
    <ol><li v-for="(id, index) in stops" :key="index"><span>{{ places.find(item => item.id === id)?.label || '已移出的地点' }}</span><button class="btn btn-sm" :aria-label="'移出第 ' + (index + 1) + ' 个经过地点'" @click="$emit('update:stops', stops.filter((_, position) => position !== index))">移出</button></li></ol>
    <p role="status">{{ result.message }}</p>
    <details v-for="(leg, index) in result.legs" :key="index"><summary>{{ leg.label }}</summary><p v-if="!leg.sources.length">作者明确添加的道路关系，未附正文引文。</p><p v-for="(source, sourceIndex) in leg.sources" :key="sourceIndex">{{ source.quote || '已保留资料引用' }}<button v-if="source.kind === 'source_range'" class="btn btn-sm" @click="$emit('open-source', source)">打开第 {{ source.source_ref.chapter_index }} 章</button></p></details>
  </details>
</template>
<script setup>
import { computed, ref } from 'vue'
const props = defineProps({ document: { type: Object, required: true }, stops: { type: Array, required: true }, result: { type: Object, required: true } })
const emit = defineEmits(['update:stops', 'open-source'])
const nextStop = ref('')
const places = computed(() => props.document.features.filter(feature => ['location', 'landmark'].includes(feature.kind)))
function add() { emit('update:stops', [...props.stops, nextStop.value]); nextStop.value = '' }
</script>
<style scoped>
.map-rehearsal{border:1px solid var(--border);border-radius:var(--radius-md);padding:var(--space-3)}summary{min-height:44px;align-content:center;cursor:pointer}summary span,p{color:var(--text-secondary);font-size:var(--text-sm)}.map-rehearsal-add{display:flex;align-items:end;gap:var(--space-2);flex-wrap:wrap}label{display:grid;gap:var(--space-1);min-width:0}select{max-width:100%}li{display:flex;align-items:center;gap:var(--space-2);min-height:44px;flex-wrap:wrap}
</style>
