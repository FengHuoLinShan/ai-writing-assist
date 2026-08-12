<template>
  <main class="atlas-workspace">
    <header class="atlas-header">
      <div>
        <p class="atlas-eyebrow">作者地图工作台</p>
        <h1>AI 地图册</h1>
        <p>从已确认的世界资料规划层级，再逐页生成可审核的地图图片。</p>
      </div>
      <div class="atlas-primary-actions">
        <button class="btn btn-primary" :disabled="writeLocked || runUnfinished" @click="startRun(false)">
          {{ atlas.total_pages ? '补全 / 更新地图册' : '一键生成地图册' }}
        </button>
        <details v-if="atlas.total_pages" class="atlas-more">
          <summary class="btn btn-sm">更多</summary>
          <button class="btn btn-sm" :disabled="writeLocked || runUnfinished" @click="startRun(true)">完整重做</button>
        </details>
      </div>
    </header>

    <section class="atlas-options card" aria-label="地图册生成选项">
      <label>版式
        <select v-model="options.layout" class="form-select" :disabled="writeLocked || runUnfinished">
          <option value="landscape">横版</option><option value="square">方形</option>
        </select>
      </label>
      <label>清晰度
        <select v-model="options.quality" class="form-select" :disabled="writeLocked || runUnfinished">
          <option value="standard">标准</option><option value="fine">精细</option>
        </select>
      </label>
      <label class="atlas-style">画面偏好
        <input v-model="options.style_note" class="form-input" maxlength="2000" placeholder="例如：旧羊皮纸、克制的山脉与河流细节" :disabled="writeLocked || runUnfinished" />
      </label>
      <details>
        <summary>高级选项</summary>
        <label><input v-model="options.include_working_drafts" type="checkbox" :disabled="writeLocked || runUnfinished" /> 加入工作稿资料</label>
        <label><input v-model="options.include_interiors" type="checkbox" :disabled="writeLocked || runUnfinished" /> 允许规划室内图</label>
      </details>
    </section>

    <div v-if="error" class="alert alert-warning atlas-alert" role="alert">
      <span>{{ error }}</span>
      <button v-if="connectionError" class="btn btn-sm" :disabled="busy" @click="openImageSettings">去账户设置</button>
      <button v-else class="btn btn-sm" :disabled="busy" @click="loadAll">重试</button>
    </div>

    <section v-if="currentRun" class="atlas-run card" aria-live="polite">
      <div>
        <strong>{{ runStatusLabel }}</strong>
        <span v-if="currentRun.planned_page_count">{{ currentRun.completed_page_count }} / {{ currentRun.planned_page_count }} 页</span>
        <span v-else>正在整理地图层级</span>
      </div>
      <progress aria-label="地图册生成进度" :value="currentRun.completed_page_count" :max="currentRun.planned_page_count || 1" />
      <p v-if="currentRun.error_message">{{ currentRun.error_message }}</p>
      <div class="atlas-run-actions">
        <button v-if="runActive && !currentRun.stop_requested" class="btn btn-sm" :disabled="busy" @click="stopRun">生成完当前页后停止</button>
        <button v-if="canResume" class="btn btn-sm btn-primary" :disabled="writeLocked" @click="resumeRun">继续生成</button>
        <button v-if="latestRunId && currentRun.id !== latestRunId" class="btn btn-sm" :disabled="writeLocked" @click="viewRun(latestRunId)">返回最新一轮</button>
      </div>
    </section>

    <nav class="atlas-tabs" aria-label="地图册视图" role="tablist">
      <button role="tab" :class="{ active: tab === 'review' }" :aria-selected="tab === 'review'" :aria-pressed="tab === 'review'" @click="selectTab('review')">本次生成结果 <span>{{ review.total_pages }}</span></button>
      <button role="tab" :class="{ active: tab === 'atlas' }" :aria-selected="tab === 'atlas'" :aria-pressed="tab === 'atlas'" @click="selectTab('atlas')">我的地图册 <span>{{ atlas.total_pages }}</span></button>
    </nav>

    <details v-if="historyPages.length" class="card atlas-history">
      <summary>历史记录 {{ historyPages.length }}</summary>
      <div v-for="page in historyPages" :key="page.id" class="atlas-source">
        <div>
          <strong>{{ page.title }}</strong>
          <p><span class="atlas-history-status">{{ historyStatusLabel(page) }}</span> · {{ formatDate(page.updated_at) }}</p>
        </div>
        <button v-if="page.review_status === 'candidate'" class="btn btn-sm" :disabled="writeLocked" @click="viewRun(page.run_id)">查看本轮</button>
        <button v-else-if="page.review_status === 'deprecated'" class="btn btn-sm" :disabled="writeLocked" @click="restorePage(page)">恢复到地图册</button>
      </div>
    </details>

    <section v-if="allCandidatesRejected" class="card atlas-empty atlas-all-rejected" role="status">
      <h2>本次候选均未加入</h2>
      <p>图片已保留在拒绝历史中，原地图册没有改变。</p>
    </section>

    <section v-if="loading" class="card atlas-empty" aria-live="polite">正在读取地图册…</section>
    <section v-else-if="!visiblePages.length" class="card atlas-empty">
      <h2>{{ emptyTitle }}</h2>
      <p>{{ emptyText }}</p>
    </section>

    <section v-else class="atlas-browser" role="tabpanel" :aria-label="tab === 'review' ? '本次生成结果' : '我的地图册'">
      <aside class="card atlas-tree" aria-label="地图层级">
        <button
          v-for="item in visibleNodes"
          :key="item.node.id"
          :class="{ active: activePage?.node_id === item.node.id }"
          :aria-current="activePage?.node_id === item.node.id ? 'true' : undefined"
          :style="{ paddingLeft: `${12 + item.depth * 18}px` }"
          @click="selectNode(item.node)"
        >
          <span>{{ levelLabel(item.node.level) }}</span>{{ item.node.title }}
          <small>{{ item.node.pages.length || '' }}</small>
        </button>
      </aside>

      <article v-if="activePage" class="card atlas-page">
        <header class="atlas-page-header">
          <div><p>{{ levelLabel(activeNode?.level) }}</p><h2>{{ activePage.title }}</h2></div>
          <label class="atlas-zoom">缩放 <input v-model="zoom" type="range" min="60" max="150" step="10" /></label>
        </header>

        <div :class="['atlas-images', { compare: oldPages.length && tab === 'review' }]">
          <figure v-if="oldPages.length && tab === 'review'">
            <figcaption>地图册已有图片</figcaption>
            <div class="atlas-image-viewport">
              <div v-if="imageUrls[oldPage.id]" class="atlas-image-canvas" :style="imageCanvasStyle(oldPage)">
                <img :src="imageUrls[oldPage.id]" :alt="`${oldPage.title} 已采用地图`" />
                <button
                  v-for="annotation in oldPage.annotations"
                  :key="annotation.id"
                  class="atlas-annotation"
                  :style="annotationStyle(annotation)"
                  @click="openAnnotation(annotation)"
                >{{ annotation.label }}</button>
              </div>
              <div v-else-if="imageStatus[oldPage.id] === 'error'" class="atlas-image-state" role="alert">
                <span>图片读取失败</span><button class="btn btn-sm" @click="retryImage(oldPage)">重试</button>
              </div>
              <span v-else class="atlas-image-state" role="status">正在加载图片…</span>
            </div>
            <select v-if="oldPages.length > 1" v-model="oldPageId" class="form-select" aria-label="切换地图册已有图片">
              <option v-for="page in oldPages" :key="page.id" :value="page.id">{{ formatDate(page.created_at) }}</option>
            </select>
            <button class="btn btn-sm btn-ghost" :disabled="writeLocked" @click="archivePage(oldPage)">移出地图册</button>
          </figure>

          <figure>
            <figcaption>{{ tab === 'review' ? '新候选' : '地图册图片' }}</figcaption>
            <div class="atlas-image-viewport">
              <div v-if="imageUrls[activePage.id]" ref="imageCanvas" class="atlas-image-canvas" :style="imageCanvasStyle(activePage)">
                <img :src="imageUrls[activePage.id]" :alt="`${activePage.title} 地图`" />
                <button
                  v-for="annotation in activePage.annotations"
                  :key="annotation.id"
                  class="atlas-annotation"
                  :style="annotationStyle(annotation)"
                  @pointerdown="startAnnotationDrag($event, annotation)"
                  @click="openAnnotation(annotation)"
                >{{ annotation.label }}</button>
              </div>
              <span v-else-if="activePage.generation_status === 'failed'" class="atlas-image-state">本页生成失败</span>
              <span v-else-if="activePage.generation_status === 'retry_requires_confirmation'" class="atlas-image-state">这页需确认后才能继续生成</span>
              <div v-else-if="imageStatus[activePage.id] === 'error'" class="atlas-image-state" role="alert">
                <span>图片读取失败</span><button class="btn btn-sm" @click="retryImage(activePage)">重试</button>
              </div>
              <span v-else class="atlas-image-state" role="status">正在加载图片…</span>
            </div>
            <p v-if="activePage.error_message" class="atlas-error">{{ activePage.error_message }}</p>
            <select v-if="tab === 'atlas' && activeNode?.pages?.length > 1" v-model="activePageId" class="form-select" aria-label="切换同地点图片">
              <option v-for="page in activeNode.pages" :key="page.id" :value="page.id">{{ formatDate(page.created_at) }}</option>
            </select>
          </figure>
        </div>

        <div v-if="tab === 'review'" class="atlas-review-actions">
          <p v-if="activePage.generation_status === 'retry_requires_confirmation'" class="atlas-charge-warning" role="alert">上次图片请求可能已产生费用，再次生成前需要确认。</p>
          <button v-if="activePage.generation_status === 'review_ready' && activePage.review_status === 'candidate'" class="btn btn-primary" :disabled="writeLocked" @click="adoptPage">加入地图册</button>
          <button v-if="activePage.generation_status === 'review_ready' && activePage.review_status === 'candidate'" class="btn" :disabled="writeLocked" @click="rejectPage">不加入</button>
          <button v-if="activePage.review_status === 'deprecated'" class="btn" :disabled="writeLocked" @click="restorePage(activePage)">恢复到地图册</button>
          <button v-if="['failed', 'retry_requires_confirmation'].includes(activePage.generation_status)" class="btn btn-primary" :disabled="writeLocked" @click="retryPage">{{ activePage.generation_status === 'retry_requires_confirmation' ? '确认费用并重试本页' : '重试本页' }}</button>
          <details v-if="activePage.generation_status === 'review_ready'" class="atlas-edit">
            <summary class="btn">AI 修改 / 重生成</summary>
            <textarea v-model="editInstruction" class="form-textarea" rows="3" placeholder="描述希望修改的画面；重生成可留空" :disabled="writeLocked" />
            <fieldset v-if="referenceChoices.length" class="atlas-references">
              <legend>参考地图（可选，最多 7 张）</legend>
              <label v-for="choice in referenceChoices" :key="choice.id">
                <input v-model="selectedReferencePageIds" type="checkbox" :value="choice.id" :disabled="writeLocked || (!selectedReferencePageIds.includes(choice.id) && selectedReferencePageIds.length >= 7)" />
                {{ choice.label }}
              </label>
            </fieldset>
            <label class="atlas-mask">局部修改蒙版（PNG）<input type="file" accept="image/png" :disabled="writeLocked" @change="maskFile = $event.target.files?.[0] || null" /></label>
            <p>蒙版只作为模型指导，修改边缘可能扩散；蒙版和精确标注建议在桌面完成。</p>
            <div><button class="btn btn-sm" :disabled="writeLocked || !editInstruction.trim()" @click="derivePage('edit')">按说明修改</button><button class="btn btn-sm" :disabled="writeLocked" @click="derivePage('regenerate')">重新生成候选</button></div>
          </details>
        </div>
        <div v-else class="atlas-review-actions">
          <button class="btn btn-sm btn-ghost" :disabled="writeLocked" @click="archivePage(activePage)">移出地图册</button>
        </div>

        <section class="atlas-evidence">
          <h3>为何这样画</h3>
          <div class="atlas-evidence-grid">
            <div><strong>资料直接支持</strong><p v-if="!evidence.supported.length">没有直接资料</p><ul><li v-for="item in evidence.supported" :key="item">{{ item }}</li></ul></div>
            <div><strong>AI 为画面补全</strong><p class="atlas-candidate-note">不属于正式设定</p><p v-if="!evidence.visual_fill.length">没有额外补全</p><ul><li v-for="item in evidence.visual_fill" :key="item">{{ item }}</li></ul></div>
            <div v-if="evidence.conflicts.length" class="atlas-conflicts"><strong>存在冲突</strong><ul><li v-for="item in evidence.conflicts" :key="item">{{ item }}</li></ul></div>
          </div>
          <details v-if="activePage.source_manifest.length">
            <summary>查看完整来源</summary>
            <article v-for="(source, index) in activePage.source_manifest" :key="`${source.source_type}:${index}`" class="atlas-source">
              <div><strong>{{ source.title || '来源资料' }}</strong><p><span v-if="source.source_status === 'working'">工作稿（非正式设定） · </span>{{ source.summary || '已保留资料' }}</p></div>
              <button v-if="source.open_target" class="btn btn-sm" @click="openSource(source.open_target, source)">打开来源</button>
            </article>
          </details>
        </section>
      </article>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { getApi, getConfirm, getRouter, getToast } from "../../bridge/index.js"

