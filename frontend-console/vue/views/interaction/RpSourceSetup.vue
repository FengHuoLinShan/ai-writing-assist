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

const POLL_INTERVAL_MS = 2500
const POLL_RETRY_DELAYS_MS = [3000, 6000, 12000, 24000, 30000]

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

async function loadSources() {
  if (loading.value) return
  loading.value = true
  error.value = ""
  try {
    const result = await getApi().interactions.listSources()
    if (disposed) return
    projects.value = result.projects || []
    if (restored.revisionId && !revision.value) {
      revision.value = await getApi().interactions.getSource(restored.revisionId)
      // 恢复场景以 revision 实际归属为准,避免过期存储把"重新整理"
      // 指向另一部作品。
      selectedProjectId.value = revision.value?.project_id || selectedProjectId.value
      syncRevisionDefaults()
    }
  } catch (requestError) {
    if (!disposed) reportError(requestError?.message || "作品列表暂时无法载入。")
  } finally {
    if (!disposed) loading.value = false
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
  try {
    selectedProjectId.value = project.project_id
    pollFailures = 0
    importTitle.value = project.title
    importOpen.value = false
    resetImportFile()
    if (project.latest_revision) {
      revision.value = await getApi().interactions.getSource(project.latest_revision.id)
      syncRevisionDefaults()
    } else {
      revision.value = null
    }
  } catch (requestError) {
    reportError(requestError?.message || "作品资料暂时无法载入。")
  }
}

async function organizeSelectedProject() {
  if (!selectedProjectId.value || loading.value) return
  loading.value = true
  error.value = ""
  try {
    revision.value = await getApi().interactions.sourceFromProject({
      project_id: selectedProjectId.value,
      authorization_confirmed: true,
    })
    pollFailures = 0
    syncRevisionDefaults()
  } catch (requestError) {
    reportError(requestError?.message || "完整整理未能开始。")
  } finally {
    loading.value = false
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
  selectedProjectId.value = ""
  revision.value = null
  importTitle.value = ""
  resetImportFile()
  importOpen.value = true
  clearPolling()
}

async function previewImport() {
  const validation = validateImportFile(importFile.value, RP_SOURCE_FILE_ACCEPT)
  if (validation) return reportError(validation)
  if (!importTitle.value.trim()) return reportError("请填写作品名称。")
  uploading.value = true
  const controller = new AbortController()
  uploadController = controller
  uploadPercent.value = 0
  error.value = ""
  try {
    preview.value = await getApi().interactions.previewSourceImport({
      file: importFile.value,
      title: importTitle.value.trim(),
      mode: importMode.value,
      projectId: selectedProjectId.value || null,
    }, (value) => { uploadPercent.value = value }, { signal: controller.signal })
  } catch (requestError) {
    if (!disposed && requestError?.name !== "AbortError") {
      reportError(requestError?.message || "文件预览失败。")
    }
  } finally {
    if (uploadController === controller) uploadController = null
    if (!disposed) uploading.value = false
  }
}

async function applyImport() {
  if (!preview.value || !authorizationConfirmed.value || uploading.value) return
  uploading.value = true
  const controller = new AbortController()
  uploadController = controller
  uploadPercent.value = 0
  error.value = ""
  try {
    revision.value = await getApi().interactions.importSource({
      file: importFile.value,
      title: importTitle.value.trim(),
      mode: importMode.value,
      projectId: selectedProjectId.value || null,
      expectedPreviewHash: preview.value.preview_hash,
      destructiveConfirmed: destructiveConfirmed.value,
      authorizationConfirmed: true,
    }, (value) => { uploadPercent.value = value }, { signal: controller.signal })
    selectedProjectId.value = revision.value.project_id
    pollFailures = 0
    importOpen.value = false
    preview.value = null
    await loadSources()
    syncRevisionDefaults()
  } catch (requestError) {
    if (!disposed && requestError?.name !== "AbortError") {
      reportError(requestError?.message || "导入未完成，原有作品版本没有改变。")
    }
  } finally {
    if (uploadController === controller) uploadController = null
    if (!disposed) uploading.value = false
  }
}

async function refreshRevision() {
  if (!revision.value?.id) return
  try {
    revision.value = await getApi().interactions.getSource(revision.value.id)
    if (pollFailures > 0 && error.value === "整理进度暂时无法刷新。") {
      error.value = ""
    }
    pollFailures = 0
    syncRevisionDefaults()
  } catch {
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
  resolvingKey.value = ambiguity.ambiguity_key
  try {
    revision.value = await getApi().interactions.resolveSourceAmbiguity(
      revision.value.id,
      ambiguity.ambiguity_key,
      choiceKey,
    )
    syncRevisionDefaults()
  } catch (requestError) {
    reportError(requestError?.message || "这项确认未能保存。")
  } finally {
    resolvingKey.value = ""
  }
}

async function matchAnchors() {
  if (!anchorDescription.value.trim() || !selectedChapter.value || matching.value) return
  matching.value = true
  try {
    const result = await getApi().interactions.matchSourceAnchors(
      revision.value.id,
      {
        chapter_index: selectedChapter.value,
        description: anchorDescription.value.trim(),
      },
    )
    anchorMatches.value = result.items || []
    if (!anchorMatches.value.length) reportError("没有找到可靠的剧情点，请换一种描述。")
  } catch (requestError) {
    reportError(requestError?.message || "暂时无法匹配剧情位置。")
  } finally {
    matching.value = false
  }
}

function togglePin(key) {
  pinnedKeys.value = pinnedKeys.value.includes(key)
    ? pinnedKeys.value.filter((item) => item !== key)
    : [...pinnedKeys.value, key]
}

watch(modeChoice, async (value) => {
  if (value === "source" && !projects.value.length) await loadSources()
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
    identityKind, characterKey, originalName, originalDescription, pinnedKeys],
  () => {
    emit("change", { enabled: modeChoice.value === "source", setup: setup.value })
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({
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
  uploadController?.abort()
  uploadController = null
  clearPolling()
})
</script>

<template>
  <section class="rp-source-setup" :aria-busy="loading || uploading">
    <fieldset class="rp-source-mode" :disabled="props.disabled">
      <legend>使用哪种世界资料？</legend>
      <label><input v-model="modeChoice" type="radio" value="model" /> 直接描述开场</label>
      <label><input v-model="modeChoice" type="radio" value="source" /> 使用已有作品资料</label>
    </fieldset>

    <div v-if="modeChoice === 'source'" class="rp-source-workspace">
      <p class="rp-source-explainer">
        作品不必已经完结；当前导入版本的全部章节完成整理、索引和关键歧义确认后即可开始。
      </p>
      <div v-if="error" ref="errorSummary" class="rp-source-error" tabindex="-1" role="alert">
        {{ error }} <button type="button" @click="loadSources">重新载入</button>
      </div>
      <p class="rp-source-status" aria-live="polite">{{ statusText }}</p>

      <div v-if="!revision" class="rp-source-projects">
        <h3>选择作者作品</h3>
        <button
          v-for="project in projects"
          :key="project.project_id"
          type="button"
          :class="{ active: selectedProjectId === project.project_id }"
          @click="chooseProject(project)"
        >
          <strong>{{ project.title }}</strong>
          <span>{{ project.latest_revision ? `资料版本 ${project.latest_revision.version_number}` : "尚未整理为 RP 资料" }}</span>
        </button>
        <p v-if="!loading && !projects.length">还没有作者作品，可以直接导入一部作品。</p>
        <button
          v-if="selectedProjectId"
          class="primary"
          type="button"
          :disabled="loading"
          :aria-expanded="organizeConfirmOpen"
          @click="requestOrganize"
        >完整整理这部作品</button>
        <button
          v-if="selectedProjectId"
          type="button"
          @click="importOpen = !importOpen"
        >{{ importOpen ? "收起更新" : "更新所选作品" }}</button>
        <button type="button" @click="startNewImport">导入新作品</button>
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
            导入后完整整理当前版本的全部章节，并使用我的模型额度
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

      <div v-if="revision" class="rp-source-revision">
        <header>
          <div><strong>{{ revision.title }}</strong><span>资料版本 {{ revision.version_number }}</span></div>
          <div>
            <button type="button" @click="importOpen = !importOpen">上传更新</button>
            <button type="button" @click="revision = null; selectedProjectId = ''; importOpen = false; clearPolling()">换一部作品</button>
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
            <input v-model="anchorDescription" placeholder="也可以描述：刚见到某人、某场战斗之后……" />
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

          <details v-if="pinnableObjects.length" class="rp-source-pins">
            <summary>预先固定重要人物或地点（可选）</summary>
            <label v-for="item in pinnableObjects" :key="item.reference_key">
              <input
                type="checkbox"
                :checked="pinnedKeys.includes(item.reference_key)"
                @change="togglePin(item.reference_key)"
              /> {{ item.label }} · {{ sourceEntityTypeLabel(item.entity_type) }}
            </label>
          </details>
        </div>
      </div>
    </div>

    <RpAdaptiveConfirmPopover
      :anchor="organizeAnchor"
      :busy="loading"
      busy-text="正在开始…"
      confirm-text="开始完整整理"
      id="rp-source-organize-confirm"
      message="将完整整理当前版本的全部章节，并使用我的模型额度。"
      :open="organizeConfirmOpen"
      @close="organizeConfirmOpen = false"
      @confirm="confirmOrganize"
    />
  </section>
</template>
