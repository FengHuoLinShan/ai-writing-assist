<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../bridge/index.js"
import { ACCOUNT_INVALIDATED_EVENT } from "../../shared/accountStorage.js"

const props = defineProps({ targetId: { type: String, default: "" }, interaction: Boolean, standalone: Boolean })
const emit = defineEmits(["locate"])
const available = ref(false), policy = ref(null), notices = ref([]), error = ref("")
const busy = ref(false), saved = ref(false), pending = ref(0), overflow = ref(false), active = ref(false)
const rechecks = new Map(), statusMessage = ref("")
let generation = 0
const api = () => getApi()?.[props.interaction ? "interactions" : "assistant"]
const unread = computed(() => notices.value.filter(item => item.status === "unread" && !item.needs_recheck).length)
const choices = computed(() => props.interaction ? [["interaction", "旅程连续性"]] : [["writing", "正文"], ["world", "世界资料"], ["story", "故事结构"], ["imports", "导入整理"]])
async function load() {
  const token = ++generation, target = props.targetId
  available.value = false; notices.value = []; policy.value = null; saved.value = false; error.value = ""
  statusMessage.value = ""
  if (!target || !api()?.carePolicy) return
  try {
    const settings = await api().carePolicy(target)
    if (token !== generation) return
    available.value = settings.available
    policy.value = settings.policy
    if (policy.value.web_backend !== "searxng-v1") policy.value.allow_web = false
    pending.value = settings.pending_count; overflow.value = settings.overflow; active.value = Boolean(settings.active_run_id)
    if (!available.value) return
    const result = await api().careNotices(target)
    if (token === generation) notices.value = result.items
  } catch { if (token === generation) error.value = "提醒暂时无法读取，可稍后刷新。" }
}
async function save() {
  const token = generation, target = props.targetId, snapshot = JSON.parse(JSON.stringify(policy.value))
  snapshot.web_backend = snapshot.allow_web ? "searxng-v1" : null
  busy.value = true; saved.value = false; error.value = ""
  try {
    const result = await api().saveCarePolicy(target, snapshot)
    if (token === generation) { policy.value = result.policy; saved.value = true }
  } catch { if (token === generation) error.value = "设置未保存，请重试；本次选择仍保留。" }
  finally { if (token === generation) busy.value = false }
}
async function refresh() {
  const token = generation
  busy.value = true; error.value = ""
  try {
    const result = await api().careNotices(props.targetId)
    if (token === generation) notices.value = result.items
  } catch { if (token === generation) error.value = "提醒暂时无法读取，请稍后重试。" }
  finally { if (token === generation) busy.value = false }
}
async function recheck(notice) {
  const token = generation, target = props.targetId, key = `${target}:${notice.id}`
  if (!rechecks.has(key)) rechecks.set(key, crypto.randomUUID())
  busy.value = true; error.value = ""
  try {
    const result = await api().recheckCareNotice(target, notice.id, rechecks.get(key))
    if (token === generation) {
      statusMessage.value = result.status === "running" ? "这处内容正在检查。" : "已排入新一轮检查，仍受项目每日额度限制。"
      rechecks.delete(key)
    }
  } catch (errorValue) { if (token === generation) error.value = errorValue.message || "重新检查未提交，请重试。" }
  finally { if (token === generation) busy.value = false }
}
async function decide(notice, action) {
  const token = generation, target = props.targetId
  busy.value = true; error.value = ""
  const disposition = { action }
  if (action === "snooze") disposition.until = new Date(Date.now() + 86400000).toISOString()
  try {
    await api().decideCareNotice(target, notice.id, disposition)
    if (token !== generation) return
    if (action === "read") notice.status = "read"
    else notices.value = notices.value.filter(item => item.id !== notice.id)
  } catch { if (token === generation) error.value = "处理结果未确认，请重试。" }
  finally { if (token === generation) busy.value = false }
}
function reset() { generation++; notices.value = []; policy.value = null; available.value = false; busy.value = false; error.value = "" }
globalThis.addEventListener?.(ACCOUNT_INVALIDATED_EVENT, reset)
watch(() => [props.targetId, props.interaction], () => { busy.value = false; void load() }, { immediate: true })
onBeforeUnmount(() => { reset(); globalThis.removeEventListener?.(ACCOUNT_INVALIDATED_EVENT, reset) })
</script>

