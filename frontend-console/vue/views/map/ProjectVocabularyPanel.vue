<template>
  <details class="card vocabulary" @toggle="onToggle">
    <summary>本作品的空间类型<span v-if="loaded"> · {{ total }} 项</span></summary>
    <p>为这部作品命名空间、图元、关系与旅行方式。已有地图保留原类型版本；改动不会自动改写已保存地图。</p>
    <p v-if="error" class="alert alert-warning" role="alert">{{ error }} <button class="btn btn-sm" :disabled="busy" @click="load">重新读取</button></p>
    <p v-if="message" role="status">{{ message }}</p>
    <p v-if="loading" role="status">正在读取项目类型…</p>
    <template v-if="loaded">
      <fieldset :disabled="locked" class="vocabulary-presets">
        <legend>用题材预设起步（可以混搭）</legend>
        <label v-for="(label, key) in presets" :key="key"><input v-model="selectedPresets" type="checkbox" :value="key" />{{ label }}</label>
        <button class="btn btn-sm" :disabled="!selectedPresets.length || dirty" @click="applyPresets">添加预设</button>
      </fieldset>
      <div class="vocabulary-bar">
        <label>种类<select v-model="filter" class="form-select"><option value="">全部种类</option><option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
        <label>查找类型<input v-model="query" class="form-input" placeholder="名称或别名" /></label>
        <button class="btn btn-sm" :disabled="locked" @click="beginNew">新增类型</button>
      </div>
      <p v-if="omitted" role="status">当前只读取了 {{ total - omitted }} / {{ total }} 项，尚有 {{ omitted }} 项未显示；以下筛选仅针对已读取内容。</p>
      <div class="vocabulary-body">
        <ul class="vocabulary-list" aria-label="项目类型列表">
          <li v-for="term in filtered" :key="term.id"><button type="button" :disabled="locked" :aria-pressed="selected?.id === term.id" @click="select(term)"><strong>{{ term.name }}</strong><span>{{ kinds[term.kind] }} · {{ statuses[term.status] }}</span><small>{{ origins[term.source] }} · 版本 {{ term.revision_number }}</small></button></li>
          <li v-if="!filtered.length">{{ total ? '没有匹配的已读取类型。' : '还没有项目类型，可添加预设或自定义。' }}</li>
        </ul>
        <form v-if="editor" class="vocabulary-editor" @submit.prevent="save">
          <fieldset :disabled="locked || readOnly">
            <legend>{{ selected ? '编辑：' + selected.name : '新增类型' }}</legend>
            <label>类型种类<select v-model="editor.kind" class="form-select" :disabled="Boolean(selected)"><option v-for="(label, key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
            <label>名称<input v-model="editor.name" class="form-input" maxlength="120" required /></label>
            <label>别名（每行一个，最多 24 个）<textarea v-model="editor.aliasText" class="form-textarea" rows="2" /></label>
            <label>含义说明<textarea v-model="editor.description" class="form-textarea" maxlength="1000" rows="3" /></label>
            <details><summary>计算特性</summary><p>没有特性的类型只作为文字使用。上下、移动等声明尚不代表完整时空计算。</p>
              <fieldset v-for="group in traitGroups" :key="group.key"><legend>{{ group.label }}</legend><label v-for="(label, key) in group.options" :key="key"><input v-model="editor.traits[group.key]" type="checkbox" :value="key" />{{ label }}</label></fieldset>
            </details>
            <button class="btn btn-primary" :disabled="!dirty || !editor.name.trim()">{{ busy ? '正在保存…' : '保存类型' }}</button>
          </fieldset>
          <div class="vocabulary-bar">
            <button type="button" class="btn btn-sm" :disabled="locked" @click="cancelEdit">收起编辑</button>
            <button v-if="selected?.status === 'archived'" type="button" class="btn btn-sm" :disabled="locked" @click="restore">恢复类型</button>
            <button v-else-if="selected && !readOnly" type="button" class="btn btn-sm" :disabled="locked || dirty" @click="archive">归档类型</button>
          </div>
          <p v-if="readOnly">{{ selected.status === 'merged' ? '此类型已合并，保留原身份与历史引用。请编辑合并后的类型。' : '此类型已归档，旧引用仍保留，恢复后可以继续编辑。' }}</p>
          <details v-if="selected && !readOnly"><summary>合并或拆分</summary>
            <p>先保存当前编辑，再处理类型身份。历史地图仍保留固定修订。</p>
            <label>合并到<select v-model="mergeTarget" class="form-select" :disabled="locked || dirty"><option value="">选择同种类类型</option><option v-for="term in mergeChoices" :key="term.id" :value="term.id">{{ term.name }}</option></select></label>
            <button type="button" class="btn btn-sm" :disabled="locked || dirty || !mergeTarget" @click="merge">预览并确认合并</button>
            <label>拆出的新类型名称<input v-model="splitName" class="form-input" maxlength="120" :disabled="locked || dirty" /></label>
            <button type="button" class="btn btn-sm" :disabled="locked || dirty || !splitName.trim()" @click="split">保留当前类型并拆出新类型</button>
          </details>
        </form>
      </div>
    </template>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'

