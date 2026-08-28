<script setup>
import { computed, nextTick, ref } from "vue"
import { getRouter } from "../../../bridge/index.js"
import AuthorTaskForm from "./AuthorTaskForm.vue"
import { openAuthorTaskSource } from "./authorTaskSource.js"
import { useAuthorTasks } from "./useAuthorTasks.js"

const props = defineProps({
  projectId: { type: String, required: true },
  scope: { type: String, default: "today" },
  source: { type: Object, default: null },
})
const router = getRouter()
const activeScope = ["today", "inbox", "later", "completed", "archived"].includes(props.scope)
  ? props.scope
  : "today"
const tasks = useAuthorTasks(props.projectId, activeScope)
const formOpen = ref(Boolean(props.source))
const editingTask = ref(null)
const navigationBusy = computed(() => tasks.loading.value || tasks.busyIds.value.size > 0)
const heading = computed(() => activeScope === "archived" ? "已归档" : "我的任务")
const tabs = computed(() => [
  ["today", "今天", tasks.counts.value.today],
  ["inbox", "收件箱", tasks.counts.value.inbox],
  ["later", "之后", tasks.counts.value.later],
  ["completed", "已完成", tasks.counts.value.completed],
])

function navigateScope(scope) {
  router.navigate("writing", null, true, new URLSearchParams({ home: "1", panel: "tasks", scope }))
}

function clearTaskSource() {
  const query = new URLSearchParams({ home: "1", panel: "tasks", scope: activeScope })
  if (router.commitCurrentQuery?.(query, "replace") !== true) navigateScope(activeScope)
}

function openWritingHome() {
  router.navigate("writing", null, true, new URLSearchParams({ home: "1" }))
}

async function save(payload) {
  const editing = Boolean(editingTask.value)
  const ok = editing
    ? Boolean(await tasks.patch(editingTask.value, payload))
    : await tasks.create(payload)
  if (!ok) return
  formOpen.value = false
  editingTask.value = null
  tasks.clearConflict()
  if (!editing && props.source) clearTaskSource()
}

function edit(task) {
  tasks.clearConflict()
  editingTask.value = task
  formOpen.value = true
  nextTick(() => document.getElementById("author-task-title")?.focus())
}

function closeForm() {
  tasks.clearConflict()
  formOpen.value = false
  editingTask.value = null
}
</script>