const props = defineProps({ projectId: { type: String, default: null } })
const api = getApi()
const toast = getToast()
const confirm = getConfirm()
const tab = ref("review")
const loading = ref(true)
const busy = ref(false)
const refreshing = ref(false)
const error = ref("")
const errorCode = ref("")
const currentRun = ref(null)
const latestRunId = ref(null)
const review = ref({ mode: "review", nodes: [], total_pages: 0 })
const atlas = ref({ mode: "atlas", nodes: [], total_pages: 0 })
const pageHistory = ref([])
const activePageId = ref(null)
const oldPageId = ref(null)
const zoom = ref(100)
const editInstruction = ref("")
const maskFile = ref(null)
const selectedReferencePageIds = ref([])
const imageCanvas = ref(null)
const imageUrls = reactive({})
const imageStatus = reactive({})
const options = reactive({ layout: "landscape", quality: "standard", style_note: "", include_working_drafts: false, include_interiors: false })
let pollTimer = null
let drag = null
let dataEpoch = 0
let suppressedAnnotationClickId = null
let mounted = true
const imageRequests = new Map()
const insufficientSourcesHelp = "请先补充并发布世界书、确认地点设定或正文；也可以在高级选项中打开“加入工作稿资料”后重试。"

const activeTree = computed(() => tab.value === "review" ? review.value : atlas.value)
const visibleNodes = computed(() => flattenNodes(activeTree.value.nodes || []))
const visiblePages = computed(() => visibleNodes.value.flatMap(({ node }) => node.pages || []))
const activePage = computed(() => visiblePages.value.find(page => page.id === activePageId.value) || visiblePages.value[0] || null)
const activeNode = computed(() => visibleNodes.value.find(({ node }) => node.id === activePage.value?.node_id)?.node || null)
const adoptedNode = computed(() => flattenNodes(atlas.value.nodes || []).find(({ node }) => node.id === activePage.value?.node_id)?.node || null)
const oldPages = computed(() => adoptedNode.value?.pages || [])
const oldPage = computed(() => oldPages.value.find(page => page.id === oldPageId.value) || oldPages.value[0] || {})
const evidence = computed(() => ({ supported: [], visual_fill: [], conflicts: [], ...(activePage.value?.evidence || {}) }))
const historyPages = computed(() => {
  const pages = Array.isArray(pageHistory.value) ? pageHistory.value : (pageHistory.value?.items || [])
  return pages.filter(page => page.run_id !== currentRun.value?.id)
})
const runActive = computed(() => ["planning", "generating"].includes(currentRun.value?.status))
const canResume = computed(() => currentRun.value?.status === "paused"
  || (currentRun.value?.status === "partial" && ["retry_requires_confirmation", "worker_interrupted"].includes(currentRun.value?.error_code)))
