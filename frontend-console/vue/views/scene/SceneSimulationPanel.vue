<template>
  <section id="scene-runtime-panel-simulation" class="scene-runtime-panel scene-simulation-panel" role="tabpanel" aria-labelledby="scene-runtime-tab-simulation">
    <header class="scene-runtime-panel__header">
      <div>
        <p class="scene-runtime-panel__eyebrow">同一场景导演工作台</p>
        <h2>{{ scene?.title || "先选择一个场景" }}</h2>
        <p>预算预览、逐人物隔离排演、候选历史与分支都由同一个导演运行管理。</p>
      </div>
    </header>

    <SceneDirectorPanel :project-id="projectId" :scene="scene" :characters="characters" :selected-writing-reference-ids="selectedWritingReferenceIds" @update:writing-reference-ids="setWritingReferenceIds" />
    <SceneRehearsalPanel v-if="scene && projectId && simulation?.rehearsalId" :project-id="projectId" :characters="characters" :rehearsal-id="simulation.rehearsalId" :running="false" />
    <div v-if="!scene" class="scene-runtime-empty">
      <strong>请先从“管理”选择一个场景</strong>
      <p>推演会读取本场目标、冲突和人物资料。</p>
    </div>
    <div v-else-if="running" class="scene-runtime-progress" role="status" aria-live="polite">
      <strong>{{ progress?.message || "正在整理人物反应与剧情走向…" }}</strong>
      <span v-if="progress?.percent != null">{{ progress.percent }}%</span>
    </div>
    <div v-else-if="error" class="scene-runtime-error" role="alert">{{ error }}</div>
    <div v-else-if="!simulation" class="scene-runtime-empty">
      <strong>先生成一组可比较的候选</strong>
      <p>你可以逐条保留或拒绝人物反应，再把成立的方向带进剧本区。</p>
    </div>
    <div v-else class="scene-simulation-content">
      <section class="scene-runtime-constraints" aria-label="本场约束">
        <h3>本场约束</h3>
        <dl>
          <div><dt>目标</dt><dd>{{ scene.goal || "尚未填写" }}</dd></div>
          <div><dt>核心冲突</dt><dd>{{ scene.core_conflict || "尚未填写" }}</dd></div>
          <div><dt>必须发生</dt><dd>{{ scene.must_happen || "作者待确认" }}</dd></div>
          <div><dt>禁止发生</dt><dd>{{ scene.must_not_happen || "暂无" }}</dd></div>
        </dl>
      </section>

      <section class="scene-runtime-section" aria-labelledby="scene-reactions-heading">
        <div class="scene-runtime-section__heading"><h3 id="scene-reactions-heading">人物反应候选</h3><span>{{ keptCount }} 条已保留</span></div>
        <div v-if="!simulation.reactions?.length" class="scene-runtime-empty scene-runtime-empty--compact">暂未形成可比较的反应候选。</div>
        <article v-for="reaction in simulation.reactions || []" :key="reaction.id" class="scene-reaction-card" :class="`is-${reaction.status || 'candidate'}`">
          <div class="scene-reaction-card__heading"><strong>{{ reaction.name }}</strong><span>{{ reaction.status === "kept" ? "已保留" : reaction.status === "rejected" ? "已拒绝" : "待决定" }}</span></div>
          <p v-if="reaction.goal"><b>目标：</b>{{ reaction.goal }}</p>
          <p v-if="reaction.subjectiveJudgment"><b>判断：</b>{{ reaction.subjectiveJudgment }}</p>
          <p v-if="reaction.motivation"><b>方案动机：</b>{{ reaction.motivation }}</p>
          <p v-if="reaction.immediateReaction"><b>即时反应：</b>{{ reaction.immediateReaction }}</p>
          <p><b>压力：</b>{{ reaction.stance }}</p>
          <p><b>回应：</b>{{ reaction.action }}</p>
          <p v-if="reaction.facialExpression"><b>表情：</b>{{ reaction.facialExpression }}</p>
          <p v-if="reaction.bodyLanguage"><b>肢体：</b>{{ reaction.bodyLanguage }}</p>
          <p v-if="reaction.dialogueTendency"><b>对白倾向：</b>{{ reaction.dialogueTendency }}</p>
          <p v-if="reaction.innerResponse"><b>内心：</b>{{ reaction.innerResponse }}</p>
          <p v-if="reaction.attention"><b>注意：</b>{{ reaction.attention }}</p>
          <p v-if="reaction.change"><b>变化：</b>{{ reaction.change }}</p>
          <p v-if="reaction.schemaVersion === 'story.reaction.v2'"><b>依据：</b>{{ reaction.sourceFactIds.length }} 项确认事实、{{ reaction.sourcePatternIds.length }} 项待审倾向</p>
          <p v-if="reaction.conflict"><b>冲突：</b>{{ reaction.conflict }}</p>
          <p v-if="reaction.confidence"><b>置信度：</b>{{ Math.round(reaction.confidence * 100) }}%</p>
          <div class="scene-reaction-card__actions">
            <button type="button" class="btn btn-sm btn-primary" :data-action="`keep-scene-reaction-${reaction.id}`" :disabled="reaction.status === 'kept'" @click="$emit('reaction', reaction.id, 'kept')">保留</button>
            <button type="button" class="btn btn-sm" :data-action="`reject-scene-reaction-${reaction.id}`" :disabled="reaction.status === 'rejected'" @click="$emit('reaction', reaction.id, 'rejected')">拒绝</button>
          </div>
        </article>
      </section>

      <section class="scene-runtime-section" aria-labelledby="scene-beats-heading">
        <div class="scene-runtime-section__heading"><h3 id="scene-beats-heading">Beat 链与叙事计划</h3></div>
        <ol class="scene-beat-list">
          <li v-for="beat in simulation.beats || []" :key="beat.id"><strong>{{ beat.title }}</strong><span>{{ beat.detail }}</span></li>
        </ol>
        <p class="scene-runtime-plan">{{ simulation.plan || "暂无叙事计划" }}</p>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import SceneDirectorPanel from "./SceneDirectorPanel.vue"