const props = defineProps({ projectId: { type: String, required: true }, disabled: Boolean })
const emit = defineEmits(['state', 'changed'])
const api = getApi()
const kinds = { space: '空间', level: '层级', feature: '图元', relation: '空间关系', transport: '交通方式', traveler: '旅行者类别', access_condition: '通行条件', dossier_facing: '档案面向', faction_form: '势力形态', territory_control: '控制方式' }
const statuses = { active: '启用', emerging: '涌现中', archived: '已归档', merged: '已合并' }
const origins = { author: '作者定义', model: '模型提议', preset: '题材预设' }
const presets = { xianxia: '修仙', fantasy: '西幻', urban: '都市', science_fiction: '科幻', mystery: '悬疑' }
const traitGroups = [
  { key: 'geometry', label: '几何', options: { point: '点', line: '线', area: '面', none: '无几何' } },
  { key: 'containment', label: '容纳', options: { can_contain: '可容纳', independent_space: '独立空间' } },
  { key: 'connection', label: '连接', options: { traversable: '可通行', directed: '有向', cross_space: '跨空间', distance_constrained: '受距离约束' } },
  { key: 'orientation', label: '方位', options: { compass: '方位有效', vertical: '上下关系' } },
  { key: 'other', label: '其他', options: { movable: '可移动', qualitative_distance: '定性远近' } },
]
const items = ref([]), total = ref(0), omitted = ref(0), loaded = ref(false), loading = ref(false), busy = ref(false)
const error = ref(''), message = ref(''), query = ref(''), filter = ref(''), selectedPresets = ref([])
const selected = ref(null), editor = ref(null), original = ref(''), mergeTarget = ref(''), splitName = ref('')
let active = true, readSequence = 0
const dirty = computed(() => editor.value !== null && JSON.stringify(editor.value) !== original.value)
const locked = computed(() => props.disabled || busy.value || loading.value)
const readOnly = computed(() => ['archived', 'merged'].includes(selected.value?.status))
const filtered = computed(() => items.value.filter(term => (!filter.value || term.kind === filter.value) && [term.name, ...term.aliases].some(text => text.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))))
const mergeChoices = computed(() => items.value.filter(term => term.id !== selected.value?.id && term.kind === selected.value?.kind && !['merged', 'archived'].includes(term.status)))
watch([dirty, busy], () => emit('state', { dirty: dirty.value, busy: busy.value }), { immediate: true })
onBeforeUnmount(() => { active = false; readSequence++ })
function fields(value) {
  return { name: value.name, description: value.description, aliases: value.aliasText.split('\n').map(text => text.trim()).filter(Boolean), traits: JSON.parse(JSON.stringify(value.traits)) }
}
function edit(term) {
  selected.value = term
  editor.value = { kind: term?.kind || filter.value || 'feature', name: term?.name || '', description: term?.description || '', aliasText: (term?.aliases || []).join('\n'), traits: Object.fromEntries(traitGroups.map(group => [group.key, [...(term?.traits?.[group.key] || [])]])) }
  original.value = JSON.stringify(editor.value)
  mergeTarget.value = ''; splitName.value = ''
}
async function discard() {
  return !dirty.value || await confirmAsync('类型编辑尚未保存，放弃这次编辑吗？', '确认放弃', { confirmAction: getConfirmAction() })
}
async function select(term) { if (!locked.value && await discard()) edit(term) }
async function beginNew() { if (!locked.value && await discard()) edit(null) }
async function cancelEdit() { if (await discard()) { editor.value = null; selected.value = null } }
async function load() {
  if (loading.value || busy.value) return
  const sequence = ++readSequence, projectId = props.projectId
  loading.value = true; error.value = ''
  try {
    const result = await api.world.listProjectVocabulary(projectId)
    if (!active || sequence !== readSequence || props.projectId !== projectId) return
    items.value = result.items; total.value = result.total_count; omitted.value = result.omitted_count; loaded.value = true
  } catch (failure) { if (active && sequence === readSequence) error.value = failure.message || '类型读取失败，请重试。' }
  finally { if (active && sequence === readSequence) loading.value = false }
}
function onToggle(event) { if (event.target.open && !loaded.value) load() }
async function run(action, success) {
  if (!active || locked.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const result = await action()
    if (!active) return
    if (result?.id) edit(result)
    message.value = typeof success === 'function' ? success(result) : success
    emit('changed')
  } catch (failure) { if (active) error.value = failure.status === 409 ? '类型版本已变化，编辑内容已保留。重新读取后，请核对列表中的当前版本；复制需要的修改，再选择该类型重新编辑。' : failure.message || '操作未完成，编辑内容已保留。' }
  finally { if (active) busy.value = false }
  if (active && !error.value) await load()
}
async function save() {
  if (!editor.value || !dirty.value || readOnly.value) return
  const payload = fields(editor.value), term = selected.value
  if (payload.aliases.length > 24) { error.value = '别名最多 24 个，请先精简。'; return }
  await run(() => term ? api.world.updateVocabularyTerm(props.projectId, term.id, { ...payload, expected_revision_id: term.revision_id }) : api.world.createVocabularyTerm(props.projectId, { ...payload, kind: editor.value.kind }), '类型已保存。已有地图的类型版本保持不变。')
}
async function archive() {
  const term = selected.value
  if (!term || !await confirmAsync(`归档“${term.name}”？历史引用会保留，计算将暂停使用此类型。`, '确认归档', { confirmAction: getConfirmAction() })) return
  await run(() => api.world.archiveVocabularyTerm(props.projectId, term.id, { expected_revision_id: term.revision_id, confirmed: true }), '类型已归档，可以恢复。')
}
async function restore() {
  const term = selected.value
  await run(() => api.world.restoreVocabularyTerm(props.projectId, term.id, { expected_revision_id: term.revision_id }), '类型已恢复。')
}
async function merge() {
  const source = selected.value, target = mergeChoices.value.find(term => term.id === mergeTarget.value)
  if (!source || !target || !await confirmAsync(`将“${source.name}”合并到“${target.name}”？来源名称会保留为别名，旧身份指向目标。`, '确认合并', { confirmAction: getConfirmAction() })) return
  await run(() => api.world.mergeVocabularyTerms(props.projectId, { target_id: target.id, source_ids: [source.id], expected_revision_ids: { [target.id]: target.revision_id, [source.id]: source.revision_id }, confirmed: true }), '类型已合并，历史引用仍保留。')
}
async function split() {
  const term = selected.value, name = splitName.value.trim()
  if (!term || !name) return
  await run(async () => (await api.world.splitVocabularyTerm(props.projectId, term.id, { expected_revision_id: term.revision_id, retained: fields(editor.value), split_off: { name, description: '', aliases: [], traits: fields(editor.value).traits } })).split_off, '已保留原类型并创建拆出的类型，请继续完善新类型说明。')
}
async function applyPresets() {
  await run(() => api.world.applyVocabularyPresets(props.projectId, { preset_ids: [...selectedPresets.value] }), result => `预设已处理：新增 ${result.applied} 项，已添加 ${result.already_applied} 项，重名跳过 ${result.duplicate_skipped} 项。`)
}
</script>

