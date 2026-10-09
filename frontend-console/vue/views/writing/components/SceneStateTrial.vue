<template>
  <details class="scene-state-trial" @toggle="result = null">
    <summary>比较钥匙交接与开锁条件</summary>
    <p>只检查已有依据和这次假设，不改变原稿、世界设定或人物知识。</p>
    <form @submit.prevent="compare">
      <label>行动<select aria-label="行动" v-model="form.action"><option value="transfer_key">交出钥匙</option><option value="open_lock">尝试开锁</option></select></label>
      <label>行动人物<select aria-label="行动人物" v-model="form.actor_id" required><option value="" disabled>选择人物</option><option v-for="(name, id) in choices" :key="id" :value="id">{{ name }}</option></select></label>
      <label>钥匙<select aria-label="钥匙" v-model="form.key_id" required><option value="" disabled>选择钥匙</option><option v-for="item in objects" :key="item.subject_id" :value="item.subject_id">{{ item.label }}</option></select></label>
      <label v-if="form.action === 'transfer_key'">交给谁<select aria-label="交给谁" v-model="form.recipient_id" required><option value="" disabled>选择人物</option><option v-for="(name, id) in choices" :key="id" :value="id">{{ name }}</option></select></label>
      <label v-else>要开启的锁<select aria-label="要开启的锁" v-model="form.lock_id" required><option value="" disabled>选择锁</option><option v-for="item in objects" :key="item.subject_id" :value="item.subject_id">{{ item.label }}</option></select></label>
      <label>试改后的保管人<select aria-label="试改后的保管人" v-model="form.candidate_holder_id"><option value="">沿用已有记录</option><option v-for="(name, id) in choices" :key="id" :value="id">{{ name }}</option></select></label>
      <label v-if="form.action === 'open_lock'">试改月相<select aria-label="试改月相" v-model="form.candidate_moon_phase"><option value="">沿用已有记录</option><option value="full">假设月圆</option><option value="other">假设非月圆</option></select></label>
      <button type="submit" class="btn btn-sm" :disabled="busy">{{ busy ? '正在核对…' : '比较原状态与本次假设' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="result">
      <p>{{ result.authority }}</p>
      <div class="scene-trial-comparison">
        <section v-for="[key, label] in [['baseline', '原状态'], ['candidate', '本次假设']]" :key="key"><h5>{{ label }} · {{ outcomes[result[key].outcome] }}</h5><ul><li v-for="(condition, index) in result[key].conditions" :key="index">{{ condition.label }}：{{ statuses[condition.status] }}{{ condition.assumption ? '（本次假设）' : '' }}<small>当前：{{ condition.observed }}；所需：{{ condition.expected }}</small> <button v-if="condition.source?.checkpoint_id" type="button" class="btn btn-sm" @click="$emit('source', condition.source)">查看依据</button></li></ul><p>比较后的保管人：{{ result[key].resource_state.holder }}；所有人：{{ result[key].resource_state.owner }}</p></section>
      </div>
      <p v-for="note in [...result.assumptions, ...result.not_checked]" :key="note">{{ note }}</p>
      <button type="button" class="btn btn-sm" @click="$emit('start-trial', { ...request(), comparison_digest: result.comparison_digest })">按这个假设发起原稿试改</button>
    </template>
  </details>
</template>
<script setup>
import { reactive, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"
const props = defineProps({ projectId: String, sceneId: String, fingerprint: String, choices: { type: Object, default: () => ({}) }, objects: { type: Array, default: () => [] } })
defineEmits(["source", "start-trial"])
const form = reactive({ action: "transfer_key", actor_id: "", key_id: "", recipient_id: "", lock_id: "", candidate_holder_id: "", candidate_moon_phase: "" })
const busy = ref(false), result = ref(null), error = ref("")
const outcomes = { succeeded: "明确条件已满足", failed: "明确条件未满足", uncertain: "依据不足，仍不确定" }
const statuses = { met: "满足", unmet: "未满足", unknown: "尚无可靠依据" }
let generation = 0
watch(() => [props.projectId, props.sceneId, props.fingerprint], () => { generation++; result.value = null; error.value = ""; busy.value = false })
watch(form, () => { generation++; result.value = null; busy.value = false })
function request() { return { scene_id: props.sceneId, state_fingerprint: props.fingerprint, ...Object.fromEntries(Object.entries(form).filter(([key, value]) => value && !(key === "lock_id" && form.action !== "open_lock") && !(key === "recipient_id" && form.action !== "transfer_key"))) } }
async function compare() {
  const token = ++generation
  busy.value = true; error.value = ""
  try { const value = await getApi().story.compareSceneStateTrial(props.projectId, request()); if (token === generation) result.value = value }
  catch (cause) { if (token === generation) error.value = cause.message || "比较未完成，请刷新本场后重试。" }
  finally { if (token === generation) busy.value = false }
}
</script>
<style scoped>
.scene-state-trial{margin-top:12px}.scene-state-trial label{display:block;margin:8px 0}.scene-state-trial select{display:block;width:100%;min-height:40px}.scene-trial-comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.scene-trial-comparison ul{padding-left:18px}.scene-trial-comparison h5{margin-bottom:5px}@media(max-width:700px){.scene-trial-comparison{grid-template-columns:1fr}}
</style>
