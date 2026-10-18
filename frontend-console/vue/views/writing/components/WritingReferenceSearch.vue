<template>
  <section class="writing-reference-search" aria-label="查这里">
    <h3>查这里</h3>
    <form @submit.prevent="search">
      <label>查找范围<select v-model="searchMode" @change="resetSearch"><option value="objects">世界对象</option><option value="previous">前文中的词句</option></select></label>
      <label>名称、别名或词句<input v-model="query" maxlength="200" type="search" /></label>
      <button type="submit" class="btn btn-sm" :disabled="busy || !query.trim()">{{ busy ? '查找中…' : searchMode === 'previous' ? '查找前文' : '查找对象' }}</button>
    </form>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="searched && !busy && !items.length && !error" role="status">没有找到匹配资料，可以换一个词句再试。</p>
    <ul><li v-for="(item, index) in items" :key="index">
      <template v-if="searchMode === 'objects'">
        <button type="button" class="btn btn-sm" @click="$emit('open-object', item.id)">{{ item.name }}</button>
        <p>{{ item.summary || '尚无简介' }}</p>
        <button type="button" class="btn btn-sm" :disabled="isPinned({ kind: 'object', id: item.id })" @click="pin({ kind: 'object', id: item.id })">固定参考：{{ item.name }}</button>
      </template>
      <template v-else>
        <strong>{{ item.title || `第 ${item.chapter_index} 章` }}</strong>
        <p>{{ item.snippet }}</p>
        <button type="button" class="btn btn-sm" :disabled="reading" @click="readSource(item.source_ref)">核对原文</button>
        <button type="button" class="btn btn-sm" :disabled="!item.source_ref || isPinned({ kind: 'prose', source_ref: item.source_ref })" @click="pin({ kind: 'prose', source_ref: item.source_ref })">固定这段前文</button>
      </template>
    </li></ul>
    <p v-if="hasMore">当前展示前 20 个匹配{{ searchMode === 'objects' ? '对象' : '词句' }}，请补充关键词缩小范围。</p>
    <p v-for="warning in warnings" :key="warning" role="status">{{ warning }}</p>
    <p>名称和字面匹配只是查找线索，不代表身份或剧情依赖已经证实。前文只查当前章之前的已保存工作稿。</p>
    <p v-if="reading" role="status">正在核对原文版本…</p>
    <p v-if="readError" role="alert">{{ readError }}</p>
    <article v-if="source" class="writing-reference-search__source" aria-label="核对原文">
      <strong>{{ source.title || `第 ${source.source_ref.chapter_index} 章` }}</strong>
      <p>{{ source.text }}</p><p v-for="warning in source.warnings" :key="warning">{{ warning }}</p>
      <button class="btn btn-sm" type="button" @click="source = null">收起原文</button>
    </article>
    <section v-if="pins.length" aria-label="固定参考">
      <h4>固定参考</h4>
      <p>只固定阅读资料；不会据此批准修改，也不会自动扩大助手的参考范围。</p>
      <p v-if="pinsLoading" role="status">正在核对参考…</p>
      <article v-for="(item, index) in pins" :key="pinKey(item.ref)">
        <strong>{{ item.data?.name || item.data?.title || `参考 ${index + 1}` }}</strong>
        <p v-if="item.error" role="alert">{{ item.error }} <button type="button" class="btn btn-sm" @click="loadPins">重新读取参考</button></p>
        <p v-else>{{ item.data?.summary || item.data?.text || '尚无简介' }}</p>
        <p v-for="warning in item.data?.warnings || []" :key="warning">{{ warning }}</p>
        <button v-if="item.ref.kind === 'object' && item.data" type="button" class="btn btn-sm" @click="$emit('open-object', item.ref.id)">打开对象资料</button>
        <button type="button" class="btn btn-sm" @click="unpin(item.ref)">取消固定：{{ item.data?.name || item.data?.title || `参考 ${index + 1}` }}</button>
      </article>
    </section>
    <p v-if="pinStatus" role="status">{{ pinStatus }}</p>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getApi, getLocalDraftAccountScope, getLocalDraftStorage } from '../../../bridge/index.js'
