<template>
  <details class="scene-lens" :class="{ 'scene-lens--mobile': mobile }" :open="!mobile">
    <summary>
      <span><strong>本场</strong><small>{{ scene?.title || '未命名 Scene' }}</small></span>
      <span aria-hidden="true">详情</span>
    </summary>
    <div class="scene-lens__body">
      <dl v-if="staticItems.length" class="scene-lens__facts">
        <template v-for="item in staticItems" :key="item.label">
          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
        </template>
      </dl>
      <p v-else class="writing-empty-hint">本场还没有可用的结构摘要。</p>

      <div class="scene-lens__load">
        <button type="button" class="btn btn-sm" :disabled="lens.loading" @click="$emit('load')">
          {{ lens.loading ? '正在查看…' : lens.error ? '重试角色可见信息' : lens.data ? '刷新角色可见信息' : '查看角色可见信息' }}
        </button>
        <p v-if="lens.error" class="writing-form-error" role="alert">{{ lens.error }}，静态摘要已保留。</p>
      </div>

      <template v-if="lens.data">
        <section class="scene-lens__section">
          <h4>POV 可见知识</h4>
          <ul v-if="knowledgeItems.length"><li v-for="item in knowledgeItems" :key="`${item.label}:${item.summary}`" :class="{ 'is-unavailable': !item.availability }"><strong>{{ item.label }}</strong><span>{{ item.summary }}</span></li></ul>
          <p v-else class="writing-empty-hint">未找到可安全展示的角色知识。</p>
        </section>
        <section class="scene-lens__section">
          <h4>场景时点状态</h4>
          <ul v-if="stateItems.length"><li v-for="item in stateItems" :key="`${item.label}:${item.summary}`" :class="{ 'is-unavailable': !item.availability, 'is-stale': item.stale }"><strong>{{ item.label }}</strong><em v-if="item.stale" class="scene-lens__stale-badge">待核对</em><span>{{ item.summary }}</span></li></ul>
          <p v-else class="writing-empty-hint">暂无已建立的 Scene 时点状态。</p>
        </section>
        <section class="scene-lens__section">
          <h4>对象状态</h4>
          <ul v-if="objectStates.length" class="scene-lens__objects">
            <li v-for="obj in objectStates" :key="obj.key">
              <strong>{{ obj.label }}<em v-if="obj.stale" class="scene-lens__stale-badge">待核对</em></strong>
              <p v-for="unknown in obj.unknowns" :key="unknown" class="writing-empty-hint">{{ unknown }}</p>
              <p v-if="obj.location" class="scene-lens__object-line">所在：{{ obj.location }}</p>
              <dl v-if="obj.fields.length" class="scene-lens__object-fields">
                <template v-for="field in obj.fields" :key="`${obj.key}:${field.label}`">
                  <dt>{{ field.label }}<em v-if="field.confirmed">已确认</em><em v-else>推导</em><em v-if="field.provenance" class="scene-lens__provenance-badge" :class="`is-${field.provenance.status}`">{{ field.provenance.statusLabel }}</em></dt>
                  <dd>
                    {{ field.display }} <button v-if="field.source?.checkpoint_id" type="button" class="btn btn-sm" @click="openSource(field.source)">查看依据</button>
                    <button v-if="field.provenance" type="button" class="btn btn-sm" @click="toggleProvenance(`${obj.key}:${field.label}`)">{{ provenanceOpenKey === `${obj.key}:${field.label}` ? '收起来源' : '字段来源' }}</button>
                    <SceneFieldProvenance v-if="field.provenance && provenanceOpenKey === `${obj.key}:${field.label}`" :project-id="projectId" :field-label="field.label" :provenance="field.provenance" />
                  </dd>
                </template>
              </dl>
              <p v-for="belief in obj.knowledge" :key="`${obj.key}:${belief.holder}:${belief.text}`" class="scene-lens__object-line" :class="{ 'is-misconception': belief.possiblyFalse }">
                认知：{{ belief.holder }}认为「{{ belief.text }}」{{ belief.possiblyFalse ? '（可能误信）' : '' }}
                <button v-if="belief.source?.checkpoint_id" type="button" class="btn btn-sm" @click="openSource(belief.source)">查看依据</button>
              </p>
            </li>
          </ul>
          <p v-else class="writing-empty-hint">本场没有可展示的对象级状态；未记载的状态不会显示为「确定没有」。</p>
          <p v-if="objectStates.length && !hasAnyProvenance" class="writing-empty-hint">本场状态还没有逐字段来源记录；随着正文推进和状态整理，每个字段会逐步标出具体依据。</p>
          <SceneStateTrial v-if="lens.data.state_fingerprint && projectId" :project-id="projectId" :scene-id="scene.id" :fingerprint="lens.data.state_fingerprint" :choices="lens.data.subject_choices" :objects="lens.data.object_states" @source="openSource" @start-trial="$emit('start-trial', $event)" />
          <SceneCheckpointHistory v-if="projectId" :project-id="projectId" :scene-id="scene.id" @source="openSource" />
          <section v-if="sourceOpen" class="scene-lens__section" aria-label="状态依据">
            <h4>状态依据</h4><p v-if="sourceLoading">正在回读…</p><p v-if="sourceError" role="alert">{{ sourceError }}</p>
            <template v-if="sourceData"><p>{{ sourceData.summary }}</p><p>{{ sourceData.authority }}</p>
              <p v-for="item in sourceData.events" :key="item.id">第 {{ item.chapter_index }} 章：{{ eventText(item) }}</p>
              <p v-if="sourceData.missing">部分历史事件无法回读；该部分依据尚未核对。</p>
              <p v-if="sourceData.gap">{{ sourceData.gap }}</p>
              <button v-for="parent in sourceData.parents" :key="parent.id" type="button" class="btn btn-sm" @click="openSource({ checkpoint_id: parent.id })">查看此前场景依据</button>
            </template>
            <button type="button" class="btn btn-sm" @click="sourceOpen = false">收起依据</button>
          </section>
          <button v-if="projectId" type="button" class="btn btn-sm" :disabled="repairLoading" @click="refreshState">{{ repairLoading ? '正在重读状态…' : '重新整理已有状态记录' }}</button>
          <p v-if="repairError" role="alert">{{ repairError }}</p>
          <p v-if="repairNote" role="status">{{ repairNote }}</p>
          <button v-if="projectId" type="button" class="btn btn-sm scene-lens__trial-entry" @click="$emit('start-trial')">从本场状态发起试改</button>
        </section>
        <p v-for="warning in lens.data.warnings || []" :key="warning" class="scene-lens__warning">{{ warning }}</p>
      </template>
      <EvolutionPanorama v-if="projectId && scene?.id" :project-id="projectId" :scene-id="scene.id" />
    </div>
  </details>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import EvolutionPanorama from "../../../components/EvolutionPanorama.vue"
