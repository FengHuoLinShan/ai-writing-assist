<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"
import { useImportUpload } from "../../../composables/useImportUpload.js"
import { getApi, getToast, useStateKey } from "../../../bridge/index.js"
import {
  importFailureMessage,
  importStatusDot,
  importStatusLabel,
  importStatusPill,
  importTimeText,
} from "../logic/importHistory.js"

/**
 * 导入抽屉 — 对应 vanilla _renderImportSection + _renderImportHistory + _uploadFile。
 * 文件上传经 useImportUpload（XHR 进度 → WorkflowProgressCard）。
 */
const emit = defineEmits(["import-new-project"])

const currentProjectId = useStateKey("currentProjectId")
const currentProject = useStateKey("currentProject")
const hasProject = computed(() => Boolean(currentProjectId.value))

const fileInput = ref(null)
const importRecords = ref([])
const historyLoaded = ref(false)
const historyLoading = ref(false)
const historyLoadFailed = ref(false)
const historyFailureCopy = computed(() => (
  historyLoaded.value
    ? "导入记录刷新失败，当前显示上次加载的内容。"
    : "导入记录暂时无法加载，请重试。"
))
let historyLoadGeneration = 0

const { uploading, percent, progress, upload } = useImportUpload()

const uploadCardProgress = computed(() => {
  if (!progress.value) return null
  return {
    label: "导入小说",
    message: progress.value.message || progress.value.stage,
    status: "running",
    statusLabel: progress.value.stage,
    percent: progress.value.percent,
    hasPercent: true,
    indeterminate: false,
    warnings: [],
  }
})

async function loadImportHistory() {
  const projectId = currentProjectId.value
  const generation = ++historyLoadGeneration
  if (!projectId) return
  historyLoading.value = true
  try {
    const data = await getApi().imports.list({ novel_id: projectId })
    if (generation !== historyLoadGeneration || currentProjectId.value !== projectId) return
    importRecords.value = data.items || []
    historyLoaded.value = true
    historyLoadFailed.value = false
  } catch {
    if (generation !== historyLoadGeneration || currentProjectId.value !== projectId) return
    historyLoadFailed.value = true
  } finally {
    if (generation !== historyLoadGeneration || currentProjectId.value !== projectId) return
    historyLoading.value = false
  }
}

function retryImportHistory() {
  if (historyLoading.value || !currentProjectId.value) return
  void loadImportHistory()
}

// 抽屉挂载（打开）时加载一次；项目切换后重载
watch(currentProjectId, () => {
  historyLoadGeneration += 1
  importRecords.value = []
  historyLoaded.value = false
  historyLoadFailed.value = false
  historyLoading.value = false
  if (!currentProjectId.value) return
  void loadImportHistory()
}, { immediate: true, flush: "sync" })

onBeforeUnmount(() => {
  historyLoadGeneration += 1
})

async function uploadFile() {
  const input = fileInput.value
  if (!input || !input.files || input.files.length === 0) {
    getToast()("请先选择文件", "warning")
    return
  }
  const file = input.files[0]
  await upload(file, currentProjectId.value, {
    onSettled: () => {
      input.value = ""
      void loadImportHistory()
    },
  })
}
</script>

<template>
  <div class="project-import-panel">
    <div class="project-import-panel__hint">
      将小说文件导入到当前选中的项目。
      <template v-if="hasProject">当前项目：<strong>{{ currentProject?.title || "" }}</strong></template>
      <span v-else class="project-import-panel__hint-warning">请先点击项目行选择项目</span>
    </div>
    <div class="project-import-panel__form">
      <div class="project-import-panel__field">
        <label class="project-import-panel__label" for="pv-import-file">选择文件（txt/epub/html/mobi）</label>
        <input
          type="file"
          id="pv-import-file"
          class="project-import-panel__input"
          accept=".txt,.epub,.html,.htm,.mobi,.azw3"
          :disabled="!hasProject"
          ref="fileInput"
        />
      </div>
      <button
        class="btn btn-primary"
        data-action="upload-file"
        :disabled="uploading || !hasProject"
        @click="uploadFile"
      >{{ uploading ? `上传中 ${percent}%` : "上传并导入" }}</button>
      <button class="btn btn-ghost" data-action="import" @click="emit('import-new-project')">导入为新项目</button>
    </div>
    <div id="pv-upload-progress" class="project-import-panel__progress">
      <WorkflowProgressCard
        v-if="uploadCardProgress"
        :progress="uploadCardProgress"
        :show-task-id="false"
        :collapse-storage-key-override="`workflow-progress-card:project-upload:${currentProjectId || 'global'}`"
      />
    </div>
    <div class="project-import-panel__history">
      <div class="project-import-panel__history-header">导入记录</div>
      <div id="import-list-body" class="project-import-panel__history-list" role="region" aria-label="导入记录" :aria-busy="historyLoading">
        <p v-if="!hasProject" class="project-import-list__status" role="status" aria-live="polite">选择项目后查看导入记录。</p>
        <template v-else>
          <p v-if="historyLoading && !historyLoaded && !historyLoadFailed" class="project-import-list__status" role="status" aria-live="polite">加载中...</p>
          <div v-if="historyLoadFailed" class="alert alert-warning project-import-list__failure" role="alert">
            <span>{{ historyFailureCopy }}</span>
            <button type="button" class="btn btn-sm" data-action="retry-import-history" :disabled="historyLoading" @click="retryImportHistory">{{ historyLoading ? "正在重试..." : "重试" }}</button>
          </div>
          <p v-if="historyLoading && historyLoaded && !historyLoadFailed" class="project-import-list__status" role="status" aria-live="polite">正在刷新导入记录...</p>
          <p v-if="historyLoaded && !historyLoading && !historyLoadFailed && importRecords.length === 0" class="project-import-list__empty">暂无导入记录。</p>
        </template>
        <div v-for="record in importRecords" :key="record.id || record.file_name + record.created_at" class="import-list-item">
          <div class="project-import-list__item-summary">
            <span class="status-dot" :class="importStatusDot(record.status)"></span>
            <span class="project-import-list__item-name">{{ record.file_name }}</span>
            <span class="pill" :class="importStatusPill(record.status)">{{ importStatusLabel(record.status) }}</span>
            <span class="project-import-list__item-chapters">成功 {{ record.imported_chapters || 0 }} / 共 {{ record.total_chapters || 0 }} 章</span>
            <span class="project-import-list__item-time">{{ importTimeText(record) }}</span>
          </div>
          <p v-if="record.status === 'failed'" class="project-import-list__item-error">
            <strong>失败原因：</strong>{{ importFailureMessage(record) }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
