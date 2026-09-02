<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from "vue"
import { getApi } from "../../bridge/index.js"
import {
  RP_SOURCE_FILE_ACCEPT,
  validateImportFile,
} from "../../composables/useImportUpload.js"
import RpAdaptiveConfirmPopover from "./RpAdaptiveConfirmPopover.vue"
import { sourceEntityTypeLabel } from "./sourceLabels.js"

const props = defineProps({ disabled: { type: Boolean, default: false } })
const emit = defineEmits(["change"])
const storageKey = "rpSourceSetupDraft:v1"
let restored = {}
try { restored = JSON.parse(sessionStorage.getItem(storageKey) || "{}") } catch { /* empty */ }

const restoredStep = Number(restored.step)
const step = ref([1, 2, 3, 4].includes(restoredStep) ? restoredStep : (
  restored.modeChoice === "source" && restored.revisionId
    ? (restored.anchorKey ? 4 : 3)
    : 1
))
const stepHeading = ref(null)

const modeChoice = ref(restored.modeChoice === "source" ? "source" : "model")
const loading = ref(false)
const error = ref("")
const errorSummary = ref(null)
const projects = ref([])
const selectedProjectId = ref(restored.selectedProjectId || "")
const revision = ref(null)
const importOpen = ref(false)
const importTitle = ref("")
const importMode = ref("full")
const importFile = ref(null)
const importFileInput = ref(null)
const preview = ref(null)
const uploading = ref(false)
const uploadPercent = ref(0)
const destructiveConfirmed = ref(false)
const authorizationConfirmed = ref(false)
const selectedChapter = ref(Number(restored.selectedChapter || 0))
const anchorKey = ref(restored.anchorKey || "")
const anchorDescription = ref("")
const anchorMatches = ref([])
const matching = ref(false)
const identityKind = ref(restored.identityKind || "source_character")
const characterKey = ref(restored.characterKey || "")
const originalName = ref(restored.originalName || "")
const originalDescription = ref(restored.originalDescription || "")
const pinnedKeys = ref(Array.isArray(restored.pinnedKeys) ? restored.pinnedKeys : [])
const resolvingKey = ref("")
const organizeConfirmOpen = ref(false)
const organizeAnchor = ref(null)
let pollTimer = null
let uploadController = null
let disposed = false
let pollFailures = 0
let sourceGeneration = 0
let restoredRevisionId = restored.revisionId || null

const POLL_INTERVAL_MS = 2500
const POLL_RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 30000]
const STEP_ITEMS = [
  { value: 1, label: "选择资料来源" },
  { value: 2, label: "选择作品或文件" },
  { value: 3, label: "准备作品资料" },
  { value: 4, label: "角色与开场" },
]