import SceneCheckpointHistory from "./SceneCheckpointHistory.vue"
import SceneFieldProvenance from "./SceneFieldProvenance.vue"
import SceneStateTrial from "./SceneStateTrial.vue"
import { getApi } from "../../../bridge/index.js"
import { sceneLensItems, sceneObjectStates, sceneStructureSummary } from "../sceneLensModel.js"

const props = defineProps({
  scene: { type: Object, default: null },
  lens: { type: Object, default: () => ({ loading: false, data: null, error: null }) },
  mobile: { type: Boolean, default: false },
  projectId: { type: String, default: null },
})
const emit = defineEmits(["load", "start-trial"])
const sourceOpen = ref(false), sourceLoading = ref(false), sourceData = ref(null), sourceError = ref("")
const repairLoading = ref(false), repairError = ref(""), repairNote = ref("")
const provenanceOpenKey = ref("")
let sourceGeneration = 0
let repairGeneration = 0
watch(() => [props.projectId, props.scene?.id, props.lens.data], () => {
  sourceGeneration++; sourceOpen.value = false; sourceLoading.value = false; sourceData.value = null
  sourceError.value = ""
  provenanceOpenKey.value = ""
})
watch([() => props.projectId, () => props.scene?.id], () => {
  repairGeneration++; repairLoading.value = false
  repairError.value = repairNote.value = ""
})
function eventText(item) {
  const state = item.snapshot_after || {}
  const names = { ...(props.lens.data?.subject_choices || {}), ...Object.fromEntries((props.lens.data?.object_states || []).map(item => [item.subject_id, item.label])) }
  const label = id => names[id] || "未记录名称的对象"
  const facts = [state.custody_holder ? `保管人：${label(state.custody_holder)}` : "", state.custody_owner ? `所有人：${label(state.custody_owner)}` : "", state.opening_key_id ? `所需钥匙：${label(state.opening_key_id)}` : "", state.opening_moon_phase ? `所需月相：${state.opening_moon_phase === "full" ? "月圆" : "非月圆"}` : ""]
  return [state.summary || state.text || state.knowledge || state.content || state.text_state || state.name || names[item.entity_id] || "状态变化记录", ...facts.filter(Boolean)].join("；")
}
async function openSource(source) {
  const token = ++sourceGeneration
  sourceOpen.value = sourceLoading.value = true; sourceData.value = null; sourceError.value = ""
  try {
    const checkpoint = await getApi().story.sceneCheckpointRecord(props.projectId, source.checkpoint_id)
    if (token !== sourceGeneration) return
    const refs = checkpoint.evidence_refs || []
    const ids = new Set(refs.filter(item => item.type === "memory_event").map(item => item.id))
    const events = []
    const eventIds = [...ids]
    for (let offset = 0; offset < eventIds.length; offset += 100) {
      const records = await getApi().story.memoryEventsByIds(props.projectId, eventIds.slice(offset, offset + 100))
      events.push(...records.items)
    }
    if (token !== sourceGeneration) return
    sourceData.value = { summary: checkpoint.display_summary || "已记录的场景状态", events,
      missing: events.length !== ids.size, gap: checkpoint.gap_reason,
      parents: refs.filter(item => item.type === "scene_checkpoint"),
      authority: [checkpoint.is_current ? "" : "历史记录：不能作为当前已核对状态。", checkpoint.confirmed || checkpoint.source === "manual" ? "作者确认的状态记录。" : "本维度的推导依据；尚未逐字段定位到正文。"].filter(Boolean).join(" ") }
  } catch (error) { if (token === sourceGeneration) sourceError.value = error.message || "依据暂时无法回读。" }
  finally { if (token === sourceGeneration) sourceLoading.value = false }
}
async function refreshState() {
  const projectId = props.projectId, sceneId = props.scene.id
  const token = ++repairGeneration
  repairLoading.value = true; repairError.value = repairNote.value = ""
  try {
    await getApi().story.ensureSceneCheckpoints(projectId, sceneId)
    if (token !== repairGeneration) return
    emit("load")
    repairNote.value = "已按现有事件重新整理；缺少的正文依据和行动条件仍需补充核对。"
  } catch (error) { if (token === repairGeneration) repairError.value = error.message || "状态整理未完成，请重试。" }
  finally { if (token === repairGeneration) repairLoading.value = false }
}
const staticItems = computed(() => sceneStructureSummary(props.scene))
const knowledgeItems = computed(() => sceneLensItems(props.lens.data?.role_visible_knowledge))
const stateItems = computed(() => sceneLensItems(props.lens.data?.scene_world_state))
const objectStates = computed(() => sceneObjectStates(props.lens.data?.object_states))
const hasAnyProvenance = computed(() => objectStates.value.some(obj => obj.fields.some(field => field.provenance)))
function toggleProvenance(key) {
  provenanceOpenKey.value = provenanceOpenKey.value === key ? "" : key
}
</script>

<style scoped>
.scene-lens__objects { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.scene-lens__objects strong { display: block; }
.scene-lens__object-line { margin: 2px 0 0; }
.scene-lens__object-fields { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; margin: 4px 0 0; }
.scene-lens__object-fields dt { font-weight: 600; }
.scene-lens__object-fields dt em { font-style: normal; font-weight: 400; margin-left: 4px; opacity: 0.75; }
.scene-lens__object-line.is-misconception { opacity: 0.85; }
.scene-lens__stale-badge { font-style: normal; margin-left: 6px; padding: 0 6px; border-radius: 8px; background: rgba(176, 132, 32, 0.16); font-size: 12px; }
.scene-lens__provenance-badge { font-style: normal; margin-left: 6px; padding: 0 6px; border-radius: 8px; font-size: 12px; }
.scene-lens__provenance-badge.is-exact { background: rgba(46, 125, 80, 0.16); }
.scene-lens__provenance-badge.is-unverified { background: rgba(176, 132, 32, 0.16); }
.scene-lens__provenance-badge.is-conflict { background: rgba(176, 64, 32, 0.16); }
li.is-stale { opacity: 0.92; }
.scene-lens__trial-entry { margin-top: 10px; }
</style>
