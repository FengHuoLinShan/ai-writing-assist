<template>
  <section v-if="sceneId" class="map-dynamic-section scene-memory-repair" data-testid="scene-memory-repair" :aria-busy="loading || saving">
    <div class="scene-memory-heading">
      <div><h4>阶段状态</h4><p>{{ sceneTitle }} · 只使用此 Scene 及之前的已确认事实</p></div>
      <span class="badge" :class="{ 'is-warning': needsRepair }">{{ statusLabel }}</span>
    </div>
    <p v-if="loading" class="map-muted-text" role="status">正在核对阶段状态...</p>
    <div v-else-if="error" class="alert alert-warning" role="alert"><span>{{ error }}</span><button class="btn btn-sm" @click="load">重试</button></div>
    <template v-else-if="checkpointSet">
      <div class="scene-memory-dimensions" role="group" aria-label="阶段状态维度">
        <button v-for="item in checkpointSet.items" :key="item.dimension" class="scene-memory-dimension" :class="{ 'is-active': selected?.dimension === item.dimension, 'needs-attention': item.status !== 'ready' }" :aria-pressed="selected?.dimension === item.dimension" @click="selectedDimension = item.dimension">
          <span>{{ dimensionLabel(item.dimension) }}</span><small>{{ item.status === "ready" ? "完整" : "待修复" }}</small>
        </button>
      </div>
      <article v-if="selected" class="map-dynamic-item scene-memory-current">
        <div class="scene-memory-kicker">当前事实</div><strong>{{ selected.display_summary || "此阶段没有记录到事实" }}</strong>
        <p v-if="selected.gap_reason" class="scene-memory-gap">{{ selected.gap_reason }}</p>
        <details v-if="selected.evidence_refs?.length" class="scene-memory-evidence"><summary>查看来源证据 {{ selected.evidence_refs.length }} 条</summary><ul><li v-for="ref in selected.evidence_refs.slice(0, 8)" :key="`${ref.type}:${ref.id}`">{{ ref.label || ref.type }}</li></ul></details>
      </article>
      <form v-if="selected?.status !== 'ready'" class="scene-memory-decision" @submit.prevent="submitRepair">
        <div class="scene-memory-kicker">你的决定</div>
        <label><input v-model="decision" type="radio" value="keep_current" /> 当前事实正确，直接采用</label>
        <label><input v-model="decision" type="radio" value="replace_with_summary" /> 用我填写的正确内容替换</label>
        <textarea v-if="decision === 'replace_with_summary'" v-model="replacementSummary" class="form-textarea" rows="4" placeholder="用自然语言写清这一阶段的正确事实；无需填写 ID 或技术字段。" aria-label="填写正确的阶段事实" />
        <label><input v-model="decision" type="radio" value="confirm_empty" /> 这一阶段确实没有此类事实</label>
        <textarea v-model="decisionSummary" class="form-textarea" rows="2" placeholder="简要说明判断依据，便于以后回看。" aria-label="说明判断依据" />
        <button class="btn btn-primary scene-memory-primary" type="submit" :disabled="saving">{{ saving ? "正在修复并重建..." : "确认修复并重建后续阶段" }}</button>
        <p class="map-muted-text">只替换当前 Scene 的系统结果；人工确认内容会保留，后续阶段自动重建。</p>
      </form>
    </template>
  </section>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { getApi, getToast } from "../../../bridge/index.js"

const props = defineProps({ projectId: { type: String, required: true }, sceneId: { type: String, default: null } })
const api = getApi()
const toast = getToast()
const loading = ref(false)
const saving = ref(false)
const error = ref("")
const checkpointSet = ref(null)
const selectedDimension = ref(null)
const decision = ref("keep_current")
const decisionSummary = ref("")
const replacementSummary = ref("")
let generation = 0

