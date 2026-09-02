<template>
  <div class="mobile-quick-note">
    <div class="mobile-note-header">
      <span class="mobile-note-chapter">第 {{ chapterNumber }} 章</span>
      <span class="mobile-note-status" role="status">{{ statusText }}</span>
      <span class="mobile-note-counts">
        <span id="mobile-note-wc" class="mobile-note-wc">本章 {{ state.content.length.toLocaleString() }} 字</span>
        <span id="mobile-note-today-wc" class="mobile-note-wc">今日累计 {{ todayWords.toLocaleString() }} 字</span>
      </span>
    </div>
    <div v-if="state.loading" class="writing-editor-state loading-skeleton" role="status" aria-live="polite" aria-busy="true">
      <p>正在打开第 {{ chapterNumber }} 章…</p>
      <div class="skeleton loading-skeleton__heading" aria-hidden="true" />
      <div class="skeleton loading-skeleton__line loading-skeleton__line--medium" aria-hidden="true" />
    </div>
    <div v-else-if="state.loadError" class="writing-editor-state error-card" role="alert">
      <div>
        <strong>这一章暂时无法打开</strong>
        <p>{{ state.loadError }}。已保留上一章内容，没有写入本章。</p>
      </div>
      <button class="btn btn-sm" type="button" @click="$emit('retry-load')">重新加载</button>
    </div>
    <template v-else>
    <div v-if="state.saveError || (state.dirty && state.backupComplete === false)" class="writing-save-recovery error-card" role="alert">
      <div>
        <strong>工作稿还没有保存</strong>
        <p v-if="state.saveError">{{ state.backupComplete
            ? "本地备份已保留，可以直接重试。"
            : "本地备份不可用，离开或刷新会丢失未保存修改。" }}</p>
        <p v-else>本地备份不可用，当前修改只保留在这个页面；离开或刷新会丢失。请尽快保存工作稿。</p>
      </div>
      <button class="btn btn-sm" type="button" :disabled="state.saving" @click="$emit('save')">{{ state.saving ? '重试中…' : '重试保存' }}</button>
    </div>
    <label class="mobile-note-scene" for="mobile-note-scene-selector">
      <span>本章 Scene</span>
      <select
        v-if="scenes.length"
        id="mobile-note-scene-selector"
        :value="selectedSceneId || ''"
        aria-label="切换本章 Scene"
        @change="$emit('select-scene', $event.target.value)"
      >
        <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || '未命名 Scene' }}</option>
      </select>
      <span v-else class="writing-empty-hint">本章未关联 Scene</span>
    </label>
    <SceneLensSummary :scene="scene" :lens="lens" mobile @load="$emit('load-lens')" />
    <textarea
      ref="editorEl"
      id="mobile-note-editor"
      class="mobile-note-editor"
      aria-label="移动端速记正文"
      :value="state.content"
      placeholder="在此记录灵感..."
    />
    <div class="mobile-note-actions">
      <button type="button" class="btn btn-primary" :disabled="state.saving || Boolean(state.saveError) || !state.content.trim()" @click="$emit('publish')">设为正式正文</button>
      <button v-if="!state.saveError" type="button" class="btn btn-ghost" :disabled="state.saving" @click="$emit('save')">保存工作稿</button>
      <button type="button" class="btn btn-ghost" aria-label="打开完整编辑器，可编辑标题、版本与检查" @click="$emit('desktop')">更多编辑</button>
    </div>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import SceneLensSummary from "./SceneLensSummary.vue"

const props = defineProps({
  state: { type: Object, required: true },
  chapter: { type: Number, default: null },
  scenes: { type: Array, default: () => [] },
  selectedSceneId: { type: String, default: null },
  scene: { type: Object, default: null },
  lens: { type: Object, default: () => ({ loading: false, data: null, error: null }) },
  todayWords: { type: Number, default: 0 },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits(["save", "publish", "desktop", "select-scene", "load-lens", "retry-load"])
const chapterNumber = computed(() => Number(props.chapter || props.state.chapter) || null)
const statusText = computed(() => {
  if (props.state.saving) return "正在保存"
  if (props.state.saveError) {
    return props.state.backupComplete
      ? "保存失败，本地备份已保留"
      : "保存失败，本地备份不可用"
  }
  if (props.state.dirty && props.state.backupComplete === false) return "本地备份不可用"
  return props.state.dirty ? "尚未保存" : "已保存到工作稿"
})
const editorEl = ref(null)
const attachEditor = () => nextTick(() => {
  if (editorEl.value) props.attach({ title: null, editor: editorEl.value })
  else props.detach()
})
onMounted(attachEditor)
watch(() => [props.state.loading, props.state.loadError, props.state.chapter], attachEditor)
onBeforeUnmount(() => props.detach())
</script>
