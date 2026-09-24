<script setup>
import { onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"

const props = defineProps({ projectId: { type: String, required: true }, visual: { type: Object, required: true }, sceneTitle: { type: String, default: "场景" } })
const url = ref("")
const status = ref("正在读取配图…")
const canRetry = ref(false)
let generation = 0

function clear() {
  generation += 1
  if (url.value) URL.revokeObjectURL(url.value)
  url.value = ""
}

async function load() {
  clear()
  const token = generation
  status.value = "正在读取配图…"
  canRetry.value = false
  try {
    const entity = await getApi().world.getEntity(props.visual.entity_id, props.projectId)
    if (token !== generation) return
    if (entity.image_version !== props.visual.image_version) {
      status.value = "对象配图已更新，请重新核对场景图片。"
      return
    }
    const blob = await getApi().world.fetchEntityImage(props.visual.entity_id, props.projectId, "full", { expectedVersion: props.visual.image_version })
    if (token !== generation) return
    url.value = URL.createObjectURL(blob)
    status.value = ""
  } catch {
    if (token === generation) {
      status.value = "场景配图暂时无法读取，请稍后重试。"
      canRetry.value = true
    }
  }
}
watch(() => [props.projectId, props.visual.entity_id, props.visual.image_version], load, { immediate: true })
onBeforeUnmount(clear)
</script>

<template>
  <section class="scene-visual" aria-label="场景配图" :aria-busy="Boolean(status && !url)">
    <img v-if="url" :src="url" :alt="`${sceneTitle}的场景配图`" />
    <p v-if="status" role="status">{{ status }}</p>
    <button v-if="canRetry" type="button" class="btn btn-sm" @click="load">重新读取配图</button>
    <p v-if="url" class="scene-visual__caption">{{ visual.caption || '根据正文制作的场景图' }} · 画面为艺术诠释</p>
  </section>
</template>

<style scoped>
.scene-visual { display: grid; gap: 0.5rem; margin: 0 0 1rem; }
.scene-visual img { display: block; width: 100%; max-height: 19rem; object-fit: contain; background: var(--nc-surface, #f5f1e9); border-radius: var(--radius-md, 0.5rem); }
.scene-visual__caption { margin: 0; color: var(--text-muted); font-size: 0.875rem; }
</style>
