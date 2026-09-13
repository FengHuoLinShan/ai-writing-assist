<script setup>
import { notices } from './data.js'
import PreviewIcon from './PreviewIcon.vue'
defineProps({ state: { type: String, default: 'normal' } })
defineEmits(['action'])
</script>
<template>
  <div :key="state" v-if="notices[state]" class="rd-notice" :class="`tone-${notices[state].color}`" role="status">
    <span class="rd-notice-icon"><PreviewIcon v-if="state === 'success'" name="check"/><template v-else>{{ notices[state].icon }}</template></span>
    <div><strong>{{ notices[state].title }} <small>演示</small></strong><p>{{ notices[state].body }}</p></div>
    <button class="rd-button subtle" @click="$emit('action')"><span class="rd-button-content">{{ notices[state].action }} <PreviewIcon name="forward"/></span></button>
  </div>
  <div v-else-if="state === 'loading'" class="rd-loading" role="status"><span class="rd-spinner" />正在载入示例内容…<small>加载状态展示</small></div>
  <section v-else-if="state === 'empty'" class="rd-empty"><span class="rd-empty-symbol">＋</span><h2>留一点空间，给新的故事</h2><p>从一个人物、一段文字，或一个还没想明白的念头开始。</p><button class="rd-button primary" @click="$emit('action')"><span class="rd-button-content">查看新建面板</span></button><small>空态演示</small></section>
</template>