<template>
  <details v-if="available || error" class="proactive-care" :class="{ 'proactive-care--standalone': standalone }" :open="standalone">
    <summary>回访与提醒<span v-if="unread"> · {{ unread }} 项待看</span></summary>
    <div class="proactive-care-body">
      <p v-if="error" role="alert">{{ error }}</p>
      <button v-if="!policy" type="button" @click="load">重新读取</button>
      <p v-if="active" role="status">正在检查最近的变化，结果会留在这里。</p>
      <p v-if="statusMessage" role="status">{{ statusMessage }}</p>
      <p v-else-if="pending">最近的变化已排入检查。</p>
      <p v-if="overflow">积累的变化较多，部分内容需要你手动发起深入检查。</p>
      <p v-if="!notices.length">当前没有需要查看的提醒。没有提醒不代表已经全面检查。</p>
      <article v-for="notice in notices" :key="notice.id" class="proactive-care-notice">
        <strong>{{ notice.title }}</strong><p>{{ notice.summary }}</p>
        <p v-if="notice.needs_recheck">来源后来有变化，请以当前内容为准。</p>
        <div class="proactive-care-actions">
          <button type="button" :disabled="busy" @click="emit('locate', notice.source)">查看来源</button>
          <button v-if="notice.can_recheck" type="button" :disabled="busy || !policy?.enabled" @click="recheck(notice)">重新检查（使用新额度）</button>
          <button v-if="notice.status === 'unread'" type="button" :disabled="busy" @click="decide(notice, 'read')">已看过</button>
          <button type="button" :disabled="busy" @click="decide(notice, 'snooze')">明天提醒</button>
          <button type="button" :disabled="busy" @click="decide(notice, 'intentional')">这是刻意安排</button>
          <button type="button" :disabled="busy" @click="decide(notice, 'ignore')">忽略</button>
        </div>
      </article>
      <details><summary>主动服务设置</summary>
        <form v-if="policy" @submit.prevent="save">
          <fieldset :disabled="busy">
            <legend>检查范围与额度</legend>
            <label><input v-model="policy.enabled" type="checkbox" @change="saved = false">内容变化后主动检查</label>
            <p>开启后，允许在后台读取当前作品中所选类别的资料，使用当前账户模型检查变化；沿用已设置的排除范围和角色可见边界。不会自动修改内容。</p>
            <label v-for="[value, label] in choices" :key="value"><input v-model="policy.categories" type="checkbox" :value="value" @change="saved = false">{{ label }}</label>
            <label><input v-model="policy.allow_web" type="checkbox" @change="saved = false">允许通过本站搜索服务查证通用事实</label>
            <p>仅向上游搜索网站发送通用问题并读取公开网页，不发送作品原文。</p>
            <label>每日最多检查 <input v-model.number="policy.daily_limit" type="number" min="1" max="100" required @input="saved = false"> 次</label>
            <p>连续修改会合并；普通保存稳定一分钟后开始。同一处十分钟内合并，达到额度后等待次日。费用按供应商实际用量计算。</p>
            <button type="submit">{{ busy ? '正在保存…' : '保存设置' }}</button>
          </fieldset>
          <p v-if="saved" role="status">设置已保存。</p>
        </form>
      </details>
      <button v-if="policy" type="button" :disabled="busy" @click="refresh">刷新提醒</button>
    </div>
  </details>
</template>

<style scoped>
.proactive-care--standalone{flex:1;min-height:0;overflow:auto}.proactive-care--standalone .proactive-care-body{max-height:none;overflow:visible}.proactive-care{padding:8px 16px;border-bottom:1px solid var(--border-color,var(--border));font-size:13px;line-height:1.65;color:inherit}
summary{cursor:pointer;min-height:36px;display:list-item;align-content:center}.proactive-care-body{max-height:42vh;overflow:auto;overscroll-behavior:contain;padding-bottom:8px}
p{overflow-wrap:anywhere}.proactive-care-notice{border-bottom:1px solid var(--border-color,var(--border));padding:10px 0}.proactive-care-actions{display:flex;gap:8px;flex-wrap:wrap}
button{font:inherit;color:inherit;background:var(--bg-secondary,transparent);border:1px solid var(--border-color,var(--border));border-radius:6px;padding:6px 10px;min-height:36px;cursor:pointer}
fieldset{border:0;padding:8px 0;min-width:0}label{display:block;padding:4px 0}input[type=number]{width:5em;font:inherit;color:inherit;background:transparent;border:1px solid var(--border-color,var(--border));padding:4px}
input[type=checkbox]{margin-right:6px}button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid var(--accent,#7762e8);outline-offset:3px}
@media(max-width:800px){button,summary{min-height:44px}input[type=checkbox]{width:18px;height:18px}input[type=number]{font-size:16px}}
</style>
