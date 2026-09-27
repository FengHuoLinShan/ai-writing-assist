<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getApi, getRouteQuery, getRouter } from '../../bridge/index.js'
import { openingOperationKey, clearOpeningOperation } from './interactionSession.js'

const props = defineProps({ disabled: Boolean })
const cards = ref([]), images = ref({}), imageErrors = ref({}), error = ref(''), starting = ref('')
let alive = true
const labels = { exploration: '探索日常', source_character: '原作角色', original_character: '原创角色', event: '事件切入', scene: '场景切入' }
async function load() {
  error.value = ''
  try {
    const projectId = getRouteQuery().get('project_id')
    const result = await getApi().interactions.listOpenings(projectId ? { project_id: projectId } : {})
    if (!alive) return
    cards.value = result.items
    await Promise.all(cards.value.filter(card => card.has_image).map(async card => {
      try {
        const blob = await getApi().interactions.fetchOpeningImage(card.id)
        if (!alive) return
        if (images.value[card.id]) URL.revokeObjectURL(images.value[card.id])
        images.value[card.id] = URL.createObjectURL(blob)
      } catch { if (alive) imageErrors.value[card.id] = true }
    }))
  } catch (err) { if (alive) error.value = err.message || '开局暂时无法读取，仍可在下方自行设定。' }
}
async function start(card) {
  if (starting.value || props.disabled) return
  starting.value = card.id; error.value = ''
  try {
    const result = await getApi().interactions.startOpening(card.id, { idempotency_key: openingOperationKey(card.id) })
    if (!alive) return
    await getRouter().navigate('interaction', result.journey.id)
    clearOpeningOperation(card.id)
  } catch (err) { if (alive) error.value = err.message || '暂时无法进入，重试会继续同一次创建。' }
  finally { if (alive) starting.value = '' }
}
onMounted(load)
onBeforeUnmount(() => { alive = false; Object.values(images.value).forEach(url => URL.revokeObjectURL(url)) })
</script>

<template>
  <section v-if="cards.length || error" class="rp-opening-catalog" aria-label="从作品快速开始">
    <header><h3>从作品走进故事</h3><p>选一个开局，人物、起点与资料会一同带入。进入后可以自由行动。</p></header>
    <p v-if="error" role="alert">{{ error }} <button type="button" :disabled="Boolean(starting)" @click="load">重新读取</button></p>
    <div class="rp-entry-grid">
      <article v-for="card in cards" :key="card.id" class="rp-entry-card">
        <img v-if="images[card.id]" :src="images[card.id]" :alt="card.title + ' · 开局配图'" />
        <p v-else-if="imageErrors[card.id]" class="rp-entry-image-status">配图版本暂不可用，开局资料仍保留。</p>
        <div class="rp-entry-copy">
          <span>{{ labels[card.experience_kind] }} · {{ card.source_title }}</span>
          <h4>{{ card.title }}</h4><p>{{ card.description }}</p>
          <span>{{ card.player_label }} · {{ card.progress_label }}</span>
          <small>{{ card.curation }}</small>
          <button type="button" :disabled="disabled || Boolean(starting)" @click="start(card)">{{ starting === card.id ? '正在进入…' : '从这里开始' }}</button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.rp-opening-catalog { margin-block: 1.25rem 2rem; }
.rp-opening-catalog header p, .rp-entry-copy > span, .rp-entry-copy small { color: var(--text-secondary); }
.rp-entry-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 1rem; }
.rp-entry-card { overflow: hidden; border: 1px solid var(--border); border-radius: 16px; background: var(--bg-base); display: flex; flex-direction: column; }
.rp-entry-card > img { width: 100%; aspect-ratio: 3 / 2; object-fit: cover; object-position: center 28%; }
.rp-entry-copy { display: flex; flex-direction: column; flex: 1; gap: .65rem; padding: 1rem; }
.rp-entry-copy h4 { margin: 0; font-size: 1.15rem; }
.rp-entry-copy p { margin: 0; line-height: 1.6; }
.rp-entry-copy > span, .rp-entry-copy small { font-size: .8rem; line-height: 1.5; }
.rp-entry-copy button { margin-top: auto; min-height: 44px; border: 1px solid var(--border); border-radius: 10px; background: var(--accent); color: white; cursor: pointer; }
.rp-entry-copy button:disabled { opacity: .6; cursor: wait; }
.rp-entry-image-status { padding: 1rem; color: var(--text-secondary); }
</style>
