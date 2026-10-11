<template>
  <details class="scene-checkpoint-history">
    <summary>历史版本</summary>
    <p>本场状态每次整理都会留下一份记录；旧版本保留改稿前的依据，不会覆盖。</p>
    <div class="scene-checkpoint-history__load">
      <button type="button" class="btn btn-sm" :disabled="loading" @click="load">
        {{ loading ? '正在读取…' : groups.length ? '刷新历史版本' : '查看历史版本' }}
      </button>
      <p v-if="error" role="alert">{{ error }}</p>
    </div>
    <template v-if="groups.length">
      <ul class="scene-checkpoint-history__list">
        <li v-for="group in groups" :key="group.key" :class="{ 'is-current': group.isCurrent }">
          <strong>
            {{ group.isCurrent ? '当前版本' : '历史版本' }}
            <small>{{ group.chapterIndex ? `第 ${group.chapterIndex} 章` : '未锚定章节' }}{{ group.version ? ` · 第 ${group.version} 次整理` : '' }}</small>
          </strong>
          <p v-if="group.dimensionLabels.length" class="scene-checkpoint-history__dims">{{ group.dimensionLabels.join('、') }}</p>
          <p v-if="group.createdAt" class="scene-checkpoint-history__time">记录于 {{ formatTime(group.createdAt) }}</p>
          <p v-if="!group.hasFieldProvenance" class="writing-empty-hint">这个版本早于逐字段来源功能上线，没有每个字段的依据记录；可回看当时的整体依据。</p>
          <div class="scene-checkpoint-history__actions">
            <button
              v-for="checkpoint in group.checkpoints"
              :key="checkpoint.checkpointId"
              type="button"
              class="btn btn-sm"
              @click="$emit('source', { checkpoint_id: checkpoint.checkpointId })"
            >回看该版本依据</button>
          </div>
        </li>
      </ul>
    </template>
    <p v-else-if="loaded" class="writing-empty-hint">本场还没有历史版本记录；状态整理后会产生可回看的版本。</p>
  </details>
</template>

<script setup>
import { ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"
import { sceneCheckpointHistoryGroups } from "../sceneLensModel.js"

const props = defineProps({
  projectId: { type: String, default: null },
  sceneId: { type: String, default: null },
})
defineEmits(["source"])
const loading = ref(false), loaded = ref(false), error = ref(""), groups = ref([])
let generation = 0
watch(() => [props.projectId, props.sceneId], () => {
  generation += 1
  loading.value = false
  loaded.value = false
  error.value = ""
  groups.value = []
})
async function load() {
  const token = ++generation
  loading.value = true
  error.value = ""
  try {
    const result = await getApi().story.sceneCheckpointHistory(props.projectId, props.sceneId)
    if (token !== generation) return
    groups.value = sceneCheckpointHistoryGroups(result?.items)
    loaded.value = true
  } catch (cause) {
    if (token === generation) error.value = cause?.message || "历史版本暂时读不到，请稍后重试。"
  } finally {
    if (token === generation) loading.value = false
  }
}
function formatTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString()
}
</script>

<style scoped>
.scene-checkpoint-history { margin-top: 10px; }
.scene-checkpoint-history__load { margin: 6px 0; }
.scene-checkpoint-history__list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.scene-checkpoint-history__list li { padding: 6px 8px; border: 1px solid var(--border-color, rgba(128, 128, 128, 0.3)); border-radius: 6px; }
.scene-checkpoint-history__list li.is-current { border-color: rgba(46, 125, 80, 0.5); }
.scene-checkpoint-history__list small { font-weight: 400; margin-left: 6px; opacity: 0.8; }
.scene-checkpoint-history__dims, .scene-checkpoint-history__time { margin: 2px 0 0; font-size: 12px; opacity: 0.85; }
.scene-checkpoint-history__actions { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 6px; }
</style>
