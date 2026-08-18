<template>
  <div class="mobile-quick-note">
    <div class="mobile-note-header">
      <span class="mobile-note-chapter">第 {{ state.chapter }} 章</span>
      <span class="mobile-note-status" role="status">{{ statusText }}</span>
      <span id="mobile-note-wc" class="mobile-note-wc">{{ state.content.length.toLocaleString() }} 字</span>
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
      <button class="btn btn-primary" :disabled="state.saving || !state.content.trim()" @click="$emit('publish')">设为正式正文</button>
      <button class="btn btn-ghost" :disabled="state.saving" @click="$emit('save')">保存工作稿</button>
      <button class="btn btn-ghost" @click="$emit('desktop')">完整编辑器</button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import SceneLensSummary from "./SceneLensSummary.vue"

const props = defineProps({
  state: { type: Object, required: true },
  scenes: { type: Array, default: () => [] },
  selectedSceneId: { type: String, default: null },
  scene: { type: Object, default: null },
  lens: { type: Object, default: () => ({ loading: false, data: null, error: null }) },
  attach: { type: Function, required: true },
  detach: { type: Function, required: true },
})
defineEmits(["save", "publish", "desktop", "select-scene", "load-lens"])
const statusText = computed(() => {
  if (props.state.saving) return "正在保存"
  if (props.state.saveError) return "保存失败，本地备份已保留"
  return props.state.dirty ? "尚未保存" : "已保存到工作稿"
})
const editorEl = ref(null)
onMounted(() => nextTick(() => props.attach({ title: null, editor: editorEl.value })))
onBeforeUnmount(() => props.detach())
</script>