const statusText = computed(() => {
  if (loading.value) return "正在载入作品…"
  if (uploading.value) return `正在上传并校验 ${uploadPercent.value}%`
  if (!revision.value) return ""
  if (revision.value.status === "organizing") return revision.value.progress_message
  if (revision.value.status === "needs_confirmation") return revision.value.progress_message
  if (revision.value.status === "failed") return revision.value.progress_message
  return "作品资料已完整整理，可以选择进入位置"
})
const chapterOptions = computed(() => {
  const chapters = new Map()
  for (const anchor of revision.value?.anchors || []) {
    chapters.set(anchor.chapter_index, anchor.chapter_title)
  }
  return [...chapters].sort((left, right) => left[0] - right[0])
})
const visibleAnchors = computed(() => (
  (revision.value?.anchors || []).filter(
    (anchor) => anchor.chapter_index === selectedChapter.value,
  )
))
const selectedAnchor = computed(() => (
  (revision.value?.anchors || []).find((item) => item.anchor_key === anchorKey.value) || null
))
const visibleObjects = computed(() => (
  selectedAnchor.value
    ? (revision.value?.objects || []).filter((item) => (
      Number(item.first_chapter_index || 0) < selectedAnchor.value.chapter_index
      || (
        Number(item.first_chapter_index || 0) === selectedAnchor.value.chapter_index
        && Number(item.first_end_offset || 0) <= selectedAnchor.value.end_offset
      )
    ))
    : []
))
const characters = computed(() => (
  visibleObjects.value.filter((item) => item.entity_type === "character")
))
const pinnableObjects = computed(() => (
  visibleObjects.value.filter(
    (item) => item.entity_type !== "relation",
  ).slice(0, 30)
))
const sourceModeSummary = computed(() => (
  modeChoice.value === "source" ? "使用已有作品资料" : "直接描述世界与开场"
))
const projectSummary = computed(() => {
  if (revision.value) return `${revision.value.title} · 资料版本 ${revision.value.version_number}`
  return projects.value.find((item) => item.project_id === selectedProjectId.value)?.title
    || importTitle.value.trim()
    || "尚未选择作品"
})
const progressSummary = computed(() => {
  if (!revision.value) return "尚未开始整理"
  if (revision.value.status !== "ready") return statusText.value || "正在准备作品资料"
  return selectedAnchor.value ? `${selectedAnchor.value.chapter_title} · ${selectedAnchor.value.label}` : "尚未选择进入位置"
})
const identitySummary = computed(() => {
  if (modeChoice.value !== "source") return "在开场中描述身份"
  if (identityKind.value === "original") return originalName.value.trim() || "原创角色"
  return characters.value.find((item) => item.reference_key === characterKey.value)?.label || "尚未选择角色"
})
const openingReady = computed(() => (
  step.value === 4
  && (
    modeChoice.value !== "source"
    || (revision.value?.status === "ready" && Boolean(anchorKey.value))
  )
))
const visibleSteps = computed(() => (
  modeChoice.value === "source" ? STEP_ITEMS : [STEP_ITEMS[0], STEP_ITEMS[3]]
))
const setup = computed(() => {
  if (modeChoice.value !== "source" || revision.value?.status !== "ready") return null
  if (!anchorKey.value) return null
  let playerIdentity
  if (identityKind.value === "source_character") {
    if (!characters.value.some((item) => item.reference_key === characterKey.value)) {
      return null
    }
    playerIdentity = { kind: "source_character", reference_key: characterKey.value }
  } else {
    if (!originalName.value.trim()) return null
    playerIdentity = {
      kind: "original",
      name: originalName.value.trim(),
      description: originalDescription.value.trim() || null,
    }
  }
  return {
    source_revision_id: revision.value.id,
    progress_anchor_key: anchorKey.value,
    player_identity: playerIdentity,
    pinned_reference_keys: pinnedKeys.value,
  }
})

function invalidateSourceRequests() {
  sourceGeneration += 1
  restoredRevisionId = null
  uploadController?.abort()
  uploadController = null
  loading.value = false
  uploading.value = false
  matching.value = false
  resolvingKey.value = ""
  return sourceGeneration
}

function sourceRequestIsCurrent(generation, { projectId, revisionId } = {}) {
  return !disposed
    && generation === sourceGeneration
    && (projectId === undefined || selectedProjectId.value === projectId)
    && (revisionId === undefined || revision.value?.id === revisionId)
}

function setStep(value, invalidateRequests = true) {
  if (invalidateRequests) invalidateSourceRequests()
  step.value = value
  if (value === 3) schedulePoll()
  else clearPolling()
  void nextTick(() => stepHeading.value?.focus?.())
}

function stepSummary(number) {
  if (number === 1) return sourceModeSummary.value
  if (number === 2) return projectSummary.value
  if (number === 3) return progressSummary.value
  return identitySummary.value
}

async function continueFromMode() {
  if (modeChoice.value === "model") return setStep(4)
  setStep(2, false)
  if (!projects.value.length) await loadSources()
}

function clearSelectedProject() {
  invalidateSourceRequests()
  revision.value = null
  selectedProjectId.value = ""
  importOpen.value = false
  clearPolling()
  setStep(2, false)
}

function editSelectedSource() {
  invalidateSourceRequests()
  importOpen.value = true
  clearPolling()
  setStep(2, false)
}

function reportError(message) {
  error.value = message || "操作未完成，请重试。"
  void nextTick(() => errorSummary.value?.focus?.())
}

