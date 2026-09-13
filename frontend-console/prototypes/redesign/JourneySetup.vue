<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({ state: { type: String, default: 'normal' }, initialSection: { type: String, default: 'direct' } })
const emit = defineEmits(['navigate', 'open'])
const mode = ref(props.initialSection === 'source' ? 'source' : 'direct')
const sourceStatus = ref('ready')
const world = ref('白沙港，一座被潮汐记住的港口')
const identity = ref('一个带着旧海图回来的旅人')
const opening = ref('灯塔再次亮起的时候，我决定走向那条只在落潮时出现的石路。')
const chapter = ref('码头上的初次相遇')
const confirmed = ref(false)
const sourceConfirmed = ref(false)
watch([chapter, mode], () => { sourceConfirmed.value = false })
watch([world, identity, opening], () => { confirmed.value = false })
const canEnter = computed(() => Boolean(world.value.trim() && identity.value.trim() && opening.value.trim() && confirmed.value && (mode.value === 'direct' || (sourceStatus.value === 'ready' && sourceConfirmed.value))))
const sourceReady = computed(() => mode.value === 'direct' || sourceStatus.value === 'ready')
function selectSource() { mode.value = 'source'; }
function startOrganizing() { sourceStatus.value = 'organizing'; sourceConfirmed.value = false }
function finishOrganizing() { sourceStatus.value = 'ready' }
function enterReading() {
  if (canEnter.value) emit('navigate', 'reading')
}
</script>

<template>
  <div class="rd-page-scroll"><div class="rd-page-inner rd-journey-setup">
    <header class="rd-page-heading"><div><span class="rd-eyebrow">开启一段旅程 · 演示</span><h1>从哪里开始？</h1><p>写下世界、身份和开场；也可以选择一份已整理的作品资料。</p></div><button class="rd-text-button" @click="emit('navigate', 'journeys')">返回旅程列表</button></header>
    <div class="rd-journey-modes" role="group" aria-label="旅程来源"><button :aria-pressed="mode === 'direct'" @click="mode = 'direct'">直接写下世界与开场</button><button :aria-pressed="mode === 'source'" @click="selectSource">选择作品资料</button></div>
    <section v-if="mode === 'source'" class="rd-setup-source rd-panel">
      <div class="rd-detail-heading"><div><span class="rd-eyebrow">可用来源 · 演示</span><h2>潮汐来信</h2></div><span class="rd-badge" :class="sourceReady ? 'tone-green' : 'tone-orange'">{{ sourceReady ? '资料已整理 · 演示' : '正在整理 · 演示' }}</span></div>
      <p>可从第 3 章开始，角色和剧情位置会在进入阅读前再次确认。</p>
      <div v-if="sourceStatus === 'organizing'" class="rd-inline-notice tone-orange" role="status"><strong>正在整理作品资料 · 演示</strong><p>整理尚未完成，不能开始旅程。</p><button class="rd-button" @click="finishOrganizing">演示整理完成</button></div>
      <div class="rd-local-toolbar"><label class="rd-field">章节剧情点<select v-model="chapter" :disabled="!sourceReady"><option>码头上的初次相遇</option><option>雾中的灯塔</option><option>灯火归来的夜晚</option></select></label><label><input v-model="sourceConfirmed" type="checkbox" :disabled="!sourceReady"/>我确认从这个位置开始</label><button class="rd-button" @click="startOrganizing">演示重新整理</button></div>
    </section>
    <section class="rd-panel">
      <div class="rd-detail-heading"><div><span class="rd-eyebrow">角色与开场</span><h2>你想以谁的目光进入？</h2></div><span class="rd-badge tone-purple">不生成正文 · 演示</span></div>
      <div class="rd-setup-fields"><label class="rd-field">世界<input v-model="world" aria-label="故事世界"/></label><label class="rd-field">你的身份<input v-model="identity" aria-label="旅程身份"/></label><label class="rd-field">开场<textarea v-model="opening" rows="4" aria-label="故事开场"/></label></div>
      <label class="rd-check-label"><input v-model="confirmed" type="checkbox" aria-label="确认角色与开场"/>确认角色与开场</label>
    </section>
    <div class="rd-local-toolbar rd-setup-actions"><button class="rd-button" @click="emit('navigate', 'import')">从作品导入</button><button class="rd-button purple" :disabled="!canEnter" @click="enterReading">进入示例故事</button></div>
    <p class="rd-demonstration">进入阅读只打开虚构示例，不生成内容、不读取真实作品。</p>
  </div></div>
</template>

<style>
#redesign-root .rd-journey-setup .rd-page-heading { align-items: end; }
#redesign-root .rd-journey-setup .rd-journey-modes { display: flex; gap: 8px; margin: 26px 0 18px; }
#redesign-root .rd-journey-setup .rd-journey-modes button { padding: 10px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); }
#redesign-root .rd-journey-setup .rd-journey-modes button[aria-pressed="true"] { color: var(--blue); border-color: var(--blue); }
#redesign-root .rd-journey-setup .rd-panel { padding: 22px; margin: 18px 0; border: 1px solid var(--line); border-radius: 14px; background: var(--surface); }
#redesign-root .rd-journey-setup .rd-setup-fields { display: grid; gap: 14px; }
#redesign-root .rd-journey-setup .rd-setup-actions { justify-content: end; }
@media (max-width: 760px) { #redesign-root .rd-journey-setup .rd-page-heading { align-items: stretch; } #redesign-root .rd-journey-setup .rd-setup-actions .rd-button { flex: 1; } }
</style>
