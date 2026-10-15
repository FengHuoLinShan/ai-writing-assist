<template>
  <section v-if="available" class="scene-rehearsal" aria-label="多人物场景排演">
    <h3>多人物排演 <small>实验</small></h3><p>人物分别提出行动，环境裁决后再推进下一回合。最终剧本仍须你审阅与采用。</p>
    <fieldset :disabled="running"><legend>参与人物</legend><label v-for="actor in characters" :key="actor.id"><input v-model="selected" type="checkbox" :value="actor.id" :disabled="!hasWorldIdentity(actor)" /> {{ actor.name }}</label></fieldset>
    <p v-if="characters.some(actor => !hasWorldIdentity(actor))">未关联到作品人物的条目暂时不能参与。</p>
    <details><summary>设置本次场景假设</summary><p>选中的人物沿用现有身份；输入的物品和地点只作为本次试验中的临时设定，不会匹配或写入世界对象。</p><label>临时物品（每行一个，初始无人持有）<textarea v-model="items" rows="2" :disabled="running" /></label><label>共同起点<input v-model="location" :disabled="running" /></label><label>可直接前往的地点（每行一个）<textarea v-model="destinations" rows="2" :disabled="running || !location.trim()" /></label></details>
    <p>每次提交一回合；继续后续发展时由你再次发起。</p>
    <button type="button" class="btn" :disabled="running || !selected.length" @click="start()">排演一回合</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <button v-if="canReplay" class="btn btn-sm" type="button" :disabled="running" @click="replay">核对已记录回合（不重新推演）</button><p v-if="replayStatus" role="status">{{ replayStatus }}</p>
    <template v-if="rehearsal"><p>完成 {{ rehearsal.rounds.length }} 回合。{{ rehearsal.parent_id ? '这是独立分叉，原结果仍保留。' : '' }}</p>
      <p v-if="!canFork">这份旧记录仅供查看，不能从中创建新分支。</p>
      <label>观察视角 <select v-model="observer" @change="load"><option value="">作者查看</option><option v-for="actor in characters" :key="actor.id" :value="actor.id">{{ actor.name }}</option></select></label>
      <article v-for="round in rehearsal.rounds" :key="round.number"><h4>第 {{ round.number }} 回合</h4><ul><li v-for="(event, index) in round.events" :key="index">{{ actorName(event.actor_id) }}：{{ event.action }}（{{ outcomes[event.outcome] || '尚未裁定' }}）</li></ul><button type="button" class="btn btn-sm" :disabled="running || !canFork" @click="start(round)">从这一回合另试一种发展</button></article>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"
const props = defineProps({ projectId: { type: String, required: true }, characters: { type: Array, default: () => [] }, rehearsalId: { type: String, default: null }, running: Boolean })
const emit = defineEmits(["run"])
const selected = ref([]), observer = ref(""), rehearsal = ref(null), error = ref(""), available = ref(false)
const outcomes = { succeeded: "完成", failed: "未能完成", uncertain: "结果未定" }
const items = ref(""), location = ref(""), destinations = ref(""), replayStatus = ref("")
const canFork = computed(() => rehearsal.value?.protocol === "simulation_v3" && Array.isArray(rehearsal.value?.scenario_seed?.participants))
const canReplay = computed(() => ["observation_v2", "simulation_v3"].includes(rehearsal.value?.protocol))
let generation = 0
function actorName(id) { return props.characters.find(actor => actor.id === id)?.name || "人物" }
function hasWorldIdentity(actor) { return Boolean(actor?.id && !String(actor.id).startsWith("character-")) }
function start(round = null) {
  if (round && !canFork.value) return
  const actorIds = round
    ? rehearsal.value.scenario_seed.participants.filter(reference => reference.kind === "object").map(reference => reference.id)
    : selected.value.filter(id => id && !String(id).startsWith("character-"))
  if (!actorIds.length) return
  const names = [...new Set(items.value.split("\n").map(value => value.trim()).filter(Boolean))]
  const startLocation = location.value.trim()
  const places = [...new Set(destinations.value.split("\n").map(value => value.trim()).filter(value => value && value !== startLocation))]
  const candidate = (id, label) => ({ kind: "candidate", id, label })
  const origin = startLocation ? candidate("location-origin", startLocation) : null
  const destinationsForRun = places.map((label, index) => candidate(`location-destination-${index + 1}`, label))
  const seed = round ? rehearsal.value.scenario_seed : {
    participants: actorIds.map(id => ({ kind: "object", id })),
    locations: origin ? [origin, ...destinationsForRun] : [],
    positions: origin ? actorIds.map(id => ({ subject: { kind: "object", id }, location: origin })) : [],
    resources: names.map((label, index) => ({ resource: candidate(`item-${index + 1}`, label), holder: null })),
    routes: origin ? destinationsForRun.map(destination => ({ origin, destination })) : [],
    assumptions: ["作者为本次独立试验提供的初始条件，不等于正史。"],
  }
  emit("run", { rehearsal: true, protocol: "simulation_v3", seed, characterIds: actorIds, rounds: 1, ...(round ? { parentId: props.rehearsalId, forkRound: round.number, parentHash: round.hash } : {}) })
}
async function replay() { try { const result = await getApi().story.replayRehearsal(props.projectId, props.rehearsalId); replayStatus.value = result.verified ? "已按原记录重放，状态一致，没有调用模型。" : "状态核对未通过。" } catch (cause) { error.value = cause.message } }
async function load() {
  const token = ++generation
  if (!props.rehearsalId) { rehearsal.value = null; return }
  try { const result = await getApi().story.rehearsal(props.projectId, props.rehearsalId, observer.value || null); if (token === generation) { rehearsal.value = result; if (canFork.value) { selected.value = result.scenario_seed.participants.filter(reference => reference.kind === "object").map(reference => reference.id) }; error.value = "" } }
  catch (cause) { if (token === generation) error.value = cause.message || "回合暂不可读取。" }
}
watch(() => props.projectId, async projectId => {
  available.value = false
  try { const result = await getApi().assistant.capabilities(projectId); if (projectId === props.projectId) available.value = result.rehearsal?.available === true } catch { /* ordinary simulation remains available */ }
}, { immediate: true })
watch(() => props.characters, actors => { const eligible = actors.filter(hasWorldIdentity); selected.value = selected.value.filter(id => eligible.some(actor => actor.id === id)); if (!selected.value.length) selected.value = eligible.map(actor => actor.id) }, { immediate: true })
watch(() => [props.projectId, props.rehearsalId], load, { immediate: true })
</script>

<style scoped>
.scene-rehearsal{padding:16px;border:1px solid var(--border);border-radius:8px;line-height:1.7;margin:12px 0}.scene-rehearsal fieldset{display:flex;gap:16px;flex-wrap:wrap}.scene-rehearsal label{display:inline-flex;gap:8px;align-items:center;min-height:44px;margin-right:12px}.scene-rehearsal input[type=number]{width:4rem;min-height:40px}.scene-rehearsal button,.scene-rehearsal select{min-height:44px}.scene-rehearsal article{border-top:1px solid var(--border);padding:8px 0;overflow-wrap:anywhere}
</style>