const runUnfinished = computed(() => runActive.value || canResume.value)
const writeLocked = computed(() => loading.value || busy.value || (runActive.value && Boolean(currentRun.value?.stop_requested)))
const connectionError = computed(() => ["image_connection_required", "image_auth_failed"].includes(errorCode.value))
const runStatusLabel = computed(() => ({ planning: "正在规划地图册", generating: currentRun.value?.stop_requested ? "将在当前页完成后停止" : "正在逐页生成", review_ready: "本次地图册已经生成", partial: "部分页面需要处理", paused: "生成已停止", failed: "地图册生成失败", completed: "地图册已完成" }[currentRun.value?.status] || "地图册任务"))
const emptyTitle = computed(() => {
  if (tab.value !== "review") return "你的地图册还是空的"
  if (!currentRun.value) return "还没有本次生成结果"
  if (currentRun.value.error_code === "insufficient_sources") return "已确认资料不足"
  return ({ failed: "本次生成未完成", paused: "本次生成已停止", review_ready: "本次没有新页面", completed: "本次没有新页面" }[currentRun.value.status] || "结果正在生成")
})
const emptyText = computed(() => tab.value === "review" && currentRun.value?.error_code === "insufficient_sources"
  ? insufficientSourcesHelp
  : tab.value === "review" ? "已完成的候选会逐页出现在这里，刷新页面也不会丢失。" : "采用候选后会出现在这里；拒绝候选不会改变已有地图册。")
