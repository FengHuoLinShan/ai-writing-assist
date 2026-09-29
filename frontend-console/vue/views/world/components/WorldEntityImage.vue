<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { getApi, getRouter } from '../../../bridge/index.js'
import { projectSettingsSession } from '../../settings/projectSettingsSession.js'
import LocalRunApproval from '../../../components/LocalRunApproval.vue'
const props = defineProps({ projectId: { type: String, required: true }, entity: { type: Object, required: true } })
const imageUrl = ref(''), status = ref(''), error = ref(''), uploading = ref(false), input = ref(null)
let generation = 0, controller = null

// 本机 CLI 生图
const generationOpen = ref(false)
const generationLoading = ref(false)
const generationInfo = ref(null)
const generationError = ref('')
const prompt = ref('')
const promptEdited = ref(false)
const creating = ref(false)
const activeCandidate = ref(null)
const previewUrl = ref('')
const adopting = ref(false)
const discarding = ref(false)
const recentPreviewUrls = reactive({})
const recentBusyId = ref(null)
let genGeneration = 0
let pollTimer = null

function entityId() { return props.entity.id || props.entity.entity_id }

function reset() {
  generation += 1; controller?.abort(); controller = null
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''; error.value = ''; status.value = ''; uploading.value = false
}
async function loadImage(token = generation) {
  try {
    const blob = await getApi().world.fetchEntityImage(entityId(), props.projectId, 'full')
    if (token !== generation) return
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = URL.createObjectURL(blob)
  } catch (err) { if (token === generation) error.value = err.message || '图片读取失败，请重试' }
}
async function upload(event) {
  const file = event.target.files?.[0]
  if (!file || uploading.value) return
  error.value = ''; status.value = ''
  if (!['image/png', 'image/jpeg'].includes(file.type) || file.size >= 6 * 1024 * 1024) {
    error.value = '请选择小于 6 MiB 的 PNG 或 JPEG 图片'; event.target.value = ''; return
  }
  const token = generation
  controller = new AbortController(); uploading.value = true
  try {
    await getApi().world.uploadEntityImage(entityId(), file, props.projectId, null, { signal: controller.signal })
    if (token !== generation) return
    const entity = props.entity; entity.has_image = true
    status.value = "图片已保存"
    await loadImage(token)
  } catch (err) { if (token === generation) error.value = err.message || '上传失败，原图片仍保留' }
  finally { if (token === generation) { uploading.value = false; event.target.value = '' } }
}

function resetGeneration() {
  genGeneration += 1
  clearTimeout(pollTimer); pollTimer = null
  generationOpen.value = false; generationLoading.value = false; generationInfo.value = null; generationError.value = ''
  prompt.value = ''; promptEdited.value = false; creating.value = false; activeCandidate.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = ''
  adopting.value = false; discarding.value = false
  for (const id of Object.keys(recentPreviewUrls)) { URL.revokeObjectURL(recentPreviewUrls[id]); delete recentPreviewUrls[id] }
  recentBusyId.value = null
}

function friendlyGenerationError(err) {
  const code = err?.body?.error
  if (code === 'local_image_executor_required') return '本机 CLI 生图尚未配置，请先到作品设置完成配置'
  if (code === 'image_generation_in_progress') return '已有一张图片正在生成，请等待完成后再试'
  return err?.message || '生成请求失败，请重试'
}

async function loadGenerationInfo() {
  generationLoading.value = true; generationError.value = ''
  const token = ++genGeneration
  try {
    const info = await getApi().world.imageGeneration(entityId(), props.projectId)
    if (token !== genGeneration) return
    generationInfo.value = info
    if (!promptEdited.value) prompt.value = info.default_prompt || ''
  } catch (err) {
    if (token === genGeneration) generationError.value = err.message || '生成设置读取失败'
  } finally { if (token === genGeneration) generationLoading.value = false }
}

async function toggleGeneration() {
  generationOpen.value = !generationOpen.value
  if (generationOpen.value) await loadGenerationInfo()
}

function schedulePoll(token) {
  clearTimeout(pollTimer); pollTimer = null
  if (token !== genGeneration) return
  if (activeCandidate.value && ['queued', 'generating'].includes(activeCandidate.value.status)) {
    pollTimer = setTimeout(() => pollCandidate(token), 3000)
  }
}

async function pollCandidate(token) {
  if (token !== genGeneration || !activeCandidate.value) return
  try {
    const candidate = await getApi().world.imageCandidate(activeCandidate.value.id, props.projectId)
    if (token !== genGeneration) return
    activeCandidate.value = candidate
    if (candidate.status === 'review_ready') await loadPreview(candidate, token)
    schedulePoll(token)
  } catch (err) {
    if (token === genGeneration) { generationError.value = err.message || '生成状态读取失败'; schedulePoll(token) }
  }
}