const sceneTitle = computed(() => checkpointSet.value?.scene_title || `Scene ${checkpointSet.value?.scene_index ?? ""}`)
const selected = computed(() => checkpointSet.value?.items?.find((item) => item.dimension === selectedDimension.value) || checkpointSet.value?.items?.find((item) => item.status !== "ready") || checkpointSet.value?.items?.[0] || null)
const needsRepair = computed(() => checkpointSet.value?.coverage_status !== "ready")
const statusLabel = computed(() => needsRepair.value ? "需要判断" : "状态完整")
function dimensionLabel(value) { return ({ entities: "人物与对象", relations: "关系", locations: "人物位置", knowledge: "知识边界", map: "地图事实" })[value] || value }

async function load() {
  const token = ++generation
  if (!props.sceneId) { checkpointSet.value = null; return }
  loading.value = true; error.value = ""
  try {
    const result = await api.memory.ensureSceneCheckpoints(props.projectId, props.sceneId)
    if (token !== generation) return
    checkpointSet.value = result
    selectedDimension.value = result.items?.find((item) => item.status !== "ready")?.dimension || result.items?.[0]?.dimension || null
  } catch (cause) { if (token === generation) error.value = cause?.message || "阶段状态加载失败" }
  finally { if (token === generation) loading.value = false }
}

async function submitRepair() {
  if (!selected.value || saving.value) return
  if (decisionSummary.value.trim().length < 2) { toast("请简要说明判断依据", "warning"); return }
  if (decision.value === "replace_with_summary" && !replacementSummary.value.trim()) { toast("请填写正确内容", "warning"); return }
  saving.value = true
  try {
    await api.memory.repairSceneCheckpoint(props.projectId, { scene_id: props.sceneId, dimension: selected.value.dimension, expected_checkpoint_id: selected.value.id, decision: decision.value, decision_summary: decisionSummary.value.trim(), replacement_summary: replacementSummary.value.trim() || null, confirmed: true })
    toast("阶段状态已修复，后续阶段已重建", "success")
    decision.value = "keep_current"; decisionSummary.value = ""; replacementSummary.value = ""
    await load()
  } catch (cause) {
    if (cause?.status === 409) {
      toast("阶段事实已更新，请核对最新内容后再确认", "warning")
      await load()
    } else {
      toast(`修复失败：${cause?.message || "未知错误"}`, "error")
    }
  }
  finally { saving.value = false }
}

watch(() => [props.projectId, props.sceneId], load, { immediate: true })
</script>

<style scoped>
.scene-memory-repair { border-top: 1px solid var(--border); padding-top: var(--space-4); }
.scene-memory-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.scene-memory-heading h4 { margin: 0; }
.scene-memory-heading p { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--text-xs); line-height: 1.5; }
.scene-memory-dimensions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin: 12px 0; }
.scene-memory-dimension { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); color: inherit; padding: var(--space-2) var(--space-3); text-align: left; cursor: pointer; }
.scene-memory-dimension span, .scene-memory-dimension small { display: block; }
.scene-memory-dimension small { margin-top: var(--space-1); color: var(--text-secondary); }
.scene-memory-dimension.is-active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.scene-memory-dimension.needs-attention small, .scene-memory-gap { color: var(--danger); }
.scene-memory-current { cursor: default; }
.scene-memory-current strong { display: block; margin-top: 5px; line-height: 1.55; }
.scene-memory-kicker { color: var(--text-secondary); font-size: var(--text-xs); letter-spacing: .08em; }
.scene-memory-evidence { margin-top: 10px; }
.scene-memory-evidence summary { cursor: pointer; color: var(--accent); }
.scene-memory-evidence ul { margin: 8px 0 0; padding-left: 18px; }
.scene-memory-decision { display: grid; gap: var(--space-3); margin-top: var(--space-3); padding: var(--space-3); border-radius: var(--radius-md); background: var(--accent-soft); }
.scene-memory-decision label { display: flex; gap: 8px; align-items: flex-start; line-height: 1.4; }
.scene-memory-primary { width: 100%; justify-content: center; }
@media (max-width: 560px) { .scene-memory-dimensions { grid-template-columns: 1fr; } }
</style>