<template>
  <main class="author-tasks" aria-labelledby="author-tasks-title">
    <header class="author-tasks__header">
      <div>
        <button type="button" class="btn btn-sm btn-ghost" :disabled="navigationBusy" @click="openWritingHome">← 写作首页</button>
        <h1 id="author-tasks-title">{{ heading }}</h1>
        <p>这是你主动安排的待办；“需要你决定”和后台整理仍在各自区域处理。</p>
      </div>
      <button type="button" class="btn btn-primary" :disabled="navigationBusy" @click="formOpen = true">＋ 添加任务</button>
    </header>

    <nav class="author-task-tabs" aria-label="任务视图">
      <button v-for="tab in tabs" :key="tab[0]" type="button" class="btn btn-sm" :disabled="navigationBusy" :aria-current="activeScope === tab[0] ? 'page' : undefined" @click="navigateScope(tab[0])">{{ tab[1] }} <span v-if="tab[2]">{{ tab[2] }}</span></button>
      <button type="button" class="btn btn-sm btn-ghost author-task-tabs__archive" :disabled="navigationBusy" :aria-current="activeScope === 'archived' ? 'page' : undefined" @click="navigateScope('archived')">已归档</button>
    </nav>

    <AuthorTaskForm v-if="formOpen" :task="editingTask" :source="editingTask?.source || source" :busy="tasks.loading.value" @submit="save" @cancel="closeForm" />
    <p v-if="tasks.conflict.value" class="author-task-conflict field-error" role="alert">{{ tasks.conflict.value.message }}</p>

    <div v-if="tasks.loadError.value" class="error-card" role="alert">
      <p>{{ tasks.loadError.value }}</p>
      <button type="button" class="btn btn-sm" @click="tasks.load">重新加载</button>
    </div>
    <p v-else-if="tasks.loading.value && !tasks.items.value.length" role="status">正在加载任务…</p>
    <div v-else-if="!tasks.items.value.length" class="empty-state">
      <p>{{ activeScope === 'completed' ? '还没有已完成任务。' : activeScope === 'archived' ? '没有已归档任务。' : '这里还没有任务。' }}</p>
      <button v-if="!['completed', 'archived'].includes(activeScope)" type="button" class="btn btn-sm" @click="formOpen = true">添加第一项</button>
    </div>
    <ul v-else class="author-task-list">
      <li v-for="task in tasks.items.value" :key="task.id" class="author-task-row">
        <label
          v-if="task.status !== 'archived'"
          class="author-task-row__check"
        >
          <input
            type="checkbox"
            :checked="task.status === 'completed'"
            :disabled="tasks.busyIds.value.has(task.id)"
            :aria-label="task.status === 'completed' ? `重开任务：${task.title}` : `完成任务：${task.title}`"
            @change="tasks.patch(task, { status: task.status === 'completed' ? 'open' : 'completed' })"
          >
        </label>
        <div class="author-task-row__copy">
          <strong>{{ task.title }}</strong>
          <p v-if="task.note">{{ task.note }}</p>
          <span v-if="task.due_date">{{ task.due_date }}</span>
          <button v-if="task.source?.available" type="button" class="author-task-source" @click="openAuthorTaskSource(task.source, router)">{{ task.source.label }} →</button>
          <span v-else-if="task.source" class="author-task-source is-missing">来源已失效</span>
        </div>
        <div class="author-task-row__actions">
          <button v-if="task.source && !task.source.available" type="button" class="btn btn-sm btn-ghost" @click="tasks.patch(task, { source: null })">清除来源</button>
          <button v-if="task.status !== 'archived'" type="button" class="btn btn-sm" @click="edit(task)">编辑</button>
          <button v-if="task.status !== 'archived'" type="button" class="btn btn-sm btn-ghost" @click="tasks.patch(task, { status: 'archived' })">归档</button>
          <button v-else type="button" class="btn btn-sm" @click="tasks.patch(task, { status: 'open' })">恢复</button>
        </div>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.author-tasks { max-width: 960px; margin: 0 auto; padding: 24px; }
.author-tasks__header { display: flex; justify-content: space-between; gap: 20px; align-items: end; }
.author-tasks__header h1 { margin: 10px 0 4px; }
.author-tasks__header p { margin: 0; color: var(--text-muted); }
.author-task-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 16px; }
.author-task-tabs__archive { margin-left: auto; }
.author-task-list { display: grid; gap: 10px; padding: 0; list-style: none; }
.author-task-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 12px; align-items: start; padding: 14px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); }
.author-task-row__check { display: grid; width: 44px; height: 44px; place-items: center; cursor: pointer; }
.author-task-row__check input { width: 20px; height: 20px; }
.author-task-row__copy { min-width: 0; display: grid; gap: 5px; }
.author-task-row__copy p, .author-task-row__copy span { margin: 0; color: var(--text-muted); overflow-wrap: anywhere; }
.author-task-row__actions { display: flex; flex-wrap: wrap; justify-content: end; gap: 6px; }
.author-task-source { width: fit-content; padding: 0; border: 0; color: var(--accent); background: transparent; text-align: left; text-decoration: underline; cursor: pointer; }
.author-task-source.is-missing { color: var(--text-muted); text-decoration: none; }
.author-task-conflict { margin: 0 0 12px; color: var(--danger); }
@media (max-width: 760px) {
  .author-tasks { padding: 16px; }
  .author-tasks__header { align-items: stretch; flex-direction: column; }
  .author-tasks__header > .btn { min-height: 44px; }
  .author-task-tabs__archive { margin-left: 0; }
  .author-task-tabs .btn { min-height: 44px; flex: 1 1 calc(50% - 8px); }
  .author-task-row { grid-template-columns: auto minmax(0, 1fr); }
  .author-task-row__actions { grid-column: 2; justify-content: start; }
}
</style>