async function loadPreview(candidate, token) {
  try {
    const blob = await getApi().world.fetchImageCandidateImage(candidate.id, props.projectId)
    if (token !== genGeneration || activeCandidate.value?.id !== candidate.id) return
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(blob)
  } catch (err) { if (token === genGeneration) generationError.value = err.message || '候选图片读取失败' }
}

async function createCandidate() {
  if (creating.value || !prompt.value.trim()) return
  creating.value = true; generationError.value = ''
  const token = genGeneration
  try {
    const candidate = await getApi().world.createImageCandidate(entityId(), props.projectId, prompt.value.trim())
    if (token !== genGeneration) return
    activeCandidate.value = candidate
    schedulePoll(token)
  } catch (err) {
    if (token === genGeneration) generationError.value = friendlyGenerationError(err)
  } finally { if (token === genGeneration) creating.value = false }
}

async function adoptActive() {
  if (!activeCandidate.value || adopting.value) return
  adopting.value = true; generationError.value = ''
  const token = genGeneration
  try {
    await getApi().world.adoptImageCandidate(activeCandidate.value.id, props.projectId)
    if (token !== genGeneration) return
    const entity = props.entity; entity.has_image = true
    status.value = '图片已保存'
    resetGeneration()
    await loadImage()
  } catch (err) { if (token === genGeneration) generationError.value = err.message || '采用失败，请重试' }
  finally { if (token === genGeneration) adopting.value = false }
}

async function discardActive() {
  if (!activeCandidate.value || discarding.value) return
  discarding.value = true; generationError.value = ''
  const token = genGeneration
  try {
    await getApi().world.discardImageCandidate(activeCandidate.value.id, props.projectId)
    if (token !== genGeneration) return
    resetGeneration()
    generationOpen.value = true
    await loadGenerationInfo()
  } catch (err) { if (token === genGeneration) generationError.value = err.message || '放弃失败，请重试' }
  finally { if (token === genGeneration) discarding.value = false }
}

const reviewReadyCandidates = computed(() => (generationInfo.value?.candidates || [])
  .filter((item) => item.status === 'review_ready' && item.id !== activeCandidate.value?.id))

function cleanupRecentPreview(id) {
  if (recentPreviewUrls[id]) { URL.revokeObjectURL(recentPreviewUrls[id]); delete recentPreviewUrls[id] }
}

async function loadRecentPreview(item) {
  try {
    const blob = await getApi().world.fetchImageCandidateImage(item.id, props.projectId)
    cleanupRecentPreview(item.id)
    recentPreviewUrls[item.id] = URL.createObjectURL(blob)
  } catch (err) { generationError.value = err.message || '候选图片读取失败' }
}

async function adoptRecent(item) {
  if (recentBusyId.value) return
  recentBusyId.value = item.id; generationError.value = ''
  try {
    await getApi().world.adoptImageCandidate(item.id, props.projectId)
    const entity = props.entity; entity.has_image = true
    status.value = '图片已保存'
    cleanupRecentPreview(item.id)
    await loadGenerationInfo()
    await loadImage()
  } catch (err) { generationError.value = err.message || '采用失败，请重试' }
  finally { recentBusyId.value = null }
}

async function discardRecent(item) {
  if (recentBusyId.value) return
  recentBusyId.value = item.id; generationError.value = ''
  try {
    await getApi().world.discardImageCandidate(item.id, props.projectId)
    cleanupRecentPreview(item.id)
    await loadGenerationInfo()
  } catch (err) { generationError.value = err.message || '放弃失败，请重试' }
  finally { recentBusyId.value = null }
}

function goToLocalCliSettings() {
  projectSettingsSession.tab = 'ai'
  getRouter()?.navigate('project-settings')
}

const submitLabel = computed(() => {
  if (creating.value) return '正在提交…'
  if (activeCandidate.value && ['failed', 'cancelled'].includes(activeCandidate.value.status)) return '重新生成'
  return '开始生成'
})