const allCandidatesRejected = computed(() => tab.value === "review"
  && visiblePages.value.length > 0
  && visiblePages.value.every(page => page.review_status === "rejected"))
const referenceChoices = computed(() => flattenNodes(atlas.value.nodes || []).flatMap(({ node }) => (
  (node.pages || [])
    .filter(page => page.review_status === "adopted" && page.id !== activePage.value?.id)
    .map(page => ({ id: page.id, label: `${node.title} · ${formatDate(page.created_at)}` }))
)))

function flattenNodes(nodes, depth = 0, result = []) {
  for (const node of nodes) {
    result.push({ node, depth })
    flattenNodes(node.children || [], depth + 1, result)
  }
  return result
}
function levelLabel(level) { return ({ cover: "封面", world: "世界", region: "区域", city: "城市", district: "城区", street: "街道", interior: "室内" }[level] || "地图") }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "已有图片" }
function historyStatusLabel(page) {
  if (page.review_status === "rejected") return "已决定不加入"
  if (page.review_status === "deprecated") return "已从地图册移出"
  if (page.generation_status === "failed") return "生成失败，可重试"
  if (page.generation_status === "retry_requires_confirmation") return "需确认费用后重试"
  return "等待决定"
}
function selectNode(node) { const page = node.pages?.find(item => item.review_status === "candidate") || node.pages?.[0]; if (page) activePageId.value = page.id }
function annotationStyle(item) { return { left: `${item.position_x * 100}%`, top: `${item.position_y * 100}%` } }
function imageCanvasStyle(page) {
  const width = Number(page?.width)
  const height = Number(page?.height)
  return {
    width: `${zoom.value}%`,
    aspectRatio: width > 0 && height > 0 ? `${width} / ${height}` : undefined,
  }
}

