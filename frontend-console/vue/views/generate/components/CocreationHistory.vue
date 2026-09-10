<template>
  <WorkspaceDrawer :mobile="true" :open="open" title="历史与决定" @close="$emit('close')">
    <div class="cocreation-history">
      <div class="cocreation-history__actions">
        <button class="btn" type="button" @click="mode = 'sessions'; loadSessions()">会话目录</button>
        <button class="btn" type="button" :disabled="!sessionId" @click="viewSession({ id: sessionId, title: sessionTitle })">当前会话的完整历史</button>
        <button class="btn" type="button" @click="$emit('new-session')">新建会话</button>
      </div>
      <form role="search" @submit.prevent="search">
        <label>{{ mode === 'sessions' ? '搜索会话名称' : '搜索历史内容' }}<input v-model="query" type="search" /></label>
        <button class="btn" type="submit">搜索</button>
        <button v-if="query" class="btn btn-ghost" type="button" @click="query = ''; search()">清除</button>
      </form>
      <template v-if="mode === 'messages'"><h3>{{ viewed?.title || '会话历史' }}</h3><p>浏览不会改变本轮输入；只有明确选中的历史会加入参考。已选 {{ selectedIds.length }}/40 条。</p></template>
      <section v-if="taskPreview">
        <button type="button" class="btn" @click="taskPreview = null">返回历史</button>
        <button v-if="viewed?.id === sessionId && taskPreview.proposal.parent_checkpoint_id === checkpointId" type="button" class="btn" @click="emit('restore-preview', taskPreview)">载入当前工作区编辑</button>
        <WorldDesignPanel :checkpoint="taskPreview.checkpoint" :proposal="taskPreview.proposal" :read-only="true" :historical="true" />
      </section>
      <p v-else-if="loading" role="status">正在读取历史…</p>
      <div v-else-if="error" role="alert"><p>{{ error }}</p><button class="btn" type="button" @click="reload">重试</button></div>
      <template v-else>
        <p v-if="!items.length">{{ query ? '没有找到匹配记录，可以调整搜索词。' : '这里还没有记录。' }}</p>
        <article v-for="item in items" :key="item.id" :data-history-message="mode === 'messages' ? item.id : undefined" :class="{ 'is-focused': item.id === focusedId }">
          <template v-if="mode === 'sessions'">
            <h3>{{ item.title }} <span v-if="item.id === sessionId" class="badge">当前会话</span></h3><p>{{ item.status === 'archived' ? '已归档' : '讨论中' }} · {{ date(item.last_message_at || item.created_at) }}</p>
            <div class="cocreation-history__actions">
              <button class="btn" type="button" @click="viewSession(item)">阅读历史</button>
              <button v-if="item.status === 'active'" class="btn" type="button" :disabled="item.id === sessionId" @click="$emit('switch-session', item)">继续共创</button>
              <button class="btn btn-ghost" type="button" :disabled="mutating" @click="toggleArchive(item)">{{ item.status === 'archived' ? '恢复会话' : '归档' }}</button>
            </div>
          </template>
          <template v-else>
            <strong>{{ item.kind === 'decision' ? '作者决定' : item.role === 'author' ? '作者' : '共创回复' }}</strong><small> · {{ date(item.created_at) }}</small>
            <p class="cocreation-history__text">{{ expanded.has(item.id) ? item.content : item.content.slice(0, 500) }}</p>
            <div class="cocreation-history__actions">
              <button v-if="item.content.length > 500" class="btn btn-sm" type="button" @click="toggleExpanded(item.id)">{{ expanded.has(item.id) ? '收起全文' : '展开全文' }}</button>
              <button v-if="query" class="btn btn-sm" type="button" @click="around(item)">查看前后文</button>
              <label v-if="viewed.id === sessionId"><input type="checkbox" :checked="selectedIds.includes(item.id)" :disabled="!selectedIds.includes(item.id) && selectedIds.length >= 40" @change="toggleSelection(item.id, $event.target.checked)" />本轮参考</label>
              <button v-if="item.outcome_kind === 'world_design_preview' && item.task_id" class="btn btn-sm" type="button" @click="readTaskPreview(item)">查看推演预览</button>
              <button v-if="item.outcome_suggestion_id" class="btn btn-sm" type="button" @click="$emit('open-outcome', item)">查看成果</button>
            </div>
          </template>
        </article>
        <nav v-if="total > size" aria-label="历史分页" class="cocreation-history__actions">
          <button class="btn" type="button" :disabled="offset === 0" @click="page(Math.max(0, offset - size))">上一页</button>
          <span>{{ offset + 1 }}–{{ Math.min(total, offset + items.length) }} / {{ total }}</span>
          <button class="btn" type="button" :disabled="offset + items.length >= total" @click="page(offset + size)">下一页</button>
          <button class="btn btn-ghost" type="button" @click="page(Math.max(0, Math.floor((total - 1) / size) * size))">最后一页</button>
        </nav>
      </template>
    </div>
  </WorkspaceDrawer>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import WorkspaceDrawer from '../../../components/WorkspaceDrawer.vue'
