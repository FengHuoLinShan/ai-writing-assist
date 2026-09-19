<template>
  <section v-if="available" class="scene-rehearsal" aria-label="多人物场景排演">
    <h3>多人物排演 <small>实验</small></h3><p>人物分别提出行动，环境裁决后再推进下一回合。最终剧本仍须你审阅与采用。</p>
    <fieldset :disabled="running"><legend>参与人物（最多三名）</legend><label v-for="actor in characters" :key="actor.id"><input v-model="selected" type="checkbox" :value="actor.id" :disabled="selected.length >= 3 && !selected.includes(actor.id)" /> {{ actor.name }}</label></fieldset>
    <label>回合数 <input v-model.number="rounds" type="number" min="1" max="3" :disabled="running" /></label>
    <button type="button" class="btn" :disabled="running || !selected.length || rounds < 1 || rounds > 3" @click="start()">排演场景</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="rehearsal"><p>完成 {{ rehearsal.rounds.length }} 回合。{{ rehearsal.parent_id ? '这是独立分叉，原结果仍保留。' : '' }}</p>
      <label>观察视角 <select v-model="observer" @change="load"><option value="">作者查看</option><option v-for="actor in characters" :key="actor.id" :value="actor.id">{{ actor.name }}</option></select></label>
      <article v-for="round in rehearsal.rounds" :key="round.number"><h4>第 {{ round.number }} 回合</h4><ul><li v-for="(event, index) in round.events" :key="index">{{ actorName(event.actor_id) }}：{{ event.action }}（{{ outcomes[event.outcome] || '尚未裁定' }}）</li></ul><button type="button" class="btn btn-sm" :disabled="running" @click="start(round)">从这一回合另试一种发展</button></article>
    </template>
  </section>
</template>

<script setup>
import { ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"
const props = defineProps({ projectId: { type: String, required: true }, characters: { type: Array, default: () => [] }, rehearsalId: { type: String, default: null }, running: Boolean })
const emit = defineEmits(["run"])
const selected = ref([]), rounds = ref(2), observer = ref(""), rehearsal = ref(null), error = ref(""), available = ref(false)
const outcomes = { succeeded: "完成", failed: "未能完成", uncertain: "结果未定" }
let generation = 0
function actorName(id) { return props.characters.find(actor => actor.id === id)?.name || "人物" }
function start(round = null) { emit("run", { rehearsal: true, characterIds: [...selected.value], rounds: rounds.value, ...(round ? { parentId: props.rehearsalId, forkRound: round.number, parentHash: round.hash } : {}) }) }
async function load() {
  const token = ++generation
  if (!props.rehearsalId) { rehearsal.value = null; return }
  try { const result = await getApi().story.rehearsal(props.projectId, props.rehearsalId, observer.value || null); if (token === generation) { rehearsal.value = result; error.value = "" } }
  catch (cause) { if (token === generation) error.value = cause.message || "回合暂不可读取。" }
}
watch(() => props.projectId, async projectId => {
  available.value = false
  try { const result = await getApi().assistant.capabilities(projectId); if (projectId === props.projectId) available.value = result.rehearsal?.available === true } catch { /* ordinary simulation remains available */ }
}, { immediate: true })
watch(() => props.characters, actors => { selected.value = selected.value.filter(id => actors.some(actor => actor.id === id)); if (!selected.value.length) selected.value = actors.slice(0, 3).map(actor => actor.id) }, { immediate: true })
watch(() => [props.projectId, props.rehearsalId], load, { immediate: true })
</script>

<style scoped>
.scene-rehearsal{padding:16px;border:1px solid var(--border);border-radius:8px;line-height:1.7;margin:12px 0}.scene-rehearsal fieldset{display:flex;gap:16px;flex-wrap:wrap}.scene-rehearsal label{display:inline-flex;gap:8px;align-items:center;min-height:44px;margin-right:12px}.scene-rehearsal input[type=number]{width:4rem;min-height:40px}.scene-rehearsal button,.scene-rehearsal select{min-height:44px}.scene-rehearsal article{border-top:1px solid var(--border);padding:8px 0;overflow-wrap:anywhere}
</style>