function desiredImagePages() {
  const pages = [activePage.value]
  if (tab.value === "review" && oldPage.value?.id) pages.push(oldPage.value)
  return pages.filter(page => page?.id && page.image_url)
}
function releaseImage(pageId) {
  imageRequests.delete(pageId)
  if (imageUrls[pageId]) URL.revokeObjectURL(imageUrls[pageId])
  delete imageUrls[pageId]
  delete imageStatus[pageId]
}
async function loadImage(page, force = false) {
  if (!page?.id || !page.image_url) return
  if (force) releaseImage(page.id)
  if (imageUrls[page.id] || imageStatus[page.id] === "loading" || imageStatus[page.id] === "error") return
  const token = {}
  imageRequests.set(page.id, token)
  imageStatus[page.id] = "loading"
  try {
    const url = URL.createObjectURL(await api.world.fetchMapAtlasImage(props.projectId, page.id))
    const stillWanted = desiredImagePages().some(item => item.id === page.id)
    if (!mounted || imageRequests.get(page.id) !== token || !stillWanted) {
      URL.revokeObjectURL(url)
      return
    }
    imageUrls[page.id] = url
    imageStatus[page.id] = "ready"
  } catch {
    if (mounted && imageRequests.get(page.id) === token) imageStatus[page.id] = "error"
  } finally {
    if (imageRequests.get(page.id) === token) imageRequests.delete(page.id)
  }
}
async function loadImages() {
  const pages = desiredImagePages()
  const desiredIds = new Set(pages.map(page => page.id))
  for (const pageId of new Set([...Object.keys(imageUrls), ...Object.keys(imageStatus)])) {
    if (!desiredIds.has(pageId)) releaseImage(pageId)
  }
  await Promise.all(pages.map(page => loadImage(page)))
}
async function retryImage(page) {
  await loadImage(page, true)
}
async function loadAll(preferredRunId = null) {
  preferredRunId = typeof preferredRunId === "string" ? preferredRunId : null
  const epoch = ++dataEpoch
  const projectId = props.projectId
  loading.value = true
  if (!projectId) { loading.value = false; error.value = "请先选择一个作品"; return }
  error.value = ""; errorCode.value = ""
  try {
    const [savedAtlas, latest, history, preferredRun] = await Promise.all([
      api.world.getMapAtlas(projectId),
      api.world.getLatestMapAtlasRun(projectId),
      api.world.getMapAtlasPageHistory(projectId),
      preferredRunId ? api.world.getMapAtlasRun(projectId, preferredRunId) : null,
    ])
    const selectedRun = preferredRun || latest
    const selectedReview = selectedRun ? await api.world.getMapAtlasRunResults(projectId, selectedRun.id) : { mode: "review", nodes: [], total_pages: 0 }
    if (!mounted || epoch !== dataEpoch || projectId !== props.projectId) return
    atlas.value = savedAtlas
    pageHistory.value = history
    latestRunId.value = latest?.id || null
    currentRun.value = selectedRun
    review.value = selectedReview
    syncSelection()
    schedulePoll()
    await nextTick(); await loadImages()
  } catch (err) { if (epoch === dataEpoch) setError(err) } finally { if (epoch === dataEpoch) loading.value = false }
}
function syncSelection() {
  if (!visiblePages.value.some(page => page.id === activePageId.value)) activePageId.value = visiblePages.value[0]?.id || null
  if (!oldPages.value.some(page => page.id === oldPageId.value)) oldPageId.value = oldPages.value[0]?.id || null
  const validReferences = new Set(referenceChoices.value.map(item => item.id))
  selectedReferencePageIds.value = selectedReferencePageIds.value.filter(id => validReferences.has(id))
}
function schedulePoll() {
  clearTimeout(pollTimer); pollTimer = null
  if (["planning", "generating"].includes(currentRun.value?.status)) pollTimer = setTimeout(refreshRun, 2500)
}
async function refreshRun() {
  if (!currentRun.value) return
  if (busy.value || refreshing.value) { schedulePoll(); return }
  const epoch = dataEpoch
  const projectId = props.projectId
  const runId = currentRun.value.id
  refreshing.value = true
  let failed = false
  try {
    const refreshedRun = await api.world.getMapAtlasRun(projectId, runId)
    const refreshedReview = await api.world.getMapAtlasRunResults(projectId, runId)
    if (!mounted || epoch !== dataEpoch || projectId !== props.projectId || currentRun.value?.id !== runId) return
    currentRun.value = refreshedRun
    review.value = refreshedReview
    syncSelection(); await loadImages()
  } catch (err) { if (epoch === dataEpoch) { failed = true; setError(err); clearTimeout(pollTimer) } } finally { refreshing.value = false; if (!failed) schedulePoll() }
  }
