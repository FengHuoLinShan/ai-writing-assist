<template>
  <section v-if="rehearsal" class="scene-rehearsal" aria-label="旧协议排演历史">
    <header><div><h3>旧版排演历史 <small>只读</small></h3><p>记录按创建时的原协议查看；新排演请使用上方场景导演与累计预算。</p></div>
      <button v-if="canReplay" class="btn btn-sm" type="button" :disabled="running" @click="replay">核对已记录回合</button>
    </header>
    <p v-if="replayStatus" role="status">{{ replayStatus }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <p>共 {{ rehearsal.rounds?.length || 0 }} 个回合。此记录保留原协议来源，不可续跑或分叉。</p>
    <label v-if="characters.length">查看人物视角
      <select v-model="observer" @change="load"><option value="">作者查看</option><option v-for="actor in characters" :key="actor.id" :value="actor.id">{{ actor.name }}</option></select>
    </label>
    <article v-for="round in rehearsal.rounds || []" :key="round.number">
      <h4>第 {{ round.number }} 回合</h4>
      <ul><li v-for="(event, index) in round.events || []" :key="index">{{ actorName(event.actor_id) }}：{{ event.action }}（{{ outcomes[event.outcome] || "尚未裁定" }}）</li></ul>
    </article>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, required: true },
  characters: { type: Array, default: () => [] },
  rehearsalId: { type: String, default: null },
  running: Boolean,
})
const observer = ref("")
const rehearsal = ref(null)
const error = ref("")
const replayStatus = ref("")
const outcomes = { succeeded: "完成", failed: "未能完成", uncertain: "结果未定" }
const canReplay = computed(() => ["observation_v2", "simulation_v3"].includes(rehearsal.value?.protocol))
let generation = 0

function actorName(id) { return props.characters.find((actor) => (actor.character_id || actor.id) === id)?.name || "人物" }
async function replay() {
  try {
    const result = await getApi().story.replayRehearsal(props.projectId, props.rehearsalId)
    replayStatus.value = result.verified ? "已按原记录核对状态；没有调用模型。" : "原记录状态核对未通过。"
  } catch (cause) { error.value = cause?.message || "历史核对暂不可用。" }
}
async function load() {
  const token = ++generation
  error.value = ""
  replayStatus.value = ""
  if (!props.rehearsalId) { rehearsal.value = null; return }
  try {
    const result = await getApi().story.rehearsal(props.projectId, props.rehearsalId, observer.value || null)
    if (token === generation) rehearsal.value = result
  } catch (cause) {
    if (token === generation) error.value = cause?.message || "旧排演历史暂不可读取。"
  }
}
watch(() => [props.projectId, props.rehearsalId], load, { immediate: true })
</script>

<style scoped>
.scene-rehearsal{padding:14px 0;line-height:1.65}.scene-rehearsal header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.scene-rehearsal h3{margin:0}.scene-rehearsal h3 small{padding:2px 7px;border-radius:99px;background:#f1f3f2;color:#66736e;font-size:.7rem;font-weight:500}.scene-rehearsal p{color:var(--muted,#64727b)}.scene-rehearsal label{display:flex;align-items:center;gap:8px;min-height:44px}.scene-rehearsal select{min-height:40px;border:1px solid var(--border,#d9e0e4);border-radius:8px}.scene-rehearsal article{border-top:1px solid var(--border,#d9e0e4);padding:8px 0;overflow-wrap:anywhere}.scene-rehearsal article h4{margin:0}
</style>
