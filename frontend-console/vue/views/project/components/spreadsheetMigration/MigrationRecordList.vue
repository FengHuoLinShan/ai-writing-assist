<script setup>
/**
 * 表格迁移 — 迁移记录列表：状态、回执摘要、撤销与删除（删除需二次确认）。
 */
import { computed, ref } from "vue"
import { getToast } from "../../../../bridge/index.js"
import { sessionStatusLabel } from "../../logic/spreadsheetMigration.js"

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(["refresh", "rollback", "remove", "open"])

const confirmingDelete = ref(null)

const items = computed(() => props.sessions || [])

async function rollback(item) {
  emit("rollback", item)
}

function askDelete(item) {
  confirmingDelete.value = item.id
}

async function confirmDelete(item) {
  confirmingDelete.value = null
  getToast()("正在删除迁移记录；删除后不能再撤销这次导入。", "info")
  emit("remove", item)
}

function countsText(item) {
  const counts = item.counts || {}
  const parts = []
  if (counts.created) parts.push(`新建 ${counts.created}`)
  if (counts.relations) parts.push(`关系 ${counts.relations}`)
  if (counts.structures) parts.push(`结构 ${counts.structures}`)
  return parts.length ? parts.join(" · ") : ""
}
</script>

<template>
  <div class="sm-records" data-testid="sm-records">
    <div class="sm-records__head">
      <span>迁移记录</span>
      <button type="button" class="btn btn-sm" data-action="sm-records-refresh" :disabled="busy" @click="emit('refresh')">刷新</button>
    </div>
    <p v-if="items.length === 0" class="sm-records__empty">还没有迁移记录。上传表格开始第一次迁移。</p>
    <div v-for="item in items" :key="item.id" class="sm-records__item" :data-record="item.id">
      <div class="sm-records__summary">
        <span class="status-dot" :class="item.status === 'applied' ? 'success' : item.status === 'draft' ? 'warning' : 'info'"></span>
        <strong>{{ (item.file_names || []).join("、") }}</strong>
        <span>{{ sessionStatusLabel(item.status) }}</span>
        <span v-if="countsText(item)" class="sm-records__muted">{{ countsText(item) }}</span>
        <span class="sm-records__muted">{{ item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "" }}</span>
      </div>
      <div class="sm-records__actions">
        <button v-if="item.status === 'draft'" type="button" class="btn btn-sm" data-action="sm-records-open" @click="emit('open', item)">继续</button>
        <button
          v-if="item.can_rollback"
          type="button"
          class="btn btn-sm"
          data-action="sm-records-rollback"
          :disabled="busy"
          @click="rollback(item)"
        >撤销这次导入</button>
        <template v-if="confirmingDelete === item.id">
          <span>删除后不能再撤销，确定？</span>
          <button type="button" class="btn btn-sm" data-action="sm-records-delete-confirm" :disabled="busy" @click="confirmDelete(item)">确认删除</button>
          <button type="button" class="btn btn-sm btn-ghost" data-action="sm-records-delete-cancel" @click="confirmingDelete = null">取消</button>
        </template>
        <button v-else type="button" class="btn btn-sm btn-ghost" data-action="sm-records-delete" @click="askDelete(item)">删除记录</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sm-records { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--border-color, #e5e7eb); padding-top: 12px; }
.sm-records__head { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.sm-records__empty { color: var(--text-muted, #6b7280); }
.sm-records__item { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; }
.sm-records__summary { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; font-size: 13px; }
.sm-records__muted { color: var(--text-muted, #6b7280); }
.sm-records__actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 13px; }
</style>
