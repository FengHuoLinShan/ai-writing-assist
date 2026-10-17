<template>
  <details class="spatial-metadata" @toggle="onToggle">
    <summary>独立空间、类型与生效范围</summary>
    <p>空间分别排布。更改会先留在当前地图编辑中，保存后才成为地图版本。</p>
    <p v-if="error" class="map-error" role="alert">{{ error }}</p>
    <p v-if="loading" role="status">正在读取项目类型和场景…</p>
    <button v-if="!loaded" class="btn btn-sm" :disabled="loading || disabled" @click="load">重新读取编辑选项</button>
    <template v-if="document.schema_version !== 2"><p>当前地图使用单空间格式。启用后可以定义独立空间、类型和场景生效范围。</p><button class="btn btn-sm" :disabled="disabled" @click="upgrade">启用空间与时效编辑</button></template>
    <template v-else>
      <fieldset :disabled="disabled || confirming"><legend>空间</legend>
        <article v-for="space in document.spaces || []" :key="space.id" class="space-row">
          <label>空间名称<input :value="space.label" class="form-input" maxlength="200" @change="patch('spaces', space.id, { label: $event.target.value.trim() || space.label })" /></label>
          <label>空间类型<select :value="typeValue(space)" class="form-select" @change="setType('spaces', space, $event.target.value)"><option value="">按文字说明</option><option v-if="oldType(space, 'space')" :value="typeValue(space)">{{ oldType(space, 'space') }}</option><option v-for="term in types('space')" :key="term.id" :value="term.id + '@' + term.revision_id">{{ term.name }}</option></select></label>
          <button class="btn btn-sm" :disabled="space.id === 'main' || document.features.some(item => item.space_id === space.id)" @click="removeSpace(space.id)">移出空空间</button>
        </article>
        <button class="btn btn-sm" :disabled="(document.spaces || []).length >= 20" @click="addSpace">新增独立空间</button>
      </fieldset>
      <fieldset :disabled="disabled || confirming"><legend>图元与关系</legend>
        <label>编辑对象<select v-model="selection" class="form-select"><option value="">选择图元、关系或行程</option><option v-for="item in choices" :key="item.key" :value="item.key">{{ item.label }}</option></select></label>
        <template v-if="selected">
          <label v-if="collection === 'features'">所属空间<select :value="selected.space_id || 'main'" class="form-select" :disabled="selected.locked" @change="moveSpace($event.target.value)"><option v-for="space in spaces" :key="space.id" :value="space.id">{{ space.label }}</option></select></label>
          <p v-if="collection === 'features' && selected.locked">位置已锁定，解锁后才可移到其他空间。</p>
          <label v-if="collection !== 'journeys'">{{ collection === 'features' ? '图元类型' : '关系类型' }}<select :value="typeValue(selected)" class="form-select" @change="setType(collection, selected, $event.target.value)"><option value="">按文字说明</option><option v-if="oldType(selected, typeKind)" :value="typeValue(selected)">{{ oldType(selected, typeKind) }}</option><option v-for="term in types(typeKind)" :key="term.id" :value="term.id + '@' + term.revision_id">{{ term.name }}</option></select></label>
          <template v-if="collection === 'journeys'">
            <label>交通方式<input :value="selected.transport_label" class="form-input" maxlength="200" @change="patch(collection, selected.id, { transport_label: $event.target.value.trim() || selected.transport_label })" /></label>
            <label v-for="field in journeyTypes" :key="field.key">{{ field.label }}<select :value="typeValue(selected, field.key)" class="form-select" @change="setType(collection, selected, $event.target.value, field.key)"><option value="">按文字说明</option><option v-if="oldType(selected, field.kind, field.key)" :value="typeValue(selected, field.key)">{{ oldType(selected, field.kind, field.key) }}</option><option v-for="term in types(field.kind)" :key="term.id" :value="term.id + '@' + term.revision_id">{{ term.name }}</option></select></label>
            <p>行程：{{ featureLabel(selected.origin) }} → {{ featureLabel(selected.destination) }}</p>
            <p v-for="(source, index) in selected.sources || []" :key="index">依据：{{ source.quote }}</p>
            <label>通行条件（每行一项）<textarea :value="(selected.access_conditions || []).map(item => item.label).join('\n')" class="form-textarea" rows="3" maxlength="6000" @change="setConditions($event.target.value)" /></label>
          </template>
          <label>这条内容的性质<select :value="selected.modality || 'event_observed'" class="form-select" @change="patch(collection, selected.id, { modality: $event.target.value })"><option v-for="(label, key) in modalities" :key="key" :value="key">{{ label }}</option></select></label>
          <p v-if="selected.modality && selected.modality !== 'event_observed'">保留为文字资料，不参与客观空间计算。</p>
          <label>从哪个场景开始生效<select :value="selected.effective?.start?.kind === 'scene' ? selected.effective.start.id : ''" class="form-select" :disabled="selected.effective?.start?.kind === 'chapter'" @change="setAnchor('start', $event.target.value)"><option value="">未限定开始</option><option v-if="missingAnchor('start')" :value="selected.effective.start.id">原固定场景（未在本页）</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option></select></label>
          <label>到哪个场景结束生效<select :value="selected.effective?.end?.kind === 'scene' ? selected.effective.end.id : ''" class="form-select" :disabled="selected.effective?.end?.kind === 'chapter'" @change="setAnchor('end', $event.target.value)"><option value="">未限定结束</option><option v-if="missingAnchor('end')" :value="selected.effective.end.id">原固定场景（未在本页）</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option></select></label>
          <p v-if="selected.effective?.start?.kind === 'chapter' || selected.effective?.end?.kind === 'chapter'">此条目含章节身份锚点，当前场景选项不替换它。请先核对原锚点。</p>
          <section v-if="selected.effective && selected.modality === 'event_observed'" class="map-state-confirmation" aria-label="记录地图状态观察">
            <h4>记录某场已确认的地图状态</h4>
            <p>这会把作者确认的状态写入所选 Scene 的 Story 记录，不改地图版本。它只供作者核对地图有效期，至少从后续 Scene 起参与读取；人物和读者视角不会因此自动知道。</p>
            <label>在哪个场景确认<select v-model="stateSceneId" class="form-select" :disabled="disabled || stateSaving"><option value="">选择场景</option><option v-if="stateSceneId && !scenes.some(scene => scene.id === stateSceneId)" :value="stateSceneId">草稿关联场景（切换场景页后可保存）</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.label }}</option></select></label>
            <label>该声明在此场的状态<select :value="stateDraft.status" class="form-select" :disabled="disabled || stateSaving" @change="setStateStatus($event.target.value)"><option value="active">仍然生效</option><option value="inactive">已不再生效</option></select></label>
            <p v-if="stateDisabled" class="map-state-hint">请先保存当前地图，并确保它是已采用版本，再记录剧情状态。</p>
            <p v-if="stateDraft.error" class="map-error" role="alert">{{ stateDraft.error }}</p>
            <p v-else-if="stateSavedKey === stateDraftKey" class="map-state-success" role="status">Story 状态已记录，当前场景投影已更新。</p>
            <button type="button" class="btn btn-sm btn-primary" :disabled="!canSaveState" @click="saveMapState">{{ stateSaving ? '正在记录…' : stateDraft.story_saved ? '重试更新场景投影' : '确认并记录此场状态' }}</button>
          </section>
          <nav v-if="sceneTotal > 50" class="map-actions" aria-label="生效范围场景翻页"><button type="button" class="btn btn-sm" :disabled="loading || sceneOffset === 0" @click="loadScenes(sceneOffset - 50)">上一页场景</button><span>场景 {{ sceneOffset + 1 }}–{{ Math.min(sceneOffset + 50, sceneTotal) }} / {{ sceneTotal }}</span><button type="button" class="btn btn-sm" :disabled="loading || sceneOffset + 50 >= sceneTotal" @click="loadScenes(sceneOffset + 50)">下一页场景</button></nav>
        </template>
      </fieldset>
    </template>
    <p v-if="omitted">另有 {{ omitted }} 项类型未读取，请先在项目类型中整理。</p>
  </details>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getConfirmAction } from '../../bridge/index.js'
