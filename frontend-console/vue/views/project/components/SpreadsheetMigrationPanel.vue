<script setup>
/**
 * 表格迁移面板 — 向导编排：上传 → 核对表格 → AI 整理 → 预览与确认 → 完成。
 * 只经 vue/bridge 访问 API/toast/state；错误不回显单元格内容。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi, getRouter, getToast, useStateKey } from "../../../bridge/index.js"
import {
  MIGRATION_STEPS,
  isPreviewStale,
  isRevisionConflict,
  mappingPayload,
  revisionConflictCopy,
  stalePreviewCopy,
} from "../logic/spreadsheetMigration.js"
import MigrationUploadStep from "./spreadsheetMigration/MigrationUploadStep.vue"
import MigrationSheetMappingStep from "./spreadsheetMigration/MigrationSheetMappingStep.vue"
import MigrationAiStep from "./spreadsheetMigration/MigrationAiStep.vue"
import MigrationPreviewStep from "./spreadsheetMigration/MigrationPreviewStep.vue"
import MigrationRecordList from "./spreadsheetMigration/MigrationRecordList.vue"

const currentProjectId = useStateKey("currentProjectId")
const step = ref("upload")
const session = ref(null)
const sessions = ref([])
const uploading = ref(false)
const savingMapping = ref(false)
const submittingAi = ref(false)
const savingDecisions = ref(false)
const applying = ref(false)
const recordsBusy = ref(false)

let pollTimer = null

const stepIndex = computed(() => MIGRATION_STEPS.findIndex((entry) => entry.key === step.value))
const aiStatus = computed(() => session.value?.ai?.status || "idle")
const aiRunning = computed(() => aiStatus.value === "queued" || aiStatus.value === "running")

async function refreshSession() {
  if (!session.value) return
  const data = await getApi().imports.migrations.get(session.value.id, {
    novel_id: currentProjectId.value,
  })
  session.value = data
  return data
}

async function loadRecords() {
  const projectId = currentProjectId.value
  if (!projectId) return
  recordsBusy.value = true
  try {
    const data = await getApi().imports.migrations.list({
      novel_id: projectId,
      limit: 20,
      offset: 0,
    })
    if (currentProjectId.value === projectId) sessions.value = data.items || []
  } catch {
    /* 记录加载失败不打断向导 */
  } finally {
    recordsBusy.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!session.value || !aiRunning.value) {
      stopPolling()
      return
    }
    try {
      const data = await refreshSession()
      if (data && !aiRunning.value) stopPolling()
    } catch {
      stopPolling()
    }
  }, 4000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onBeforeUnmount(stopPolling)

// 项目就绪后加载迁移记录；项目切换时清空重载
watch(
  currentProjectId,
  (projectId) => {
    sessions.value = []
    if (projectId) void loadRecords()
  },
  { immediate: true, flush: "sync" },
)

async function onUpload(files) {
  uploading.value = true
  try {
    const data = await getApi().imports.migrations.create(currentProjectId.value, files)
    session.value = data
    step.value = "mapping"
    void loadRecords()
  } catch (err) {
    getToast()(err?.message || "上传失败，请检查文件格式", "error")
  } finally {
    uploading.value = false
  }
}

async function onSaveMapping(payload) {
  savingMapping.value = true
  try {
    const data = await getApi().imports.migrations.saveMapping(session.value.id, {
      ...mappingPayload({ ...session.value, novel_id: currentProjectId.value }, payload.sheets, session.value.options),
      options: session.value.options,
    })
    session.value = data
    step.value = "ai"
  } catch (err) {
    if (isRevisionConflict(err)) {
      getToast()(revisionConflictCopy(), "warning")
      await refreshSession().catch(() => {})
    } else {
      getToast()(err?.message || "保存失败", "error")
    }
  } finally {
    savingMapping.value = false
  }
}

async function onStartAi(scope) {
  submittingAi.value = true
  try {
    await getApi().imports.migrations.startAi(session.value.id, {
      novel_id: currentProjectId.value,
      expected_revision: session.value.revision,
      authorization_confirmed: true,
      operation_id: `migration-${session.value.id}`,
      scope,
    })
    await refreshSession()
    startPolling()
    getToast()("AI 整理已开始，完成后会自动更新预览。", "success")
  } catch (err) {
    getToast()(err?.message || "AI 整理发起失败", "error")
  } finally {
    submittingAi.value = false
  }
}

async function onSkipAi() {
  await refreshSession().catch(() => {})
  step.value = "preview"
}

async function onDecide(decisions) {
  savingDecisions.value = true
  try {
    const data = await getApi().imports.migrations.saveDecisions(session.value.id, {
      novel_id: currentProjectId.value,
      expected_revision: session.value.revision,
      decisions,
    })
    session.value = data
    getToast()("调整已保存，预览已更新。", "success")
  } catch (err) {
    if (isRevisionConflict(err)) {
      getToast()(revisionConflictCopy(), "warning")
      await refreshSession().catch(() => {})
    } else {
      getToast()(err?.message || "保存失败", "error")
    }
  } finally {
    savingDecisions.value = false
  }
}