import WorldDesignPanel from './WorldDesignPanel.vue'
import { getApi, getConfirm } from '../../../bridge/index.js'

const props = defineProps({ open: Boolean, projectId: String, sessionId: String, sessionTitle: String, checkpointId: String, source: Object, preset: String, targetKind: String, selectedIds: { type: Array, default: () => [] } })
const emit = defineEmits(['restore-preview', 'close', 'new-session', 'switch-session', 'update:selectedIds', 'open-outcome'])
const api = getApi(); const confirm = getConfirm()
const mode = ref('sessions'); const query = ref(''); const viewed = ref(null); const items = ref([]); const offset = ref(0); const total = ref(0); const loading = ref(false); const mutating = ref(false); const error = ref(''); const expanded = ref(new Set()); const focusedId = ref(null)
const taskPreview = ref(null)
const size = 30
let generation = 0
function date(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '' }
async function load(aroundId) {
  const turn = ++generation; loading.value = true; error.value = ''
  try {
    const data = mode.value === 'sessions'
      ? await api.world.listCocreationSessions(props.projectId, { source_kind: props.source.kind, ...(props.source.id ? { source_id: props.source.id } : {}), workflow_preset: props.preset, target_kind: props.targetKind, include_archived: true, limit: size, skip: offset.value, search: query.value || undefined })
      : await api.world.listCocreationMessages(viewed.value.id, props.projectId, { limit: size, skip: offset.value, search: query.value || undefined, ...(aroundId ? { around_message_id: aroundId } : {}) })
    if (turn !== generation || !props.open) return
    items.value = data.items || []; total.value = data.total || 0; if (Number.isInteger(data.offset)) offset.value = data.offset
  } catch (err) { if (turn === generation) error.value = err?.message || '历史暂时无法读取' }
  finally { if (turn === generation) loading.value = false }
}
function loadSessions() { taskPreview.value = null; query.value = ''; offset.value = 0; return load() }
function viewSession(item) { taskPreview.value = null; mode.value = 'messages'; viewed.value = item; query.value = ''; offset.value = 0; focusedId.value = null; return load() }
async function readTaskPreview(item) {
  const token = ++generation; const projectId = props.projectId; loading.value = true; error.value = ''
  try {
    const task = await api.tasks.get(item.task_id, projectId)
    if (token !== generation || !props.open) return
    if (task.status !== 'done' || task.result?.mode !== 'design' || task.meta?.session_id !== viewed.value.id) throw new Error('这份推演预览不可用')
    const parent = await api.world.getAdoptionArtifact(task.result.parent_checkpoint_id, projectId)
    if (token !== generation || !props.open) return
    taskPreview.value = { checkpoint: parent.payload_json, proposal: { ...task.result, originTaskId: item.task_id, action: task.meta.session_action } }
  } catch (err) { if (token === generation) error.value = err?.message || '预览读取失败' }
  finally { if (token === generation) loading.value = false }
}
function reload() { return load() }
function search() { offset.value = 0; focusedId.value = null; return load() }
function page(value) { offset.value = value; return load() }
async function around(item) { query.value = ''; focusedId.value = item.id; await load(item.id); await nextTick(); document.querySelector(`[data-history-message="${CSS.escape(item.id)}"]`)?.scrollIntoView({ block: 'nearest' }) }
function toggleExpanded(id) { const next = new Set(expanded.value); if (next.has(id)) next.delete(id); else next.add(id); expanded.value = next }
function toggleSelection(id, checked) { emit('update:selectedIds', checked ? [...new Set([...props.selectedIds, id])].slice(0, 40) : props.selectedIds.filter(item => item !== id)) }
async function toggleArchive(item) {
  const archived = item.status !== 'archived'
  if (archived && !confirm(`归档“${item.title}”？历史会继续保留。`)) return
  mutating.value = true; const project = props.projectId
  try { await api.world.updateCocreationSession(item.id, { novel_id: project, archived }); if (props.open && project === props.projectId) await load() }
  catch (err) { if (project === props.projectId) error.value = err?.message || '会话状态未能保存' }
  finally { mutating.value = false }
}
watch(() => props.open, (open) => { if (open) void load(); else generation++ }, { immediate: true })
watch(() => props.projectId, () => { generation++; mode.value = 'sessions'; viewed.value = null; query.value = ''; offset.value = 0; items.value = []; if (props.open) void load() })
onBeforeUnmount(() => { generation++ })
</script>

<style scoped>
.cocreation-history { display: grid; gap: var(--space-4, 16px); min-width: 0; }
.cocreation-history article { border-bottom: 1px solid var(--border); padding-block: var(--space-3, 12px); overflow-wrap: anywhere; }
.cocreation-history__actions, .cocreation-history form { display: flex; gap: var(--space-2, 8px); flex-wrap: wrap; align-items: center; }
.cocreation-history label { display: grid; gap: var(--space-2, 8px); }
.cocreation-history__actions label { display: flex; align-items: center; min-height: 44px; }
.cocreation-history__text { white-space: pre-wrap; line-height: 1.85; }
.cocreation-history .is-focused { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>
