<template>
  <section class="world-stress-report" aria-label="世界观压力测试报告">
    <header><h2>世界观压力测试</h2><button type="button" class="btn btn-sm" @click="$emit('close')">返回资料</button></header>
    <p v-if="error" role="alert">{{ error }}</p><button v-if="error" class="btn" :disabled="busy || loading" @click="load">重新读取</button>
    <p v-if="loading" role="status">正在读取情境与核查结论…</p>
    <p v-if="busy" role="status">正在处理，请稍候…</p>
    <template v-if="report">
      <p v-if="report.freshness === 'stale'" role="alert">原规则已变化，以下保留为历史对照，请重新测试。</p>
      <p>{{ report.assessment.summary }}</p><p class="muted">{{ report.authority }}</p>
      <p v-if="report.preserved_constraints?.length">作者保留：{{ report.preserved_constraints.join('、') }}</p>
      <ul><li v-for="omission in report.assessment.omissions" :key="omission">{{ omission }}</li></ul>
      <article v-for="scenario in report.assessment.scenarios" :key="scenario.key">
        <h3>{{ scenario.title }} · {{ verdicts[scenario.verdict] }}</h3><p><strong>检查规则：</strong>{{ scenario.invariant }}</p>
        <p v-if="scenario.assumptions.length"><strong>额外假设：</strong>{{ scenario.assumptions.join('；') }}</p>
        <ol><li v-for="(action, index) in scenario.actions" :key="index">{{ action }}</li></ol>
        <p>{{ scenario.outcome }}</p><p>{{ scenario.reason }}</p><p v-if="scenario.repair"><strong>可选修法：</strong>{{ scenario.repair }}</p>
        <p v-if="scenario.costs.length">代价：{{ scenario.costs.join('；') }}</p>
        <p v-if="report.dispositions?.[scenario.key]" role="status">你的决定：{{ dispositions[report.dispositions[scenario.key].disposition] }}。{{ report.dispositions[scenario.key].note }}</p>
        <div class="world-stress-report-actions"><button v-for="(label, key) in dispositions" :key="key" type="button" class="btn btn-sm" :disabled="busy || loading" @click="decide(scenario.key, key)">{{ label }}</button></div>
        <button type="button" class="btn btn-sm" :disabled="busy || loading" @click="retest(scenario.key)">只重测这一情境</button>
      </article>
      <details v-if="report.previous_scenarios?.length"><summary>对照上一版情境</summary><p v-for="scenario in report.previous_scenarios" :key="scenario.key">{{ scenario.title }}：{{ verdicts[scenario.verdict] }}。{{ scenario.outcome }}</p></details>
      <button class="btn btn-primary" :disabled="busy || loading" @click="retest()">按当前规则重新测试</button>
    </template>
  </section>
</template>

<script setup>
import { ref, watch } from "vue"
import { getApi, openProjectAssistant } from "../../../bridge/index.js"
const props = defineProps({ projectId: { type: String, required: true }, reportId: { type: String, required: true } })
defineEmits(["close"])
const report = ref(null), error = ref(""), loading = ref(false), busy = ref(false)
const verdicts = { valid_counterexample: "反例成立", invalid_counterexample: "前提不成立", uncertain: "仍待核查", no_counterexample: "该情境未发现反例" }
const dispositions = { intentional: "有意保留", rejected: "不接受此反例", investigate: "继续查证", resolved: "已自行处理" }
let generation = 0
async function load() {
  const token = ++generation
  loading.value = true
  busy.value = false
  report.value = null
  try { const value = await getApi().world.stressReport(props.projectId, props.reportId); if (token === generation) { report.value = value; error.value = "" } }
  catch (cause) { if (token === generation) error.value = cause.message || "压力测试报告暂不可用。" }
  finally { if (token === generation) loading.value = false }
}
async function decide(key, disposition) {
  if (busy.value || loading.value || !report.value) return
  const token = generation
  busy.value = true
  try { const value = await getApi().world.decideStressScenario(props.projectId, props.reportId, { expected_hash: report.value.assessment_hash, scenario_key: key, disposition }); if (token === generation) { report.value = value; error.value = "" } }
  catch (cause) { if (token === generation) error.value = cause.message || "决定尚未保存，请重试。" }
  finally { if (token === generation) busy.value = false }
}
async function retest(scenarioKey = null) {
  if (busy.value || loading.value || !report.value) return
  const token = generation
  busy.value = true
  try { await openProjectAssistant({ projectId: props.projectId, blueprint: "world_stress", previousReportId: props.reportId, scenarioKeys: scenarioKey ? [scenarioKey] : [], preservedConstraints: [...(report.value.preserved_constraints || []), ...Object.entries(report.value.dispositions || {}).filter(([, value]) => value.disposition === "intentional").map(([key]) => `保留情境：${report.value.assessment.scenarios.find(item => item.key === key)?.title || key}`)], context: report.value.source_scope || { page: "world", scope: "project", target: report.value.target_ref }, message: `重新测试当前规则。保留作者决定：${Object.entries(report.value.dispositions || {}).map(([key, value]) => `${report.value.assessment.scenarios.find(item => item.key === key)?.title || '既有情境'}：${dispositions[value.disposition]}`).join('；')}` }) }
  catch (cause) { if (token === generation) error.value = cause.message || "重测暂不可用。" }
  finally { if (token === generation) busy.value = false }
}
watch(() => [props.projectId, props.reportId], load, { immediate: true })
</script>

<style scoped>
.world-stress-report{max-width:72rem;margin:0 auto;padding:16px;line-height:1.7;overflow-wrap:anywhere}.world-stress-report header,.world-stress-report-actions{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.world-stress-report article{border-top:1px solid var(--border);padding:16px 0}.world-stress-report button{min-height:44px}.muted{color:var(--text-secondary)}
</style>