async function startRun(fullRebuild) {
  if (writeLocked.value || runUnfinished.value) return
  dataEpoch += 1
  busy.value = true; clearError(); tab.value = "review"
  try {
    currentRun.value = await api.world.createMapAtlasRun(props.projectId, { ...options, style_note: options.style_note || null, full_rebuild: fullRebuild })
    latestRunId.value = currentRun.value.id
    review.value = { mode: "review", run: currentRun.value, nodes: [], total_pages: 0 }
    schedulePoll(); toast("地图册任务已开始", "success")
  } catch (err) { setError(err) } finally { busy.value = false }
}
async function stopRun() {
  if (busy.value || !currentRun.value || currentRun.value.stop_requested) return
  dataEpoch += 1
  busy.value = true
  try { await api.world.stopMapAtlasRun(props.projectId, currentRun.value.id); currentRun.value.stop_requested = true; toast("会在当前页完成后停止", "info") } catch (err) { setError(err) } finally { busy.value = false }
}
async function resumeRun() {
  if (writeLocked.value || !currentRun.value) return
  dataEpoch += 1
  busy.value = true
  try {
    currentRun.value = await api.world.resumeMapAtlasRun(props.projectId, currentRun.value.id, false)
  } catch (err) {
    if (err?.body?.detail?.code === "retry_requires_confirmation" || err?.detail?.code === "retry_requires_confirmation") {
      if (!confirm("上次图片请求可能已经产生费用。确定再次调用并可能重复扣费吗？")) { busy.value = false; return }
      try { currentRun.value = await api.world.resumeMapAtlasRun(props.projectId, currentRun.value.id, true) } catch (confirmedError) { setError(confirmedError) }
    } else setError(err)
  } finally { busy.value = false; schedulePoll() }
}
async function adoptPage() {
  if (writeLocked.value || !activePage.value) return
  const hasConflicts = evidence.value.conflicts.length > 0
  if (hasConflicts && !confirm("这张图涉及资料冲突。确认仍将它加入地图册吗？")) return
  if (await reviewPage("adopt", { confirm_conflicts: hasConflicts })) toast("已增加，原有图片未改变", "success")
}
async function rejectPage() {
  if (writeLocked.value || !activePage.value) return
  if (await reviewPage("reject")) toast("已放入不加入历史，原地图册未改变", "info")
}
async function reviewPage(action, extra = {}) {
  if (writeLocked.value || !activePage.value) return false
  const runId = currentRun.value?.id
  dataEpoch += 1
  busy.value = true
  try {
    await api.world.reviewMapAtlasPage(props.projectId, activePage.value.id, action, { expected_updated_at: activePage.value.updated_at, ...extra })
    await loadAll(runId === latestRunId.value ? null : runId)
    return true
  } catch (err) { setError(err); return false } finally { busy.value = false }
}
async function archivePage(page) {
  if (writeLocked.value || !page?.id) return
  if (!confirm(`确定把“${page.title}”这张图片移出地图册吗？之后仍可恢复。`)) return
  dataEpoch += 1
  busy.value = true
  try { await api.world.reviewMapAtlasPage(props.projectId, page.id, "archive", { expected_updated_at: page.updated_at }); await loadAll(); toast("已移出地图册，可从历史恢复", "success") } catch (err) { setError(err) } finally { busy.value = false }
}
async function restorePage(page) {
  if (writeLocked.value || page?.review_status !== "deprecated") return
  dataEpoch += 1
  busy.value = true
  try { await api.world.reviewMapAtlasPage(props.projectId, page.id, "restore", { expected_updated_at: page.updated_at }); await loadAll(); toast("已恢复到地图册", "success") } catch (err) { setError(err) } finally { busy.value = false }
}
async function retryPage() {
  if (writeLocked.value || !activePage.value) return
  const needsConfirm = activePage.value.generation_status === "retry_requires_confirmation"
  if (needsConfirm && !confirm("上次图片请求可能已经产生费用。确定再次调用并可能重复扣费吗？")) return
  const runId = currentRun.value?.id
  dataEpoch += 1
  busy.value = true
  try { await api.world.retryMapAtlasPage(props.projectId, activePage.value.id, needsConfirm); await loadAll(runId === latestRunId.value ? null : runId) } catch (err) { setError(err) } finally { busy.value = false }
}
async function derivePage(mode) {
  if (writeLocked.value || !activePage.value) return
  dataEpoch += 1
  busy.value = true
  try {
    const page = mode === "edit"
      ? await api.world.editMapAtlasPage(props.projectId, activePage.value.id, { instruction: editInstruction.value, referencePageIds: selectedReferencePageIds.value, mask: maskFile.value })
      : await api.world.regenerateMapAtlasPage(props.projectId, activePage.value.id, { instruction: editInstruction.value || null, reference_page_ids: selectedReferencePageIds.value })
    currentRun.value = await api.world.getMapAtlasRun(props.projectId, page.run_id)
    latestRunId.value = page.run_id
    review.value = await api.world.getMapAtlasRunResults(props.projectId, page.run_id)
    activePageId.value = page.id; editInstruction.value = ""; maskFile.value = null; selectedReferencePageIds.value = []; schedulePoll()
    toast("新的候选正在生成，来源图不会改变", "success")
  } catch (err) { setError(err) } finally { busy.value = false }
}
function openSource(target, source = {}) {
  const router = getRouter(); const query = new URLSearchParams()
  const kind = target.kind || target.type || target.source_type
  if (["world_bible_page", "page"].includes(kind)) { if (target.page_id || target.id) query.set("page_id", target.page_id || target.id); return router?.navigate("world", "bible", true, query) }
  if (["core_entity", "world_entity", "entity", "world_event", "event", "profile"].includes(kind)) { if (target.entity_id || target.id) query.set("entity_id", target.entity_id || target.id); query.set("q", target.name || target.title || source.title || ""); return router?.navigate("world", "objects", true, query) }
  if (["world_bible_draft"].includes(kind)) { if (target.draft_id || target.id) query.set("draft_id", target.draft_id || target.id); return router?.navigate("world", "bible", true, query) }
  if (["outline_scene", "scene", "scenes"].includes(kind)) { if (target.scene_id || target.id) query.set("scene_id", target.scene_id || target.id); return router?.navigate("outline", "scenes", true, query) }
  if (["writing", "chapter", "draft"].includes(kind)) { if (target.chapter_index) query.set("chapter_index", String(target.chapter_index)); return router?.navigate("writing", null, true, query) }
  toast("这个来源暂时没有可打开的页面", "info")
}
function openAnnotation(annotation) {
  if (suppressedAnnotationClickId === annotation.id) { suppressedAnnotationClickId = null; return }
  if (!annotation.target_node_id) return
  const target = visibleNodes.value.find(({ node }) => node.id === annotation.target_node_id)?.node
    || flattenNodes(atlas.value.nodes || []).find(({ node }) => node.id === annotation.target_node_id)?.node
  if (target) { if (!visibleNodes.value.some(({ node }) => node.id === target.id)) tab.value = "atlas"; nextTick(() => selectNode(target)) }
}
function startAnnotationDrag(event, annotation) {
  if (writeLocked.value || tab.value !== "atlas" || globalThis.matchMedia?.("(max-width: 900px)").matches || !globalThis.matchMedia?.("(pointer: fine)").matches || !imageCanvas.value) return
  event.preventDefault(); drag = { annotation, rect: imageCanvas.value.getBoundingClientRect(), moved: false }
  globalThis.addEventListener("pointermove", dragAnnotation); globalThis.addEventListener("pointerup", endAnnotationDrag, { once: true })
}
function dragAnnotation(event) {
  if (!drag) return
  drag.moved = true
  drag.annotation.position_x = Math.min(1, Math.max(0, (event.clientX - drag.rect.left) / drag.rect.width))
  drag.annotation.position_y = Math.min(1, Math.max(0, (event.clientY - drag.rect.top) / drag.rect.height))
}
async function endAnnotationDrag() {
  globalThis.removeEventListener("pointermove", dragAnnotation)
  const current = drag; drag = null
  if (!current?.moved) return
  suppressedAnnotationClickId = current.annotation.id
  setTimeout(() => { if (suppressedAnnotationClickId === current.annotation.id) suppressedAnnotationClickId = null }, 0)
  if (writeLocked.value) { await loadAll(); return }
  dataEpoch += 1
  busy.value = true
  try {
    const updated = await api.world.updateMapAtlasAnnotation(props.projectId, current.annotation.id, { position_x: current.annotation.position_x, position_y: current.annotation.position_y, expected_updated_at: current.annotation.updated_at })
    Object.assign(current.annotation, updated); toast("标注位置已保存", "success")
  } catch (err) { setError(err); await loadAll() } finally { busy.value = false }
}
function friendlyError(err) {
  const code = err?.body?.detail?.code || err?.detail?.code
  if (code === "insufficient_sources") return `已确认资料不足。${insufficientSourcesHelp}`
  if (code === "image_connection_required") return "请先到账户设置连接 OpenAI 图片服务"
  if (code === "image_auth_failed") return "OpenAI 图片连接已失效，请在账户设置中重新连接"
  if (code === "moderation_blocked") return "图片请求未通过安全检查，请调整画面说明后重试"
  if (code === "image_quota_exhausted") return "OpenAI 图片额度不足，请检查账户额度"
  if (code === "image_permission_denied") return "OpenAI 图片权限不可用，账户可能需要完成组织验证"
  if (code === "image_rate_limited") return "OpenAI 图片服务繁忙，请稍后重试"
  if (["image_connection_failed", "retry_requires_confirmation"].includes(code)) return "上次图片请求结果未知，确认可能重复扣费后才能重试"
  if (code === "image_request_invalid") return "图片说明或参考图不符合要求，请修改后重试"
  if (code === "image_storage_failed") return "地图图片保存失败，原地图册没有改变，请稍后重试"
  if (["image_provider_unavailable", "image_provider_failed", "image_response_invalid", "image_provider_interrupted", "image_preparation_failed", "map_atlas_workflow_failed", "worker_interrupted"].includes(code)) return "地图册生成服务暂时不可用，已完成的候选仍会保留"
  return err?.message || "地图册操作失败"
}
function setError(err) {
  errorCode.value = err?.body?.detail?.code || err?.detail?.code || ""
  error.value = friendlyError(err)
}
function clearError() { error.value = ""; errorCode.value = "" }
function openImageSettings() { getRouter()?.navigate("settings") }
async function viewRun(runId) {
  if (writeLocked.value || !runId || runId === currentRun.value?.id) return
  tab.value = "review"
  await loadAll(runId === latestRunId.value ? null : runId)
}
function selectTab(value) {
  tab.value = value
}