<style scoped>
.vocabulary { margin-block: 1rem; padding: 1rem; }
.vocabulary summary { cursor: pointer; font-weight: 600; }
.vocabulary p, .vocabulary small { color: var(--text-secondary); }
.vocabulary-bar, .vocabulary-presets { display: flex; align-items: end; gap: .75rem; flex-wrap: wrap; }
.vocabulary-presets { border: 0; padding: .5rem 0; margin: 0; }
.vocabulary-presets label { display: inline-flex; align-items: center; gap: .35rem; margin-right: .75rem; min-height: 2.5rem; }
.vocabulary-bar label { flex: 1 1 10rem; }
.vocabulary-body { display: grid; grid-template-columns: minmax(11rem, 1fr) minmax(0, 2fr); gap: 1rem; margin-top: 1rem; }
.vocabulary-list { list-style: none; padding: 0; margin: 0; max-height: 35rem; overflow-y: auto; }
.vocabulary-list button { width: 100%; text-align: left; padding: .75rem; color: var(--text-primary); font: inherit; background: transparent; border: 1px solid var(--border); border-radius: .4rem; margin-bottom: .4rem; overflow-wrap: anywhere; }
.vocabulary-list button[aria-pressed="true"] { border-color: var(--accent); background: var(--bg-panel); }
.vocabulary-list span, .vocabulary-list small, .vocabulary-editor > fieldset > label { display: block; }
.vocabulary-editor fieldset { min-width: 0; border: 0; padding: .5rem 0; margin: 0; }
.vocabulary-editor label { margin-bottom: .7rem; }
.vocabulary-editor details fieldset label { display: inline-flex; gap: .35rem; margin-right: 1rem; align-items: center; }
.vocabulary input[type="checkbox"] { min-height: 1.25rem; min-width: 1.25rem; }
@media (max-width: 640px) { .vocabulary-body { grid-template-columns: 1fr; } .vocabulary-list { max-height: 15rem; } .vocabulary-bar > button { min-height: 2.75rem; } }
</style>
