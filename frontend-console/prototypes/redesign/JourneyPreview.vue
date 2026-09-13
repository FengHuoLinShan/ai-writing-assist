<script setup>
import { ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'

const props = defineProps({ state: { type: String, default: 'normal' }, initialSection: { type: String, default: 'list' } })
const emit = defineEmits(['navigate', 'open'])
const loadFailed = ref(props.state === 'error')
const journeys = [
  { title: '潮汐之间', subtitle: '灯塔亮起的那一刻，你决定留下来。', progress: '第 3 次选择 · 白沙港' },
  { title: '雾林来客', subtitle: '这里的树，记得每一个经过的人。', progress: '尚未开始' },
  { title: '第七封来信', subtitle: '明天的你，寄来了一封今天的信。', progress: '尚未开始' },
]
function retry() { loadFailed.value = false }
function openSetup() { emit('navigate', 'journeys', 'setup') }
</script>

<template>
  <div class="rd-page-scroll"><div class="rd-page-inner rd-journey-preview">
    <header class="rd-page-heading"><div><span class="rd-eyebrow">读者空间 · 演示</span><h1>互动故事</h1><p>继续一段旅程，或发现一个新世界。</p></div><button class="rd-button purple" @click="openSetup"><span class="rd-button-content"><PreviewIcon name="sparkles"/>开启新旅程</span></button></header>
    <div v-if="loadFailed" class="rd-inline-notice tone-orange" role="alert"><strong>! 旅程列表暂时无法打开 · 演示</strong><p>已有旅程不会丢失，可以重试或先开启一段新旅程。</p><button class="rd-button" @click="retry">重新加载</button></div>
    <section v-else-if="state === 'empty'" class="rd-empty"><span class="rd-empty-symbol">✦</span><h2>还没有开始的旅程</h2><p>选择一个世界，从第一步开始。</p><button class="rd-button purple" @click="openSetup">开启第一段旅程</button></section>
    <template v-else>
      <button class="rd-journey-hero" @click="emit('navigate', 'reading')"><span class="rd-eyebrow">继续你的旅程</span><h2>潮汐之间</h2><p>灯塔亮起的那一刻，<br>你决定留下来。</p><span class="rd-button light">回到白沙港 →</span><span class="rd-lighthouse"><i/></span><span class="rd-moon"/><span class="rd-horizon"/></button>
      <div class="rd-section-title"><h2>发现故事</h2><span class="rd-muted">为想象留一道门</span></div>
      <div class="rd-two-columns"><button v-for="journey in journeys.slice(1)" :key="journey.title" class="rd-discovery tone-purple" @click="openSetup"><span>发现故事 · 演示</span><h2>{{ journey.title }}</h2><p>{{ journey.subtitle }}</p><strong>探索这个世界 <PreviewIcon name="forward"/></strong></button></div>
      <p class="rd-demonstration">示例旅程与发现内容均为虚构，不调用模型，也不读取真实作品。</p>
    </template>
  </div></div>
</template>

<style>
#redesign-root .rd-journey-preview .rd-demonstration { margin-top: 24px; }
#redesign-root .rd-journey-preview .rd-page-heading { align-items: end; }
@media (max-width: 760px) { #redesign-root .rd-journey-preview .rd-page-heading { align-items: stretch; } }
</style>