watch(tab, () => { syncSelection(); nextTick(loadImages) })
watch(activePageId, () => { oldPageId.value = oldPages.value[0]?.id || null; nextTick(loadImages) })
watch(oldPageId, loadImages)
onMounted(loadAll)
onBeforeUnmount(() => { mounted = false; clearTimeout(pollTimer); globalThis.removeEventListener("pointermove", dragAnnotation); globalThis.removeEventListener("pointerup", endAnnotationDrag); for (const pageId of Object.keys(imageUrls)) releaseImage(pageId) })
</script>

<style scoped>
.atlas-workspace{display:grid;gap:16px;padding:20px;min-width:0}.atlas-header,.atlas-options,.atlas-run,.atlas-page-header,.atlas-primary-actions,.atlas-run-actions,.atlas-review-actions,.atlas-source{display:flex;align-items:center;gap:12px}.atlas-header{justify-content:space-between}.atlas-header h1,.atlas-page h2{margin:0}.atlas-header p{margin:4px 0;color:var(--text-secondary,#68707d)}.atlas-eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.atlas-primary-actions{align-self:flex-end}.atlas-more{position:relative}.atlas-more[open] button{position:absolute;right:0;top:42px;z-index:4;white-space:nowrap}.atlas-options{align-items:end;flex-wrap:wrap}.atlas-options label{display:grid;gap:6px;font-size:13px}.atlas-options .atlas-style{flex:1 1 280px}.atlas-options details label{display:block;margin-top:8px}.atlas-alert,.atlas-run{justify-content:space-between}.atlas-run{display:grid;grid-template-columns:minmax(220px,1fr) minmax(160px,2fr) auto}.atlas-run div:first-child{display:flex;gap:10px;flex-wrap:wrap}.atlas-run progress{width:100%}.atlas-run p{grid-column:1/-1;margin:0;color:#9a4d32}.atlas-tabs{display:flex;border-bottom:1px solid var(--border-color,#dfe3e8)}.atlas-tabs button{padding:12px 18px;border:0;border-bottom:3px solid transparent;background:none;font-weight:700}.atlas-tabs button.active{border-color:var(--primary,#496fe3);color:var(--primary,#496fe3)}.atlas-tabs span{margin-left:6px;font-size:12px}.atlas-empty{text-align:center;padding:48px}.atlas-all-rejected{padding:20px}.atlas-browser{display:grid;grid-template-columns:230px minmax(0,1fr);gap:16px;min-width:0}.atlas-tree{display:flex;flex-direction:column;align-self:start;padding:8px;max-height:72vh;overflow:auto}.atlas-tree button{display:flex;gap:7px;align-items:center;border:0;background:none;border-radius:7px;padding:9px;text-align:left}.atlas-tree button:hover,.atlas-tree button.active{background:var(--surface-muted,#eef2fa)}.atlas-tree button span{font-size:11px;color:var(--text-secondary,#68707d)}.atlas-tree button small{margin-left:auto}.atlas-page{min-width:0}.atlas-page-header{justify-content:space-between}.atlas-page-header p{margin:0;color:var(--text-secondary,#68707d)}.atlas-zoom{display:flex;align-items:center;gap:8px}.atlas-images{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}.atlas-images.compare{grid-template-columns:repeat(2,minmax(0,1fr))}.atlas-images figure{min-width:0;margin:0}.atlas-images figcaption{margin:8px 0;font-weight:700}.atlas-image-viewport{display:flex;align-items:center;min-height:220px;overflow:auto;border-radius:10px;background:#20242c;color:#fff}.atlas-image-canvas{position:relative;flex:0 0 auto;margin-inline:auto;transition:width .15s ease}.atlas-image-canvas img{display:block;width:100%;height:100%;object-fit:contain}.atlas-image-state{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;min-height:220px}.atlas-annotation{position:absolute;transform:translate(-50%,-50%);border:1px solid rgba(255,255,255,.8);border-radius:999px;padding:4px 8px;background:rgba(20,24,32,.78);color:white;white-space:nowrap;cursor:pointer;touch-action:manipulation}.atlas-review-actions{margin-top:14px;flex-wrap:wrap}.atlas-charge-warning{flex:1 0 100%;margin:0;padding:10px;border:1px solid #d68c72;border-radius:8px;background:#fff2ed;color:#7b351f}.atlas-edit{flex:1 1 320px}.atlas-edit textarea{display:block;width:100%;margin:10px 0}.atlas-edit p{font-size:12px;color:var(--text-secondary,#68707d)}.atlas-mask{display:block}.atlas-references{display:grid;gap:7px;margin:10px 0;border:1px solid var(--border-color,#dfe3e8);border-radius:8px}.atlas-references label{display:flex;align-items:center;gap:7px}.atlas-evidence{margin-top:20px;border-top:1px solid var(--border-color,#dfe3e8);padding-top:16px}.atlas-evidence-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.atlas-evidence-grid>div{padding:12px;border-radius:8px;background:var(--surface-muted,#f4f6f9)}.atlas-evidence-grid ul{padding-left:20px}.atlas-candidate-note{display:inline-block;margin:6px 0;padding:2px 7px;border-radius:999px;background:#fff2cc;color:#795d00;font-size:12px}.atlas-conflicts{border:1px solid #d68c72;background:#fff2ed!important}.atlas-source{justify-content:space-between;border-top:1px solid var(--border-color,#dfe3e8);padding:10px 0}.atlas-source p{margin:3px 0}.atlas-history-status{font-weight:700}.atlas-error{color:#a8412d}.atlas-more summary,.atlas-edit summary{list-style:none}.atlas-more summary::-webkit-details-marker,.atlas-edit summary::-webkit-details-marker{display:none}
@media(max-width:900px){.atlas-workspace{padding:12px}.atlas-header,.atlas-options,.atlas-run{align-items:stretch}.atlas-header{flex-direction:column}.atlas-primary-actions{align-self:stretch}.atlas-browser{grid-template-columns:1fr}.atlas-tree{max-height:180px}.atlas-images.compare,.atlas-evidence-grid{grid-template-columns:1fr}.atlas-run{grid-template-columns:1fr}.atlas-mask{display:none}.atlas-edit p::after{content:" 蒙版与精确标注请在桌面完成。"}}
</style>