import { readLocalDraftBackup, writeLocalDraftBackup } from '../../../shared/localDraftBackup.js'
const props = defineProps({ projectId: { type: String, required: true }, chapterIndex: { type: Number, default: null }, selection: { type: String, default: '' } })
defineEmits(['open-object'])
const query = ref(''), searchMode = ref('objects'), items = ref([]), busy = ref(false), error = ref(''), searched = ref(false), hasMore = ref(false), warnings = ref([])
const source = ref(null), reading = ref(false), readError = ref('')
const pins = ref([]), pinsLoading = ref(false), pinStatus = ref('')
let epoch = 0, readEpoch = 0, pinEpoch = 0
function pinKey(value) { return value.kind === 'object' ? `object:${value.id}` : `prose:${JSON.stringify(value.source_ref)}` }
function isPinned(value) { return pins.value.some(item => pinKey(item.ref) === pinKey(value)) }
function scope() { return { accountId: getLocalDraftAccountScope(), projectId: props.projectId, objectId: 'writing-references', section: 'pinned' } }
function resetSearch() { epoch += 1; items.value = []; busy.value = false; searched.value = false; error.value = ''; warnings.value = []; hasMore.value = false }
watch(() => props.selection, value => { if (value.trim()) query.value = value.trim().slice(0, 200) })
watch([() => props.projectId, () => getLocalDraftAccountScope()], () => {
  resetSearch(); query.value = ''; readEpoch += 1; reading.value = false; source.value = null; readError.value = ''; pinEpoch += 1; pinsLoading.value = false; pinStatus.value = ''
  const saved = readLocalDraftBackup(getLocalDraftStorage(), scope())
  const refs = saved.draft?.payload?.references
  pins.value = (Array.isArray(refs) ? refs : []).slice(0, 20).filter(item => (item?.kind === 'object' && typeof item.id === 'string') || (item?.kind === 'prose' && item.source_ref?.draft_id)).map(ref => ({ ref, data: null, error: '' }))
  if (!saved.ok) pinStatus.value = '固定参考记录暂时不可读取；当前页面仍可查找。'
  if (pins.value.length) void loadPins()
}, { immediate: true })
watch(() => props.chapterIndex, () => { resetSearch(); readEpoch += 1; source.value = null; reading.value = false; readError.value = '' })
onBeforeUnmount(() => { epoch += 1; readEpoch += 1; pinEpoch += 1 })
async function search() {
  if (!query.value.trim() || busy.value) return
  if (searchMode.value === 'previous' && !(props.chapterIndex > 1)) { error.value = '当前章之前还没有章节可查。'; return }
  const token = ++epoch
  busy.value = true; error.value = ''; searched.value = true
  try {
    const result = searchMode.value === 'objects'
      ? await getApi().world.listEntities({ novel_id: props.projectId, q: query.value.trim(), skip: 0, limit: 20 })
      : await getApi().context.grepEvidence({ novel_id: props.projectId, pattern: query.value.trim(), content_mode: 'working', visibility: { mode: 'author' }, chapter_to: props.chapterIndex - 1, skip: 0, limit: 20, group_by_chapter: false })
    if (token !== epoch) return
    items.value = result.items || result.hits || []; hasMore.value = result.total > items.value.length; warnings.value = result.warnings || []
  } catch (reason) { if (token === epoch) { items.value = []; error.value = reason.message || '查找失败，输入仍保留。' } }
  finally { if (token === epoch) busy.value = false }
}
function sourceRequest(ref) { return { novel_id: props.projectId, content_mode: ref.content_mode, visibility: { mode: 'author' }, source_ref: ref, before: 1, after: 1 } }
async function readSource(ref) {
  if (!ref) return
  const token = ++readEpoch
  reading.value = true; readError.value = ''; source.value = null
  try { const result = await getApi().context.readEvidence(sourceRequest(ref)); if (token === readEpoch) source.value = result }
  catch (reason) { if (token === readEpoch) readError.value = reason.message || '原文版本不可核对，请重新查找。' }
  finally { if (token === readEpoch) reading.value = false }
}
async function loadPins() {
  const token = ++pinEpoch, projectId = props.projectId
  pinsLoading.value = true
  const loaded = await Promise.all(pins.value.map(async item => {
    try {
      const data = item.ref.kind === 'object' ? await getApi().world.getEntity(item.ref.id, projectId) : await getApi().context.readEvidence(sourceRequest(item.ref.source_ref))
      return { ...item, data, error: '' }
    } catch (reason) { return { ...item, data: null, error: reason.message || '参考不可用；原引用仍保留，可重新查找或取消固定。' } }
  }))
  if (token === pinEpoch) { pins.value = loaded; pinsLoading.value = false }
}
function persistPins() {
  const result = writeLocalDraftBackup(getLocalDraftStorage(), scope(), null, { references: pins.value.map(item => item.ref) })
  pinStatus.value = result.ok ? '固定参考已记在此浏览器；未复制正文或修改作品。' : '固定参考未能备份到本机；当前页面仍保留，刷新后可能丢失。'
}
function pin(ref) {
  if (isPinned(ref)) return
  if (pins.value.length >= 20) { pinStatus.value = '最多固定 20 项参考，请先取消不再需要的资料。'; return }
  pins.value.push({ ref, data: null, error: '' }); persistPins(); void loadPins()
}
function unpin(ref) { pinEpoch += 1; pins.value = pins.value.filter(item => pinKey(item.ref) !== pinKey(ref)); pinsLoading.value = false; persistPins(); if (pins.value.length) void loadPins() }
</script>

<style scoped>
.writing-reference-search{padding:16px;border-bottom:1px solid var(--border-color,var(--border));line-height:1.6}
.writing-reference-search form,.writing-reference-search label{display:grid;gap:8px}
.writing-reference-search input,.writing-reference-search select{min-width:0;width:100%;box-sizing:border-box;min-height:44px;background:var(--bg-muted);color:inherit;border:1px solid var(--border-color,var(--border));padding:8px}
.writing-reference-search ul{padding:0;list-style:none}.writing-reference-search article,.writing-reference-search li{padding-block:10px;border-bottom:1px solid var(--border-color,var(--border))}
.writing-reference-search p{font-size:12px;color:var(--text-secondary);overflow-wrap:anywhere;white-space:pre-wrap}.writing-reference-search button{min-height:44px;max-width:100%;white-space:normal;text-align:start}
</style>
