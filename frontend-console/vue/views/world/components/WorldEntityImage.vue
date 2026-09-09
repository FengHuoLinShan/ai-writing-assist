<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { getApi } from '../../../bridge/index.js'
const props = defineProps({ projectId: { type: String, required: true }, entity: { type: Object, required: true } })
const imageUrl = ref(''), status = ref(''), error = ref(''), uploading = ref(false), input = ref(null)
let generation = 0, controller = null
function reset() {
  generation += 1; controller?.abort(); controller = null
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''; error.value = ''; status.value = ''; uploading.value = false
}
async function loadImage(token = generation) {
  try {
    const blob = await getApi().world.fetchEntityImage(props.entity.id || props.entity.entity_id, props.projectId, 'full')
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
    await getApi().world.uploadEntityImage(props.entity.id || props.entity.entity_id, file, props.projectId, null, { signal: controller.signal })
    if (token !== generation) return
    const entity = props.entity; entity.has_image = true
    status.value = "图片已保存"
    await loadImage(token)
  } catch (err) { if (token === generation) error.value = err.message || '上传失败，原图片仍保留' }
  finally { if (token === generation) { uploading.value = false; event.target.value = '' } }
}
watch(() => [props.projectId, props.entity.id || props.entity.entity_id], () => {
  reset(); if (props.entity.has_image) void loadImage()
}, { immediate: true })
onBeforeUnmount(reset)
</script>
<template>
  <section class="entity-image" aria-label="对象图片" :aria-busy="uploading">
    <img v-if="imageUrl" :src="imageUrl" :alt="`${entity.name}的图片`" />
    <p v-else>尚未显示图片</p>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <input ref="input" type="file" accept="image/png,image/jpeg" hidden @change="upload" />
    <button class="btn" :disabled="uploading" @click="input.click()">{{ uploading ? '正在上传…' : imageUrl ? '替换图片' : '上传图片' }}</button>
    <button v-if="error && entity.has_image" class="btn" :disabled="uploading" @click="loadImage()">重新读取图片</button>
    <small>PNG／JPEG，小于 6 MiB，最长边不超过 4096 像素。</small>
  </section>
</template>
<style scoped>
.entity-image{display:grid;gap:8px;justify-items:start}.entity-image img{max-width:100%;max-height:320px;object-fit:contain;border-radius:var(--radius-md)}.entity-image button{min-height:44px}.entity-image small{color:var(--text-muted)}
</style>