import SceneRehearsalPanel from "./SceneRehearsalPanel.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  characters: { type: Array, default: () => [] },
  scene: { type: Object, default: null },
  simulation: { type: Object, default: null },
  progress: { type: Object, default: null },
  running: Boolean,
  error: { type: String, default: null },
})
defineEmits(["reaction"])
const keptCount = computed(() => (props.simulation?.reactions || []).filter((item) => item.status === "kept").length)
const selectedWritingReferenceIds = ref([])
function storedSelections() {
  try {
    const saved = JSON.parse(globalThis.sessionStorage?.getItem(`writing-director-reference-ids-v1:${props.projectId}`) || "{}")
    return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {}
  } catch { return {} }
}
watch(() => [props.projectId, props.scene?.id], () => {
  const values = storedSelections()[props.scene?.id]
  selectedWritingReferenceIds.value = Array.isArray(values)
    ? [...new Set(values.map(String))].slice(0, 20)
    : []
}, { immediate: true })
function setWritingReferenceIds(values) {
  if (!props.projectId || !props.scene?.id) return
  const ids = [...new Set((Array.isArray(values) ? values : []).map(String))].slice(0, 20)
  selectedWritingReferenceIds.value = ids
  try {
    globalThis.sessionStorage?.setItem(
      `writing-director-reference-ids-v1:${props.projectId}`,
      JSON.stringify({ ...storedSelections(), [props.scene.id]: ids }),
    )
  } catch { /* The current view still keeps the selection until navigation. */ }
}
</script>

<style scoped>
.scene-simulation-panel__legacy{margin-top:18px;padding-top:12px;border-top:1px solid var(--border,#d9e0e4)}
</style>