import { confirmAsync } from '../../../shared/confirmAsync.js'
const props = defineProps({ projectId: { type: String, required: true }, document: { type: Object, required: true }, selectedFeatureId: { type: String, default: '' }, nodeId: { type: String, default: '' }, revisionId: { type: String, default: '' }, stateDisabled: Boolean, disabled: Boolean })
const emit = defineEmits(['change', 'state'])
const api = getApi(), terms = ref([]), scenes = ref([]), omitted = ref(0), loading = ref(false), loaded = ref(false), error = ref(''), confirming = ref(false), selection = ref('')
const sceneOffset = ref(0), sceneTotal = ref(0), stateSceneId = ref(''), stateSaving = ref(false), mapStateDrafts = ref({}), stateSelectionByDeclaration = ref({}), stateSavedKey = ref('')
let active = true, epoch = 0
const modalities = { event_observed: '已发生或作者确认', character_statement: '人物陈述', belief: '主观认知', hypothesis: '假设', author_plan: '作者计划', figurative: '比喻', unclear: '含义待核对' }
const journeyTypes = [{ key: 'transport', kind: 'transport', label: '交通类型' }, { key: 'traveler', kind: 'traveler', label: '旅行者类别' }, { key: 'connection', kind: 'relation', label: '连接类型' }]
const spaces = computed(() => props.document.spaces?.length ? props.document.spaces : [{ id: 'main', label: '主空间' }])
const choices = computed(() => [
  ...props.document.features.map(item => ({ key: 'features/' + item.id, label: '图元 · ' + item.label })),
  ...props.document.constraints.map(item => ({ key: 'constraints/' + item.id, label: '关系 · ' + featureLabel(item.subject) + ' → ' + featureLabel(item.target) })),
  ...(props.document.journeys || []).map(item => ({ key: 'journeys/' + item.id, label: '行程 · ' + featureLabel(item.origin) + ' → ' + featureLabel(item.destination) })),
])
const collection = computed(() => selection.value.split('/')[0])
const selected = computed(() => props.document[collection.value]?.find(item => selection.value === collection.value + '/' + item.id))
const typeKind = computed(() => collection.value === 'features' ? 'feature' : 'relation')
const declarationKind = computed(() => ({ features: 'feature', constraints: 'constraint', journeys: 'journey' })[collection.value] || '')
const stateSelectionKey = computed(() => JSON.stringify([props.projectId, props.nodeId, props.revisionId, declarationKind.value, selected.value?.id || '']))
const stateDraftKey = computed(() => JSON.stringify([props.projectId, props.nodeId, props.revisionId, declarationKind.value, selected.value?.id || '', stateSceneId.value]))
const stateDraft = computed(() => mapStateDrafts.value[stateDraftKey.value] || { status: 'active', idempotency_key: '', story_saved: false, error: '' })
const stateDisabled = computed(() => props.stateDisabled || !props.nodeId || !props.revisionId)
const canSaveState = computed(() => Boolean(
  !props.disabled && !stateDisabled.value && !stateSaving.value && loaded.value
  && scenes.value.some(scene => scene.id === stateSceneId.value)
  && selected.value?.effective && selected.value.modality === 'event_observed'
  && ['feature', 'constraint', 'journey'].includes(declarationKind.value)
))
watch(() => props.selectedFeatureId, value => { if (value) selection.value = 'features/' + value }, { immediate: true })
watch([loading, confirming, stateSaving], () => emit('state', { busy: loading.value || confirming.value || stateSaving.value }), { immediate: true, flush: 'sync' })
watch(() => props.projectId, () => { epoch++; terms.value = []; scenes.value = []; sceneTotal.value = 0; sceneOffset.value = 0; loaded.value = false; loading.value = false; confirming.value = false; stateSaving.value = false; error.value = ''; selection.value = '' })
watch([() => props.projectId, () => props.nodeId, () => props.revisionId, selection], () => { stateSceneId.value = stateSelectionByDeclaration.value[stateSelectionKey.value] || ''; stateSavedKey.value = '' }, { flush: 'sync' })
watch([stateSelectionKey, stateSceneId], ([key, sceneId]) => { if (sceneId) stateSelectionByDeclaration.value = { ...stateSelectionByDeclaration.value, [key]: sceneId } }, { flush: 'sync' })
onBeforeUnmount(() => { active = false; epoch++; emit('state', { busy: false }) })
function types(kind) { return terms.value.filter(term => term.kind === kind && term.status === 'active') }
function oldType(item, kind, prefix = '') {
  const key = prefix ? prefix + '_type_ref' : 'type_ref', revision = prefix ? prefix + '_type_revision_id' : 'type_revision_id'
  if (!item[key]) return ''
  const current = types(kind).find(term => term.id === item[key] && term.revision_id === item[revision])
  if (current) return ''
  return '原固定类型（旧修订保留）'
}
function typeValue(item, prefix = '') { const key = prefix ? prefix + '_type_ref' : 'type_ref', revision = prefix ? prefix + '_type_revision_id' : 'type_revision_id'; return item[key] ? item[key] + '@' + item[revision] : '' }
function featureLabel(id) { return props.document.features.find(item => item.id === id)?.label || '未找到图元' }
function change(mutator) { if (props.disabled || confirming.value) return; const copy = JSON.parse(JSON.stringify(props.document)); mutator(copy); emit('change', copy) }
function patch(group, id, values) { change(copy => Object.assign(copy[group].find(item => item.id === id), values)) }
function upgrade() { change(copy => { copy.schema_version = 2; copy.spaces = [{ id: 'main', label: '主空间' }]; copy.journeys = []; for (const feature of copy.features) feature.space_id = 'main' }) }
function addSpace() { change(copy => { copy.spaces ||= []; if (copy.spaces.length < 20) copy.spaces.push({ id: 'space:' + crypto.randomUUID(), label: '新空间' }) }) }
function removeSpace(id) { if (id !== 'main' && !props.document.features.some(item => item.space_id === id)) change(copy => { copy.spaces = copy.spaces.filter(item => item.id !== id) }) }
function setType(group, item, value, prefix = '') {
  const kind = group === 'spaces' ? 'space' : group === 'features' ? 'feature' : prefix === 'transport' || prefix === 'traveler' ? prefix : 'relation'
  const term = terms.value.find(term => term.id + '@' + term.revision_id === value && term.status === 'active' && term.kind === kind)
  const key = prefix ? prefix + '_type_ref' : 'type_ref', revision = prefix ? prefix + '_type_revision_id' : 'type_revision_id'
  if (value && !term) return
  patch(group, item.id, { [key]: term?.id || null, [revision]: term?.revision_id || null })
}
function setAnchor(side, id) {
  if (!selected.value) return
  if (selected.value.effective?.[side]?.kind === 'chapter') return
  if (id && !scenes.value.some(scene => scene.id === id)) return
  const effective = { ...(selected.value.effective || {}), [side]: id ? { kind: 'scene', id } : null }
  patch(collection.value, selected.value.id, { effective: effective.start || effective.end ? effective : null })
}
function idempotencyKey() { return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }
function updateStateDraft(key, update) {
  mapStateDrafts.value = {
    ...mapStateDrafts.value,
    [key]: {
      ...(mapStateDrafts.value[key] || { status: 'active', idempotency_key: '', story_saved: false, error: '' }),
      ...update,
    },
  }
}
function setStateStatus(status) {
  if (!['active', 'inactive'].includes(status)) return
  const key = stateDraftKey.value, prior = stateDraft.value
  mapStateDrafts.value = {
    ...mapStateDrafts.value,
    [key]: {
      ...prior,
      status,
      idempotency_key: prior.status === status ? prior.idempotency_key : idempotencyKey(),
      story_saved: prior.status === status ? prior.story_saved : false,
      error: '',
    },
  }
  stateSavedKey.value = ''
}
async function saveMapState() {
  if (!canSaveState.value || !selected.value || !stateSceneId.value) return
  const token = epoch
  const projectId = props.projectId, sceneId = stateSceneId.value
  const nodeId = props.nodeId, revisionId = props.revisionId
  const kind = declarationKind.value, declarationId = selected.value.id
  const key = stateDraftKey.value
  let draft = stateDraft.value
  if (!draft.idempotency_key) {
    draft = { ...draft, idempotency_key: idempotencyKey() }
    updateStateDraft(key, draft)
  }
  stateSaving.value = true
  updateStateDraft(key, { error: '' })
  try {
    if (!draft.story_saved) {
      await api.story.confirmMapDeclarationState(projectId, {
        confirmed: true,
        scene_id: sceneId,
        node_id: nodeId,
        revision_id: revisionId,
        declaration_kind: kind,
        declaration_id: declarationId,
        status: draft.status,
        idempotency_key: draft.idempotency_key,
      })
      if (!active || token !== epoch) return
      updateStateDraft(key, { story_saved: true })
    }
    await api.story.ensureSceneCheckpoints(projectId, sceneId)
    if (!active || token !== epoch) return
    const latest = mapStateDrafts.value[key]
    if (latest?.idempotency_key === draft.idempotency_key) {
      const next = { ...mapStateDrafts.value }
      delete next[key]
      mapStateDrafts.value = next
      stateSavedKey.value = key
    }
  } catch (failure) {
    if (active && token === epoch) {
      updateStateDraft(key, {
        error: failure?.message || '保存失败；草稿仍保留，可以重试。',
      })
    }
  } finally {
    if (active && token === epoch) stateSaving.value = false
  }
}
function missingAnchor(side) { const anchor = selected.value?.effective?.[side]; return anchor?.kind === 'scene' && !scenes.value.some(scene => scene.id === anchor.id) }
function setConditions(value) {
  const labels = value.split('\n').map(label => label.trim()).filter(Boolean)
  if (labels.length > 30 || labels.some(label => label.length > 500)) { error.value = '通行条件最多 30 项，每项不超过 500 字。'; return }
  const previous = selected.value.access_conditions || []
  patch(collection.value, selected.value.id, { access_conditions: labels.map(label => previous.find(item => item.label === label) || { label }) })
}
async function moveSpace(id) {
  const feature = selected.value
  if (!feature || feature.locked || props.disabled || confirming.value || !spaces.value.some(space => space.id === id) || (feature.space_id || 'main') === id) return
  if (props.document.images.some(image => (image.anchors || []).some(anchor => anchor.feature_id === feature.id))) { error.value = '这个图元用于底图校准，请先解除相关校准，再移入其他空间。'; return }
  const token = epoch, featureId = feature.id
  if (feature.points.length) {
    confirming.value = true
    let approved
    try { approved = await confirmAsync(`将“${feature.label}”移入另一个空间？当前坐标会清空，需要在新空间重新定位。`, '确认移入', { confirmAction: getConfirmAction() }) }
    finally { if (active && token === epoch) confirming.value = false }
    if (!approved || !active || token !== epoch || props.disabled || selected.value?.id !== featureId) return
  }
  patch('features', featureId, { space_id: id, points: [] })
}
async function load() {
  if (loading.value || props.disabled) return
  const token = ++epoch, projectId = props.projectId
  loading.value = true; error.value = ''
  const results = await Promise.allSettled([api.world.listProjectVocabulary(projectId), api.outline.listScenes(projectId, 0, 50)])
  if (!active || token !== epoch || projectId !== props.projectId) return
  if (results[0].status === 'fulfilled') { terms.value = results[0].value.items; omitted.value = results[0].value.omitted_count || 0 }
  if (results[1].status === 'fulfilled') installScenes(results[1].value, 0)
  loaded.value = results.every(item => item.status === 'fulfilled')
  if (!loaded.value) error.value = '部分编辑选项未读取，原类型和锚点保留。可以重试。'
  loading.value = false
}
function installScenes(value, offset) { const items = value.items || value || []; scenes.value = items.filter(item => ['draft', 'canonical', 'candidate'].includes(item.status)).map(item => ({ id: item.id, label: `第 ${item.scene_index + 1} 场 · ${item.title || item.summary || '未命名场景'}` })); sceneTotal.value = value.total ?? items.length; sceneOffset.value = offset }
async function loadScenes(offset) {
  if (props.disabled || loading.value || confirming.value) return
  const token = ++epoch, projectId = props.projectId
  loading.value = true; error.value = ''
  try { const result = await api.outline.listScenes(projectId, offset, 50); if (active && token === epoch) installScenes(result, offset) }
  catch (failure) { if (active && token === epoch) error.value = failure.message || '场景读取失败，原锚点保留。' }
  finally { if (active && token === epoch) loading.value = false }
}
function onToggle(event) { if (event.target.open && !loaded.value) load() }
</script>

<style scoped>
.spatial-metadata { padding: 1rem; margin-block: 1rem; border: 1px solid var(--border); border-radius: .5rem; }
.spatial-metadata summary { cursor: pointer; font-weight: 600; }
.spatial-metadata label { display: block; margin-block: .65rem; }
.spatial-metadata fieldset { border: 0; padding: .75rem 0; min-width: 0; }
.spatial-metadata p { color: var(--text-secondary); overflow-wrap: anywhere; }
.map-state-confirmation { border-top: 1px solid var(--border); margin-block: 1rem; padding-top: .75rem; }
.map-state-confirmation h4 { margin-block: .5rem; }
.map-state-confirmation label { display: block; margin-block: .65rem; }
.map-state-hint { font-size: .9rem; }
.map-state-success { color: var(--success, #276749); }
.space-row { border-bottom: 1px solid var(--border); padding-block: .5rem; }
</style>
