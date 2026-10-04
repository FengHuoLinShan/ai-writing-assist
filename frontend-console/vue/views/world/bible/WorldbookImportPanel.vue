<template>
  <section v-if="open" class="panel worldbook-import-panel" aria-labelledby="worldbook-import-title">
    <div class="world-bible-panel__header">
      <div>
        <h2 id="worldbook-import-title">导入世界书资料</h2>
        <p>支持 Markdown、TXT、JSON、YAML。资料先在浏览器本地读取和圈定，预览确认后才创建未发布工作稿；取消或失败都不会改动站内资料。</p>
      </div>
      <button type="button" class="btn btn-sm btn-ghost" @click="close">关闭</button>
    </div>
    <input
      ref="inputEl"
      class="sr-only"
      type="file"
      multiple
      webkitdirectory
      directory
      aria-label="选择资料目录"
      @change="selectFiles"
    />

    <fieldset class="worldbook-import-options" :disabled="busy">
      <legend>导入方式</legend>
      <div class="worldbook-import-options__row">
        <label class="worldbook-import-options__field">资料格式
          <select v-model="sourceFormat" data-action="worldbook-import-format">
            <option value="auto">自动识别</option>
            <option value="obsidian">Obsidian Vault</option>
            <option value="wiki_markdown">Wiki Markdown</option>
            <option value="llmwiki">LLM Wiki</option>
            <option value="generic">通用目录</option>
          </select>
        </label>
        <label class="worldbook-import-options__field">提交范围
          <select v-model="commitMode" data-action="worldbook-import-commit-mode">
            <option value="full_snapshot">完整快照（未再出现的旧页会标记缺失，不删除）</option>
            <option value="append">增量追加（只纳入所选页面，不产生缺失标记）</option>
          </select>
        </label>
      </div>
      <div class="worldbook-import-options__row" role="radiogroup" aria-label="资料集归属">
        <label class="worldbook-import-options__choice"><input v-model="datasetIntent" type="radio" name="worldbook-import-intent" value="new" /> 新资料集</label>
        <label class="worldbook-import-options__choice"><input v-model="datasetIntent" type="radio" name="worldbook-import-intent" value="continue" /> 继续维护</label>
        <label class="worldbook-import-options__choice"><input v-model="datasetIntent" type="radio" name="worldbook-import-intent" value="adopt_legacy" /> 接续旧导入</label>
        <label class="worldbook-import-options__field">资料集名
          <input v-model="datasetName" data-action="worldbook-import-dataset-name" type="text" maxlength="80" placeholder="例如：理法之环" />
        </label>
      </div>
      <p class="world-bible-empty-hint">{{ intentHint }}</p>
    </fieldset>

    <div class="world-bible-panel__actions">
      <button type="button" class="btn btn-sm btn-primary" data-action="worldbook-import-select" :disabled="busy" @click="inputEl?.click()">{{ files.length ? "重新选择目录" : "选择目录" }}</button>
      <button v-if="canPreview" type="button" class="btn btn-sm btn-primary" data-action="worldbook-import-preview" :disabled="busy" @click="previewFiles">{{ pending === "preview" ? "正在检查…" : "预览导入" }}</button>
      <button v-if="catalog" type="button" class="btn btn-sm" data-action="worldbook-import-reset-scope" :disabled="busy" @click="resetScope">清空已选</button>
    </div>
    <p v-if="selectionSummary" class="world-bible-empty-hint">{{ selectionSummary }}</p>
    <p v-if="previewNotice" class="world-bible-empty-hint" role="status">{{ previewNotice }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>

    <div v-if="catalog" class="worldbook-import-scope">
      <div class="worldbook-import-scope__entry">
        <label>入口页面
          <select v-model="entryRelPath" data-action="worldbook-import-entry" @change="onEntryChange">
            <option value="" disabled>请选择入口页面</option>
            <option v-for="item in markdownItems" :key="item.relPath" :value="item.relPath">{{ item.stem }}</option>
          </select>
        </label>
        <span>已选 {{ selectedItems.length }} 页 · 共 {{ formatBytes(selectedBytes) }}</span>
      </div>
      <p v-if="lastExpansion" class="world-bible-empty-hint">刚纳入「{{ lastExpansion.name }}」：新增 1 页 / {{ formatBytes(lastExpansion.bytes) }}</p>
      <p v-if="scopeError" class="form-error" role="alert">{{ scopeError }}</p>
      <details v-if="candidateItems.length" class="worldbook-import-scope__group" open>
        <summary>直接关联中未纳入的页面（{{ candidateItems.length }}）</summary>
        <ul class="worldbook-import-items">
          <li v-for="candidate in candidateItems" :key="candidate.relPath">
            <strong>{{ candidate.name }}</strong>
            <span>{{ candidate.relPath }} · {{ formatBytes(candidate.size) }}</span>
            <small>来自 {{ candidate.from.join("、") }}</small>
            <button type="button" class="btn btn-sm" data-action="worldbook-import-adopt" :data-rel-path="candidate.relPath" :disabled="busy" @click="adoptCandidate(candidate.relPath)">纳入</button>
          </li>
        </ul>
      </details>
      <details v-if="scannedPages.length" class="worldbook-import-scope__group">
        <summary>已纳入并扫描引用的页面（{{ scannedPages.length }}）</summary>
        <ul class="worldbook-import-items">
          <li v-for="page in scannedPages" :key="page.relPath">
            <strong>{{ page.title }}</strong>
            <span>{{ page.relPath }} · {{ formatBytes(page.bytes) }} · 引用 {{ page.links.length }} 条</span>
          </li>
        </ul>
      </details>
      <details v-if="ambiguousEntries.length" class="worldbook-import-scope__group">
        <summary>名称歧义（{{ ambiguousEntries.length }}）——同名多页，不会按名称猜测</summary>
        <ul class="worldbook-import-items">
          <li v-for="entry in ambiguousEntries" :key="`ambiguous:${entry.target}`">
            <strong>{{ entry.target }}</strong>
            <small>来自 {{ entry.from.join("、") }}；如需纳入，请用入口选择或路径明确的页面。</small>
          </li>
        </ul>
      </details>
      <details v-if="unresolvedEntries.length" class="worldbook-import-scope__group">
        <summary>未解析引用（{{ unresolvedEntries.length }}）——目标不在所选目录，会保留链接原文</summary>
        <ul class="worldbook-import-items">
          <li v-for="entry in unresolvedEntries" :key="`unresolved:${entry.target}`">
            <strong>{{ entry.target }}</strong>
            <small>来自 {{ entry.from.join("、") }}</small>
          </li>
        </ul>
      </details>
    </div>

    <template v-if="preview">
      <div class="worldbook-import-counts" aria-label="导入预览统计">
        <span>新建 {{ count("create") }}</span>
        <span>更新 {{ count("update") }}</span>
        <span>保留 {{ count("preserve") }}</span>
        <span>冲突 {{ count("conflict") }}</span>
        <span>源缺失 {{ count("missing") }}</span>
      </div>
      <p>识别为 {{ formatLabel }}；{{ ignoredCount }} 个控制或不支持文件已忽略。</p>
      <p class="world-bible-empty-hint">应用只会创建或更新未发布工作稿；发布仍需在工作台逐页确认。<template v-if="publishedTargets">其中 {{ publishedTargets }} 项目标已是已发布页，应用后生成对应工作稿。</template></p>
      <p v-if="preview.dataset_name">资料集「{{ preview.dataset_name }}」 · {{ commitModeLabel }} · {{ intentLabel }}</p>
      <template v-if="isAdoptLegacy && legacyBindings.length">
        <details class="worldbook-import-scope__group" open>
          <summary>将接续绑定的旧导入（{{ legacyBindings.length }}）</summary>
          <ul class="worldbook-import-items">
            <li v-for="binding in legacyBindings" :key="binding.source_key">
              <span>{{ binding.legacy_source_path }}</span>
              <small>→ {{ binding.rel_path }}</small>
            </li>
          </ul>
        </details>
        <p class="world-bible-empty-hint">接续会更新这些旧导入页的资料归属；已选中它们工作稿的作者 AI 上下文确认会失效，之后可重新确认。</p>
      </template>
      <details v-if="preview.ignored_paths?.length" class="worldbook-import-ignored worldbook-import-items">
        <summary>查看已忽略文件</summary>
        <ul>
          <li v-for="path in preview.ignored_paths" :key="path">{{ path }}</li>
        </ul>
      </details>
      <ul class="worldbook-import-items">
        <li v-for="item in preview.items" :key="`${item.source_key}:${item.action}`">
          <strong>{{ item.title }}</strong>
          <span>{{ [actionLabel(item.action), targetKindLabel(item.target_kind), item.path].filter(Boolean).join(" · ") }}</span>
          <small>{{ item.reason }}</small>
        </li>
      </ul>
      <div class="world-bible-panel__actions">
        <button type="button" class="btn btn-sm btn-primary" data-action="worldbook-import-apply" :disabled="busy" @click="applyImport">{{ pending === "apply" ? "正在应用…" : "创建或更新工作稿" }}</button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue"
import { getApi, getConfirm, getRouter, getToast } from "../../../bridge/index.js"
import {
  DEFAULT_ENTRY_HINT,
  buildCatalog,
  detectEntry,
  pageTitle,
  registerPageTitle,
  scanPage,
} from "./worldbookImportScope.js"

const props = defineProps({
  projectId: { type: String, required: true },
  open: Boolean,
  suggestionId: { type: String, default: "" },
})
const emit = defineEmits(["close"])
const api = getApi()
const confirm = getConfirm()
const router = getRouter()
const toast = getToast()
const inputEl = ref(null)
const files = ref([])
const preview = ref(null)
const error = ref("")
const previewNotice = ref("")
const pending = ref("")
// 本地范围扫描状态：目录清单、入口页、已选与已扫描页面。全部留在浏览器内存，
// 预览前不发任何请求（m1-contract M2：浏览器在已选目录内读取资料）。
const catalog = ref(null)
const entryRelPath = ref("")
const selectedRelPaths = ref([])
const scannedPages = ref([])
const lastExpansion = ref(null)
const scopeError = ref("")
const sourceFormat = ref("auto")
const datasetIntent = ref("new")
const datasetName = ref("")
const commitMode = ref("full_snapshot")
let requestGeneration = 0

const busy = computed(() => Boolean(pending.value))
const isSupportedText = (file) => /\.(md|txt|json|ya?ml)$/i.test(file.name)
const selectionSummary = computed(() => files.value.length
  ? `已选择 ${files.value.length} 个文件，其中 ${files.value.filter(isSupportedText).length} 个可读文本，共 ${files.value.filter(isSupportedText).reduce((sum, item) => sum + item.size, 0).toLocaleString("zh-CN")} 字节。`
  : "")
const formatLabel = computed(() => ({ obsidian: "Obsidian Vault", llmwiki: "LLM Wiki", wiki_markdown: "Wiki Markdown", generic: "通用目录" })[preview.value?.source_format] || "通用目录")
const commitModeLabel = computed(() => ({ full_snapshot: "完整快照", append: "增量追加" })[preview.value?.commit_mode] || "")
const intentLabel = computed(() => ({ new: "新资料集", continue: "继续维护", adopt_legacy: "接续旧导入" })[preview.value?.dataset_intent] || "")
const intentHint = computed(() => ({
  new: "第一次把这批资料带入项目：名字在本项目内需是新的，重名会在预览时被拒绝。",
  continue: "继续维护同名资料集：请填写与之前完全一致的资料集名，来源变化会安全更新工作稿。",
  adopt_legacy: "接续旧导入：把更早未分组的导入归入这个资料集；预览会列出待接续对照，核对后再应用。",
})[datasetIntent.value])
const count = (key) => Number(preview.value?.counts?.[key] || 0)
const actionLabel = (action) => ({ create: "新建工作稿", update: "安全更新", preserve: "保留项目版本", conflict: "需要核对", missing: "来源缺失" })[action] || action
// 真实状态：目标是未发布工作稿还是已发布页（apply 只产生工作稿，已发布页
// 的更新同样先落工作稿）；导入成功不等于已发布。
const targetKindLabel = (kind) => (kind === "page" ? "已发布页" : kind === "draft" ? "工作稿" : "")
const publishedTargets = computed(() => (preview.value?.items || []).filter((item) => item.target_kind === "page").length)
const legacyBindings = computed(() => preview.value?.legacy_bindings || [])
const isAdoptLegacy = computed(() => preview.value?.dataset_intent === "adopt_legacy")
const ignoredCount = computed(() => preview.value?.ignored_paths?.length || 0)
const markdownItems = computed(() => (catalog.value?.items || []).filter((item) => item.isMarkdown))
const selectedItems = computed(() => selectedRelPaths.value
  .map((relPath) => catalog.value?.byRelPath.get(relPath))
  .filter(Boolean))
const selectedBytes = computed(() => selectedItems.value.reduce((sum, item) => sum + item.size, 0))
const canPreview = computed(() => Boolean(catalog.value && selectedRelPaths.value.length))
const candidateItems = computed(() => {
  const seen = new Map()
  for (const page of scannedPages.value) {
    for (const link of page.links) {
      if (link.state !== "unselected" || !link.targetRelPath) continue
      if (selectedRelPaths.value.includes(link.targetRelPath)) continue
      const item = catalog.value?.byRelPath.get(link.targetRelPath)
      if (!item) continue
      let entry = seen.get(item.relPath)
      if (!entry) {
        entry = { relPath: item.relPath, name: item.stem, size: item.size, from: [] }
        seen.set(item.relPath, entry)
      }
      if (!entry.from.includes(page.title)) entry.from.push(page.title)
    }
  }
  return [...seen.values()]
})
const ambiguousEntries = computed(() => collectByState("ambiguous"))
const unresolvedEntries = computed(() => collectByState("unresolved"))

function collectByState(state) {
  const seen = new Map()
  for (const page of scannedPages.value) {
    for (const link of page.links) {
      if (link.state !== state) continue
      let entry = seen.get(link.target)
      if (!entry) {
        entry = { target: link.target, from: [] }
        seen.set(link.target, entry)
      }
      if (!entry.from.includes(page.title)) entry.from.push(page.title)
    }
  }
  return [...seen.values()]
}

function formatBytes(size) {
  return `${Number(size || 0).toLocaleString("zh-CN")} 字节`
}

// 预览是对「导入语义 + 本地范围」的冻结快照；任何一项在预览后变化都使预览
// 失效并要求重新预览，避免界面显示与实际应用的页数、语义不一致（应用范围
// 严格等于预览范围）。清空预览即可让「创建或更新工作稿」入口消失。
function invalidatePreview() {
  if (!preview.value) return
  preview.value = null
  previewNotice.value = "导入设置或所选范围已变化，之前的预览已失效；请重新预览后再应用。"
}

watch([sourceFormat, datasetIntent, datasetName, commitMode], invalidatePreview)

function close() {
  requestGeneration += 1
  pending.value = ""
  emit("close")
}

async function selectFiles(event) {
  error.value = ""
  preview.value = null
  previewNotice.value = ""
  scopeError.value = ""
  const selected = [...(event.target.files || [])]
  const supported = selected.filter(isSupportedText)
  if (!supported.length) {
    files.value = []
    catalog.value = null
    return setError("目录中没有可导入的文本文件。")
  }
  if (selected.length > 2000) return setError("一次最多导入 2,000 个文本文件。")
  if (supported.some((file) => file.size > 2 * 1024 * 1024)) return setError("单个文本文件不能超过 2 MiB。")
  if (supported.reduce((sum, file) => sum + file.size, 0) > 25 * 1024 * 1024) return setError("文本总量不能超过 25 MiB。")
  files.value = supported
  catalog.value = buildCatalog(supported.map((file) => ({
    path: file.webkitRelativePath || file.name,
    size: file.size,
    file,
  })))
  resetScope()
  // 首批入口默认「理法之环」；找不到时由作者手动指定，不做无界递归扫描。
  const entry = detectEntry(catalog.value)
  if (!entry) {
    return setError(`所选目录里没有找到「${DEFAULT_ENTRY_HINT}」页面；请从下方入口列表选择起始页面。`)
  }
  entryRelPath.value = entry.relPath
  await adoptCandidate(entry.relPath, { silent: true })
}

function setError(message) {
  error.value = message
}

function resetScope() {
  invalidatePreview()
  selectedRelPaths.value = []
  scannedPages.value = []
  lastExpansion.value = null
  scopeError.value = ""
  entryRelPath.value = ""
}

async function onEntryChange() {
  if (!entryRelPath.value) return
  await adoptCandidate(entryRelPath.value)
}

// 纳入一个页面：读取内容、扫描引用、更新本地范围。读取失败只停留在本地，
// 不发请求也不改动站内资产（m1-contract M2 完成条件）。
async function adoptCandidate(relPath, { silent = false } = {}) {
  const item = catalog.value?.byRelPath.get(relPath)
  if (!item || selectedRelPaths.value.includes(relPath)) return false
  let content
  try {
    content = await item.file.text()
  } catch {
    scopeError.value = `读取「${item.stem}」失败，资料仍保留在本地；站内资料没有变化。`
    return false
  }
  if (content.includes("\u0000")) {
    scopeError.value = `「${item.stem}」不是可读文本，已跳过。`
    return false
  }
  scopeError.value = ""
  selectedRelPaths.value = [...selectedRelPaths.value, relPath]
  const scanned = scanPage(relPath, content, catalog.value, selectedRelPaths.value)
  registerPageTitle(catalog.value, relPath, scanned.frontmatter)
  scannedPages.value = [...scannedPages.value, {
    relPath,
    title: pageTitle(relPath, scanned.frontmatter),
    bytes: item.size,
    content,
    links: scanned.links,
  }]
  // 纳入新页可能让已扫页面的歧义/未纳入状态变化（标题索引更新），在内存中重放解析。
  rescanAll()
  invalidatePreview()
  if (!silent) {
    lastExpansion.value = { name: item.stem, bytes: item.size }
  }
  return true
}

function rescanAll() {
  scannedPages.value = scannedPages.value.map((page) => ({
    ...page,
    links: scanPage(page.relPath, page.content, catalog.value, selectedRelPaths.value).links,
  }))
}

function explainError(err, fallback) {
  const status = Number(err?.status) || 0
  const detail = String(err?.detail || "")
  if (status === 400 && /already exists/i.test(detail)) {
    return "这个资料集名在项目里已存在。可以改用「继续维护」，或换一个名字再导入。"
  }
  if (status === 409) {
    return "预览已过期：来源或站内页面在预览后有变化。请重新预览再应用；刚才没有改动站内资料。"
  }
  return err?.message || fallback
}

async function previewFiles() {
  if (!canPreview.value || busy.value) return false
  const name = datasetName.value.trim()
  if (!name) {
    error.value = "请先填写资料集名，再预览导入。"
    return false
  }
  const generation = ++requestGeneration
  pending.value = "preview"
  error.value = ""
  try {
    const filesPayload = []
    for (const relPath of selectedRelPaths.value) {
      const item = catalog.value.byRelPath.get(relPath)
      const scanned = scannedPages.value.find((page) => page.relPath === relPath)
      let content
      try {
        content = scanned ? scanned.content : await item.file.text()
      } catch {
        throw new Error(`读取「${item.stem}」失败，已停在本地；站内资料没有变化。可重新预览重试。`)
      }
      filesPayload.push({ path: item.originalPath, content })
    }
    // 应用范围严格等于预览范围：只提交本地已选中的页面（m1-contract M2）。
    const result = await api.world.previewWorldbookImport(props.projectId, {
      source_format: sourceFormat.value,
      dataset_name: name,
      dataset_intent: datasetIntent.value,
      commit_mode: commitMode.value,
      files: filesPayload,
    })
    if (generation !== requestGeneration) return false
    preview.value = result
    previewNotice.value = ""
    return true
  } catch (err) {
    if (generation === requestGeneration) error.value = explainError(err, "无法预览这个目录。")
    return false
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

async function applyImport() {
  if (!preview.value || busy.value) return false
  const bindings = legacyBindings.value
  const adoptNote = isAdoptLegacy.value && bindings.length
    ? `接续会把 ${bindings.length} 个旧导入页归入「${preview.value.dataset_name}」，已选中这些工作稿的作者 AI 上下文确认会失效，之后可重新确认。`
    : ""
  if (!confirm(`${adoptNote}只会创建或更新未发布工作稿；冲突不会覆盖，是否继续？`)) return false
  const generation = ++requestGeneration
  pending.value = "apply"
  error.value = ""
  try {
    const result = await api.world.applyWorldbookImport(preview.value.suggestion_id, props.projectId, preview.value.preview_hash)
    if (generation !== requestGeneration) return false
    toast(`导入完成：${result.draft_ids.length} 个工作稿，${result.conflict_ids.length} 个待核对冲突`, "success")
    const query = new URLSearchParams()
    if (result.draft_ids[0]) query.set("draft_id", result.draft_ids[0])
    router.navigate("world", "bible", true, query)
    return true
  } catch (err) {
    if (generation === requestGeneration) error.value = explainError(err, "应用导入失败；选择和预览仍保留。")
    return false
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

async function restorePreview() {
  if (!props.open || !props.suggestionId || busy.value) return
  const generation = ++requestGeneration
  pending.value = "preview"
  try {
    const result = await api.world.getWorldbookImport(props.suggestionId, props.projectId)
    if (generation === requestGeneration) {
      preview.value = result
      previewNotice.value = ""
    }
  } catch (err) {
    if (generation === requestGeneration) error.value = err?.message || "无法恢复导入预览。"
  } finally {
    if (generation === requestGeneration) pending.value = ""
  }
}

onMounted(restorePreview)
watch(() => props.suggestionId, restorePreview)
</script>