function clearPolling() {
  if (pollTimer != null) clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePoll(delayMs = POLL_INTERVAL_MS) {
  clearPolling()
  if (disposed || revision.value?.status !== "organizing") return
  pollTimer = setTimeout(() => void refreshRevision(), delayMs)
}

async function loadSources(options = {}) {
  if (loading.value) return
  const generation = options.generation ?? ++sourceGeneration
  const revisionIdToRestore = options.restoreRevision === false
    ? null
    : restoredRevisionId
  loading.value = true
  error.value = ""
  try {
    const result = await getApi().interactions.listSources()
    if (!sourceRequestIsCurrent(generation)) return false
    projects.value = result.projects || []
    if (revisionIdToRestore && !revision.value) {
      const restoredRevision = await getApi().interactions.getSource(revisionIdToRestore)
      if (
        !sourceRequestIsCurrent(generation)
        || restoredRevision?.id !== revisionIdToRestore
      ) return false
      revision.value = restoredRevision
      // 恢复场景以 revision 实际归属为准,避免过期存储把"重新整理"
      // 指向另一部作品。
      selectedProjectId.value = revision.value?.project_id || selectedProjectId.value
      restoredRevisionId = null
      syncRevisionDefaults()
    }
    return true
  } catch (requestError) {
    if (sourceRequestIsCurrent(generation)) {
      reportError(requestError?.message || "作品列表暂时无法载入。")
    }
    return false
  } finally {
    if (sourceRequestIsCurrent(generation)) loading.value = false
  }
}

function syncRevisionDefaults() {
  if (!revision.value) return
  const chapters = new Set((revision.value.anchors || []).map((item) => item.chapter_index))
  if (!chapters.has(selectedChapter.value)) {
    selectedChapter.value = chapters.size ? Math.min(...chapters) : 0
  }
  if (!(revision.value.anchors || []).some((item) => item.anchor_key === anchorKey.value)) {
    anchorKey.value = ""
  }
  if (!(revision.value.objects || []).some((item) => item.reference_key === characterKey.value)) {
    characterKey.value = ""
  }
  pinnedKeys.value = pinnedKeys.value.filter((key) => (
    (revision.value.objects || []).some((item) => item.reference_key === key)
  ))
  schedulePoll()
}

async function chooseProject(project) {
  const projectId = project.project_id
  const requestedRevisionId = project.latest_revision?.id
  const generation = invalidateSourceRequests()
  clearPolling()
  try {
    selectedProjectId.value = projectId
    revision.value = null
    pollFailures = 0
    importTitle.value = project.title
    importOpen.value = false
    resetImportFile()
    if (requestedRevisionId) {
      const loadedRevision = await getApi().interactions.getSource(requestedRevisionId)
      if (
        !sourceRequestIsCurrent(generation, { projectId })
        || loadedRevision?.id !== requestedRevisionId
        || loadedRevision?.project_id !== projectId
      ) return
      revision.value = loadedRevision
      syncRevisionDefaults()
      setStep(3, false)
    }
  } catch (requestError) {
    if (sourceRequestIsCurrent(generation, { projectId })) {
      reportError(requestError?.message || "作品资料暂时无法载入。")
    }
  }
}

async function organizeSelectedProject() {
  if (!selectedProjectId.value || loading.value) return
  const projectId = selectedProjectId.value
  const generation = invalidateSourceRequests()
  clearPolling()
  loading.value = true
  error.value = ""
  try {
    const organizedRevision = await getApi().interactions.sourceFromProject({
      project_id: projectId,
      authorization_confirmed: true,
    })
    if (
      !sourceRequestIsCurrent(generation, { projectId })
      || organizedRevision?.project_id !== projectId
    ) return
    revision.value = organizedRevision
    pollFailures = 0
    syncRevisionDefaults()
    setStep(3, false)
  } catch (requestError) {
    if (sourceRequestIsCurrent(generation, { projectId })) {
      reportError(requestError?.message || "完整整理未能开始。")
    }
  } finally {
    if (sourceRequestIsCurrent(generation, { projectId })) loading.value = false
  }
}

function requestOrganize(event) {
  if (loading.value) return
  organizeAnchor.value = event?.currentTarget || null
  organizeConfirmOpen.value = true
}

function confirmOrganize() {
  organizeConfirmOpen.value = false
  void organizeSelectedProject()
}

function chooseFile(event) {
  invalidateSourceRequests()
  importFile.value = event.target.files?.[0] || null
  preview.value = null
  destructiveConfirmed.value = false
}

function resetImportFile() {
  importFile.value = null
  preview.value = null
  authorizationConfirmed.value = false
  destructiveConfirmed.value = false
  void nextTick(() => { if (importFileInput.value) importFileInput.value.value = "" })
}

function startNewImport() {
  invalidateSourceRequests()
  selectedProjectId.value = ""
  revision.value = null
  importTitle.value = ""
  resetImportFile()
  importOpen.value = true
  clearPolling()
  setStep(2, false)
}

async function previewImport() {
  const validation = validateImportFile(importFile.value, RP_SOURCE_FILE_ACCEPT)
  if (validation) return reportError(validation)
  if (!importTitle.value.trim()) return reportError("请填写作品名称。")
  const file = importFile.value
  const title = importTitle.value.trim()
  const mode = importMode.value
  const projectId = selectedProjectId.value
  const generation = invalidateSourceRequests()
  uploading.value = true
  const controller = new AbortController()
  uploadController = controller
  uploadPercent.value = 0
  error.value = ""
  try {
    const nextPreview = await getApi().interactions.previewSourceImport({
      file,
      title,
      mode,
      projectId: projectId || null,
    }, (value) => { uploadPercent.value = value }, { signal: controller.signal })
    if (
      !sourceRequestIsCurrent(generation, { projectId })
      || importFile.value !== file
      || importTitle.value.trim() !== title
      || importMode.value !== mode
    ) return
    preview.value = nextPreview
  } catch (requestError) {
    if (
      requestError?.name !== "AbortError"
      && sourceRequestIsCurrent(generation, { projectId })
    ) {
      reportError(requestError?.message || "文件预览失败。")
    }
  } finally {
    if (uploadController === controller) uploadController = null
    if (sourceRequestIsCurrent(generation, { projectId })) uploading.value = false
  }
}

async function applyImport() {
  if (!preview.value || !authorizationConfirmed.value || uploading.value) return
  const file = importFile.value
  const title = importTitle.value.trim()
  const mode = importMode.value
  const projectId = selectedProjectId.value
  const expectedPreviewHash = preview.value.preview_hash
  const generation = invalidateSourceRequests()
  uploading.value = true
  const controller = new AbortController()
  uploadController = controller
  uploadPercent.value = 0
  error.value = ""
  try {
    const importedRevision = await getApi().interactions.importSource({
      file,
      title,
      mode,
      projectId: projectId || null,
      expectedPreviewHash,
      destructiveConfirmed: destructiveConfirmed.value,
      authorizationConfirmed: true,
    }, (value) => { uploadPercent.value = value }, { signal: controller.signal })
    if (
      !sourceRequestIsCurrent(generation, { projectId })
      || importFile.value !== file
      || importTitle.value.trim() !== title
      || importMode.value !== mode
      || (projectId && importedRevision?.project_id !== projectId)
    ) return
    revision.value = importedRevision
    selectedProjectId.value = importedRevision.project_id
    pollFailures = 0
    importOpen.value = false
    preview.value = null
    if (!await loadSources({ generation, restoreRevision: false })) return
    if (!sourceRequestIsCurrent(generation, {
      projectId: importedRevision.project_id,
      revisionId: importedRevision.id,
    })) return
    syncRevisionDefaults()
    setStep(3, false)
  } catch (requestError) {
    if (requestError?.name !== "AbortError" && generation === sourceGeneration && !disposed) {
      reportError(requestError?.message || "导入未完成，原有作品版本没有改变。")
    }
  } finally {
    if (uploadController === controller) uploadController = null
    if (generation === sourceGeneration && !disposed) uploading.value = false
  }
}

async function refreshRevision() {
  if (!revision.value?.id) return
  const revisionId = revision.value.id
  const projectId = revision.value.project_id
  const generation = ++sourceGeneration
  try {
    const refreshedRevision = await getApi().interactions.getSource(revisionId)
    if (
      !sourceRequestIsCurrent(generation, { projectId, revisionId })
      || refreshedRevision?.id !== revisionId
      || refreshedRevision?.project_id !== projectId
    ) return
    revision.value = refreshedRevision
    if (pollFailures > 0 && error.value === "整理进度暂时无法刷新。") {
      error.value = ""
    }
    pollFailures = 0
    syncRevisionDefaults()
  } catch {
    if (!sourceRequestIsCurrent(generation, { projectId, revisionId })) return
    pollFailures += 1
    // 持续失败时按阶梯退避并只提示一次,不反复抢焦点。
    if (pollFailures === 1) {
      reportError("整理进度暂时无法刷新。")
    }
    schedulePoll(
      POLL_RETRY_DELAYS_MS[Math.min(pollFailures - 1, POLL_RETRY_DELAYS_MS.length - 1)],
    )
  }
}

async function resolveAmbiguity(ambiguity, choiceKey) {
  if (resolvingKey.value) return
  const revisionId = revision.value.id
  const projectId = revision.value.project_id
  const generation = ++sourceGeneration
  resolvingKey.value = ambiguity.ambiguity_key
  try {
    const resolvedRevision = await getApi().interactions.resolveSourceAmbiguity(
      revisionId,
      ambiguity.ambiguity_key,
      choiceKey,
    )
    if (
      !sourceRequestIsCurrent(generation, { projectId, revisionId })
      || resolvedRevision?.id !== revisionId
      || resolvedRevision?.project_id !== projectId
    ) return
    revision.value = resolvedRevision
    syncRevisionDefaults()
  } catch (requestError) {
    if (sourceRequestIsCurrent(generation, { projectId, revisionId })) {
      reportError(requestError?.message || "这项确认未能保存。")
    }
  } finally {
    if (sourceRequestIsCurrent(generation, { projectId, revisionId })) {
      resolvingKey.value = ""
    }
  }
}

async function matchAnchors() {
  if (!anchorDescription.value.trim() || !selectedChapter.value || matching.value) return
  const revisionId = revision.value.id
  const projectId = revision.value.project_id
  const chapter = selectedChapter.value
  const description = anchorDescription.value.trim()
  const generation = ++sourceGeneration
  matching.value = true
  try {
    const result = await getApi().interactions.matchSourceAnchors(
      revisionId,
      {
        chapter_index: chapter,
        description,
      },
    )
    if (
      !sourceRequestIsCurrent(generation, { projectId, revisionId })
      || selectedChapter.value !== chapter
      || anchorDescription.value.trim() !== description
    ) return
    anchorMatches.value = result.items || []
    if (!anchorMatches.value.length) reportError("没有找到可靠的剧情点，请换一种描述。")
  } catch (requestError) {
    if (sourceRequestIsCurrent(generation, { projectId, revisionId })) {
      reportError(requestError?.message || "暂时无法匹配剧情位置。")
    }
  } finally {
    if (sourceRequestIsCurrent(generation, { projectId, revisionId })) {
      matching.value = false
    }
  }
}

function togglePin(key) {
  pinnedKeys.value = pinnedKeys.value.includes(key)
    ? pinnedKeys.value.filter((item) => item !== key)
    : [...pinnedKeys.value, key]
}

watch(modeChoice, async (value) => {
  const generation = invalidateSourceRequests()
  if (value === "source" && !projects.value.length) await loadSources({ generation })
})
watch(selectedChapter, () => {
  anchorMatches.value = []
  if (!characters.value.some((item) => item.reference_key === characterKey.value)) {
    characterKey.value = ""
  }
  const visibleKeys = new Set(pinnableObjects.value.map((item) => item.reference_key))
  pinnedKeys.value = pinnedKeys.value.filter((key) => visibleKeys.has(key))
})
watch(
  [modeChoice, revision, selectedProjectId, selectedChapter, anchorKey,
    identityKind, characterKey, originalName, originalDescription, pinnedKeys, step],
  () => {
    emit("change", {
      enabled: modeChoice.value === "source",
      openingReady: openingReady.value,
      setup: setup.value,
      step: step.value,
    })
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
        step: step.value,
        modeChoice: modeChoice.value,
        selectedProjectId: selectedProjectId.value,
        revisionId: revision.value?.id || null,
        selectedChapter: selectedChapter.value,
        anchorKey: anchorKey.value,
        identityKind: identityKind.value,
        characterKey: characterKey.value,
        originalName: originalName.value,
        originalDescription: originalDescription.value,
        pinnedKeys: pinnedKeys.value,
      }))
    } catch { /* storage unavailable */ }
  },
  { deep: true, immediate: true },
)