async function onApply() {
  applying.value = true
  try {
    const result = await getApi().imports.migrations.apply(session.value.id, {
      novel_id: currentProjectId.value,
      expected_preview_hash: session.value.preview?.preview_hash,
      confirmed: true,
    })
    session.value = { ...session.value, status: "applied", receipt_summary: result.receipt_summary }
    step.value = "done"
    getApi().clearCache()
    void loadRecords()
  } catch (err) {
    if (isPreviewStale(err)) {
      getToast()(stalePreviewCopy(), "warning")
      await refreshSession().catch(() => {})
    } else {
      getToast()(err?.message || "采用失败", "error")
    }
  } finally {
    applying.value = false
  }
}

async function onRollback(item) {
  try {
    await getApi().imports.migrations.rollbackPreview(item.id, { novel_id: currentProjectId.value })
    const result = await getApi().imports.migrations.rollback(item.id, {
      novel_id: currentProjectId.value,
      confirmed: true,
    })
    const kept = result.kept || []
    const keptText = kept.length ? `；${kept.length} 项因后续修改保留` : ""
    getToast()(`已撤销 ${result.reverted_count} 项${keptText}。`, "success")
    getApi().clearCache()
    void loadRecords()
  } catch (err) {
    getToast()(err?.message || "撤销失败", "error")
  }
}

async function onRemove(item) {
  try {
    await getApi().imports.migrations.remove(item.id, {
      novel_id: currentProjectId.value,
      confirmed: true,
    })
    void loadRecords()
  } catch (err) {
    getToast()(err?.message || "删除失败", "error")
  }
}

function openRecord(item) {
  session.value = { ...item, sheets: [], files: [], options: {}, preview: null, ai: { status: "idle" } }
  void (async () => {
    try {
      await refreshSession()
      step.value = session.value.status === "draft" ? "mapping" : "done"
    } catch (err) {
      getToast()(err?.message || "打开迁移失败", "error")
    }
  })()
}

function viewWorld() {
  getRouter().navigate("world")
}

const receiptSummary = computed(() => session.value?.receipt_summary || null)
</script>

<template>
  <div class="sm-panel" data-testid="sm-panel">
    <div class="sm-panel__steps" v-if="session">
      <template v-for="(entry, index) in MIGRATION_STEPS" :key="entry.key">
        <span
          class="sm-panel__step"
          :class="{ 'sm-panel__step--active': stepIndex === index, 'sm-panel__step--done': stepIndex > index }"
        >{{ entry.label }}</span>
        <span v-if="index < MIGRATION_STEPS.length - 1" class="sm-panel__step-sep">→</span>
      </template>
    </div>

    <MigrationUploadStep v-if="step === 'upload'" :uploading="uploading" @upload="onUpload" />
    <MigrationSheetMappingStep
      v-else-if="step === 'mapping' && session"
      :session="session"
      :saving="savingMapping"
      @save="onSaveMapping"
    />
    <MigrationAiStep
      v-else-if="step === 'ai' && session"
      :session="session"
      :submitting="submittingAi"
      @start="onStartAi"
      @skip="onSkipAi"
    />
    <MigrationPreviewStep
      v-else-if="step === 'preview' && session"
      :session="session"
      :applying="applying"
      :saving-decisions="savingDecisions"
      @apply="onApply"
      @decide="onDecide"
    />
    <div v-else-if="step === 'done' && session" class="sm-panel__done" data-testid="sm-done">
      <template v-if="session.status === 'applied'">
        <p class="sm-panel__done-title">导入完成。</p>
        <p v-if="receiptSummary" class="sm-panel__done-summary">
          新建 {{ receiptSummary.created || 0 }} 项、补全 {{ receiptSummary.filled || 0 }} 项、
          关系 {{ receiptSummary.relations || 0 }} 条、大纲结构 {{ receiptSummary.structures || 0 }} 项<template v-if="receiptSummary.outline">，并写入总纲</template>。
        </p>
        <div class="sm-panel__done-actions">
          <button type="button" class="btn" data-action="sm-goto-world" @click="viewWorld">去世界库查看</button>
          <button
            type="button"
            class="btn btn-ghost"
            data-action="sm-rollback-now"
            @click="onRollback({ id: session.id })"
          >撤销这次迁移</button>
          <button type="button" class="btn btn-ghost" data-action="sm-new-migration" @click="session = null; step = 'upload'">再迁移一批</button>
        </div>
      </template>
      <template v-else>
        <p class="sm-panel__done-title">这次迁移已{{ session.status === 'rolled_back' ? "撤销" : "部分撤销" }}。</p>
      </template>
    </div>

    <MigrationRecordList
      :sessions="sessions"
      :busy="recordsBusy"
      @refresh="loadRecords"
      @rollback="onRollback"
      @remove="onRemove"
      @open="openRecord"
    />
  </div>
</template>

<style scoped>
.sm-panel { display: flex; flex-direction: column; gap: 16px; }
.sm-panel__steps { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 13px; color: var(--text-muted, #6b7280); }
.sm-panel__step--active { color: var(--text-strong, inherit); font-weight: 600; }
.sm-panel__step--done { text-decoration: line-through; opacity: 0.7; }
.sm-panel__step-sep { opacity: 0.6; }
.sm-panel__done { display: flex; flex-direction: column; gap: 8px; }
.sm-panel__done-title { font-size: 16px; font-weight: 600; margin: 0; }
.sm-panel__done-summary { color: var(--text-muted, #6b7280); margin: 0; }
.sm-panel__done-actions { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