watch(() => [props.projectId, entityId()], () => {
  reset(); if (props.entity.has_image) void loadImage()
  resetGeneration()
}, { immediate: true })
onBeforeUnmount(() => { reset(); resetGeneration() })
</script>
<template>
  <section class="entity-image" aria-label="对象图片" :aria-busy="uploading">
    <img v-if="imageUrl" :src="imageUrl" :alt="`${entity.name}的图片`" />
    <p v-else>尚未显示图片</p>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <input ref="input" type="file" accept="image/png,image/jpeg" hidden @change="upload" />
    <div class="entity-image__actions">
      <button class="btn" :disabled="uploading" @click="input.click()">{{ uploading ? '正在上传…' : imageUrl ? '替换图片' : '上传图片' }}</button>
      <button v-if="error && entity.has_image" class="btn" :disabled="uploading" @click="loadImage()">重新读取图片</button>
      <button type="button" class="btn btn-ghost" @click="toggleGeneration">{{ generationOpen ? '收起本机生成' : '用本机 CLI 生成' }}</button>
    </div>
    <small>PNG／JPEG，小于 6 MiB，最长边不超过 4096 像素。</small>

    <section v-if="generationOpen" class="entity-image-generation" aria-label="本机 CLI 生图">
      <p v-if="generationLoading" role="status">正在读取生成设置…</p>
      <template v-else-if="generationInfo && !generationInfo.available">
        <p role="alert">{{ generationInfo.reason || '本机 CLI 生图暂时不可用' }}</p>
        <button type="button" class="btn btn-sm" @click="goToLocalCliSettings">去作品设置配置</button>
      </template>
      <template v-else-if="generationInfo">
        <template v-if="!activeCandidate || ['failed', 'cancelled'].includes(activeCandidate.status)">
          <label class="entity-image-generation__prompt">画面提示
            <textarea v-model="prompt" class="form-textarea" rows="5" maxlength="4000" @input="promptEdited = true" />
          </label>
          <p class="entity-image-generation__hint">提示已根据已确认设定草拟，可以自行修改后再生成。</p>
          <p v-if="activeCandidate?.status === 'failed'" role="alert">{{ activeCandidate.error || '生成失败，请重试' }}</p>
          <p v-if="activeCandidate?.status === 'cancelled'" role="status">已取消，可重新生成</p>
          <p v-if="generationError" role="alert">{{ generationError }}</p>
          <button type="button" class="btn btn-primary" :disabled="creating || !prompt.trim()" @click="createCandidate">{{ submitLabel }}</button>
        </template>
        <template v-else>
          <LocalRunApproval
            v-if="activeCandidate.task_id && (activeCandidate.awaiting_approval || activeCandidate.status === 'queued')"
            :project-id="projectId"
            :task-id="activeCandidate.task_id"
            :executor-kind="generationInfo.executor_kind"
            purpose="对象图片生成"
          />
          <p v-if="['queued', 'generating'].includes(activeCandidate.status)" role="status">正在生成……</p>
          <div v-if="activeCandidate.status === 'review_ready'" class="entity-image-generation__preview">
            <img v-if="previewUrl" :src="previewUrl" alt="生成的候选图片" />
            <p v-else role="status">正在读取候选图片…</p>
            <div class="entity-image-generation__preview-actions">
              <button type="button" class="btn btn-primary" :disabled="adopting" @click="adoptActive">{{ adopting ? '正在采用…' : '采用这张' }}</button>
              <button type="button" class="btn" :disabled="discarding" @click="discardActive">{{ discarding ? '正在放弃…' : '放弃' }}</button>
            </div>
            <p v-if="generationError" role="alert">{{ generationError }}</p>
          </div>
        </template>
      </template>
      <section v-if="reviewReadyCandidates.length" class="entity-image-generation__recent">
        <h4>之前生成、还未处理的候选</h4>
        <article v-for="item in reviewReadyCandidates" :key="item.id" class="entity-image-generation__recent-item">
          <img v-if="recentPreviewUrls[item.id]" :src="recentPreviewUrls[item.id]" alt="候选图片" />
          <button v-else type="button" class="btn btn-sm" @click="loadRecentPreview(item)">查看图片</button>
          <div class="entity-image-generation__recent-actions">
            <button type="button" class="btn btn-sm btn-primary" :disabled="recentBusyId === item.id" @click="adoptRecent(item)">采用这张</button>
            <button type="button" class="btn btn-sm" :disabled="recentBusyId === item.id" @click="discardRecent(item)">放弃</button>
          </div>
        </article>
      </section>
    </section>
  </section>
</template>
<style scoped>
.entity-image{display:grid;gap:8px;justify-items:start}.entity-image img{max-width:100%;max-height:320px;object-fit:contain;border-radius:var(--radius-md)}.entity-image button{min-height:44px}.entity-image small{color:var(--text-muted)}
.entity-image__actions{display:flex;flex-wrap:wrap;gap:8px}
.entity-image-generation{display:grid;gap:10px;width:100%;padding-top:8px;border-top:1px solid var(--border-color, #e2e2e2)}
.entity-image-generation__prompt{display:grid;gap:4px;width:100%}
.entity-image-generation textarea{width:100%}
.entity-image-generation__hint{color:var(--text-muted);font-size:var(--text-sm)}
.entity-image-generation__preview{display:grid;gap:8px}
.entity-image-generation__preview img{max-width:100%;max-height:320px;object-fit:contain;border-radius:var(--radius-md)}
.entity-image-generation__preview-actions{display:flex;gap:8px}
.entity-image-generation__recent{display:grid;gap:8px}
.entity-image-generation__recent-item{display:grid;gap:6px;padding:8px;border:1px solid var(--border-color, #e2e2e2);border-radius:var(--radius-md)}
.entity-image-generation__recent-item img{max-width:100%;max-height:200px;object-fit:contain}
.entity-image-generation__recent-actions{display:flex;gap:8px}
</style>