onMounted(() => {
  if (modeChoice.value === "source") void loadSources()
})
onBeforeUnmount(() => {
  disposed = true
  sourceGeneration += 1
  uploadController?.abort()
  uploadController = null
  clearPolling()
})
</script>

<template>
  <section class="rp-source-setup" :aria-busy="loading || uploading">
    <ol class="rp-source-steps" :class="{ compact: modeChoice !== 'source' }" aria-label="新旅程设置进度">
      <li
        v-for="(item, index) in visibleSteps"
        :key="item.value"
        :class="{ current: step === item.value, complete: step > item.value }"
        :aria-current="step === item.value ? 'step' : undefined"
      >
        <button v-if="step > item.value" type="button" :disabled="props.disabled" @click="setStep(item.value)">
          <span>{{ index + 1 }} · {{ item.label }}</span><small>{{ stepSummary(item.value) }}</small>
        </button>
        <span v-else>{{ index + 1 }} · {{ item.label }}</span>
      </li>
    </ol>

    <div v-if="modeChoice === 'source' && error" ref="errorSummary" class="rp-source-error" tabindex="-1" role="alert">
      {{ error }} <button type="button" @click="loadSources()">重新载入</button>
    </div>

    <div v-if="step === 1" class="rp-source-step-panel">
      <h3 ref="stepHeading" tabindex="-1">先选择资料来源</h3>
      <fieldset class="rp-source-mode" :disabled="props.disabled">
        <legend>这次怎样进入世界？</legend>
        <label><input v-model="modeChoice" type="radio" value="model" /> 直接描述世界、身份和开场</label>
        <label><input v-model="modeChoice" type="radio" value="source" /> 使用已有作品资料</label>
      </fieldset>
      <p class="rp-source-explainer">
        故事生成与作品整理会使用你在账户中连接的 AI 服务；请求经本站后端代发，Key 不会进入浏览器或作品。
      </p>
      <button class="primary rp-source-next" type="button" :disabled="props.disabled" @click="continueFromMode">
        {{ modeChoice === 'source' ? '下一步：选择作品' : '下一步：填写角色与开场' }}
      </button>
    </div>

    <div v-else-if="step === 2 && modeChoice === 'source'" class="rp-source-workspace rp-source-step-panel">
      <h3 ref="stepHeading" tabindex="-1">选择作品或导入文件</h3>
      <p class="rp-source-explainer">
        作品不必完结；当前版本全部章节完成整理并确认必要歧义后即可开始。
      </p>
      <p v-if="loading" class="rp-source-status" role="status">正在载入作品…</p>
      <div class="rp-source-projects">
        <button
          v-for="project in projects"
          :key="project.project_id"
          type="button"
          :class="{ active: selectedProjectId === project.project_id }"
          :disabled="loading"
          @click="chooseProject(project)"
        >
          <strong>{{ project.title }}</strong>
          <span>{{ project.latest_revision ? `资料版本 ${project.latest_revision.version_number}` : "尚未整理为 RP 资料" }}</span>
        </button>
        <p v-if="!loading && !projects.length">还没有作者作品，可以直接导入一部作品。</p>
        <button
          v-if="selectedProjectId && !revision"
          class="primary"
          type="button"
          :disabled="loading"
          :aria-expanded="organizeConfirmOpen"
          @click="requestOrganize"
        >完整整理这部作品</button>
        <button v-if="selectedProjectId" type="button" @click="importOpen = !importOpen">
          {{ importOpen ? "收起更新" : "更新所选作品" }}
        </button>
        <button type="button" @click="startNewImport">导入新作品</button>
        <button v-if="revision" type="button" @click="setStep(3)">继续使用 {{ revision.title }}</button>
      </div>

      <div v-if="importOpen" class="rp-source-import">
        <h3>{{ selectedProjectId ? "更新所选作品" : "导入新作品" }}</h3>
        <label>作品名称<input v-model="importTitle" maxlength="255" /></label>
        <label>
          更新方式
          <select v-model="importMode">
            <option value="full">完整稿：比较全部章节</option>
            <option value="append">追加稿：只接在末章之后</option>
          </select>
        </label>
        <label>
          作品文件
          <input ref="importFileInput" type="file" :accept="RP_SOURCE_FILE_ACCEPT" @change="chooseFile" />
        </label>
        <button type="button" :disabled="uploading" @click="previewImport">
          {{ uploading ? "正在校验…" : "预览章节变化" }}
        </button>
        <div v-if="preview" class="rp-source-preview">
          <strong>共识别 {{ preview.chapter_count }} 章</strong>
          <ul>
            <li v-for="item in preview.changes" :key="`${item.chapter_index}-${item.change}`">
              {{ item.title }} · {{ { added: "新增", changed: "修改", removed: "移除", reordered: "重排", unchanged: "不变" }[item.change] || "变化" }}
            </li>
          </ul>
          <label v-if="preview.requires_destructive_confirmation">
            <input v-model="destructiveConfirmed" type="checkbox" />
            我确认修改或软废弃上述既有章节版本
          </label>
          <label>
            <input v-model="authorizationConfirmed" type="checkbox" />
            导入后完整整理当前版本的全部章节，并使用我在账户中连接的 AI 服务
          </label>
          <button
            class="primary"
            type="button"
            :disabled="
              uploading
              || !authorizationConfirmed
              || (preview.requires_destructive_confirmation && !destructiveConfirmed)
            "
            @click="applyImport"
          >应用版本并开始整理</button>
        </div>
      </div>
    </div>

    <div v-else-if="step === 3 && modeChoice === 'source'" class="rp-source-workspace rp-source-step-panel">
      <h3 ref="stepHeading" tabindex="-1">准备作品资料与进入位置</h3>
      <p class="rp-source-status" aria-live="polite">{{ statusText || "正在恢复作品资料…" }}</p>
      <div v-if="revision" class="rp-source-revision">
        <header>
          <div><strong>{{ revision.title }}</strong><span>资料版本 {{ revision.version_number }}</span></div>
          <div>
            <button type="button" @click="editSelectedSource">上传更新</button>
            <button type="button" @click="clearSelectedProject">换一部作品</button>
          </div>
        </header>
        <button v-if="revision.status === 'failed'" type="button" @click="requestOrganize">
          重新开始完整整理
        </button>

        <section v-if="revision.status === 'needs_confirmation'" class="rp-source-ambiguities">
          <h3>确认关键指代</h3>
          <article v-for="ambiguity in revision.ambiguities" :key="ambiguity.ambiguity_key">
            <strong>{{ ambiguity.label }}</strong><p>{{ ambiguity.reason }}</p>
            <button
              v-for="choice in ambiguity.choices"
              :key="choice.choice_key"
              type="button"
              :disabled="Boolean(resolvingKey)"
              @click="resolveAmbiguity(ambiguity, choice.choice_key)"
            >{{ choice.label }} · {{ sourceEntityTypeLabel(choice.entity_type) }}</button>
          </article>
        </section>

        <div v-if="revision.status === 'ready'" class="rp-source-ready">
          <label>
            先选章节
            <select v-model.number="selectedChapter" @change="anchorKey = ''">
              <option :value="0" disabled>请选择章节</option>
              <option v-for="[index, title] in chapterOptions" :key="index" :value="index">
                {{ title }}
              </option>
            </select>
          </label>
          <fieldset v-if="selectedChapter">
            <legend>再选这一章内的剧情点</legend>
            <label v-for="anchor in visibleAnchors" :key="anchor.anchor_key">
              <input v-model="anchorKey" type="radio" :value="anchor.anchor_key" />
              <span><strong>{{ anchor.label }}</strong><small>{{ anchor.excerpt }}</small></span>
            </label>
          </fieldset>
          <div class="rp-source-anchor-match">
            <input v-model="anchorDescription" aria-label="描述剧情位置" placeholder="也可以描述：刚见到某人、某场战斗之后……" />
            <button type="button" :disabled="matching || !selectedChapter" @click="matchAnchors">
              {{ matching ? "匹配中…" : "匹配剧情点" }}
            </button>
          </div>
          <div v-if="anchorMatches.length" class="rp-source-anchor-candidates">
            <strong>请选择最符合的一项</strong>
            <button
              v-for="anchor in anchorMatches"
              :key="anchor.anchor_key"
              type="button"
              @click="anchorKey = anchor.anchor_key; anchorMatches = []"
            >{{ anchor.label }} · {{ anchor.excerpt }}</button>
          </div>

          <details v-if="anchorKey && pinnableObjects.length" class="rp-source-pins">
            <summary>预先固定重要人物或地点（可选）</summary>
            <label v-for="item in pinnableObjects" :key="item.reference_key">
              <input
                type="checkbox"
                :checked="pinnedKeys.includes(item.reference_key)"
                @change="togglePin(item.reference_key)"
              /> {{ item.label }} · {{ sourceEntityTypeLabel(item.entity_type) }}
            </label>
          </details>
          <button class="primary rp-source-next" type="button" :disabled="!anchorKey" @click="setStep(4)">
            下一步：选择身份与开场
          </button>
        </div>
      </div>
      <div v-else class="rp-source-current" role="status">
        <p>正在恢复所选作品；如果没有恢复，请返回重新选择。</p>
        <button type="button" @click="setStep(2)">返回选择作品</button>
      </div>
    </div>

    <div v-else-if="step === 4" class="rp-source-step-panel">
      <h3 ref="stepHeading" tabindex="-1">角色与开场</h3>
      <p v-if="modeChoice !== 'source'" class="rp-source-explainer">
        在下方直接写下世界、你的身份和故事起点；不需要先整理作品资料。
      </p>
      <div v-else-if="revision?.status === 'ready' && anchorKey" class="rp-source-ready">
        <p class="rp-source-current">{{ projectSummary }} · {{ progressSummary }}</p>
        <fieldset>
          <legend>玩家身份</legend>
          <label><input v-model="identityKind" type="radio" value="source_character" /> 原作角色</label>
          <label><input v-model="identityKind" type="radio" value="original" /> 原创角色</label>
        </fieldset>
        <label v-if="identityKind === 'source_character'">
          选择角色
          <select v-model="characterKey">
            <option value="" disabled>请选择角色</option>
            <option v-for="item in characters" :key="item.reference_key" :value="item.reference_key">
              {{ item.label }}
            </option>
          </select>
        </label>
        <template v-else>
          <label>角色名称<input v-model="originalName" maxlength="120" /></label>
          <label>身份说明<textarea v-model="originalDescription" rows="3" maxlength="2000"></textarea></label>
        </template>
      </div>
      <div v-else class="rp-source-current" role="status">
        <p>作品资料尚未恢复到可开始状态。</p>
        <button type="button" @click="setStep(3)">返回检查作品资料</button>
      </div>
    </div>

    <RpAdaptiveConfirmPopover
      :anchor="organizeAnchor"
      :busy="loading"
      busy-text="正在开始…"
      confirm-text="开始完整整理"
      id="rp-source-organize-confirm"
      message="将完整整理当前版本的全部章节，并使用你在账户中连接的 AI 服务。请求经本站后端代发，Key 不会进入浏览器或作品。"
      :open="organizeConfirmOpen"
      @close="organizeConfirmOpen = false"
      @confirm="confirmOrganize"
    />
  </section>
</template>
