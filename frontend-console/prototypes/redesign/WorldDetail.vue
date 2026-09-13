<script setup>
import { ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'

const props = defineProps({ entry: { type: Object, required: true } })
const emit = defineEmits(['close', 'navigate', 'update'])

const editing = ref(false)
const savedNote = ref(props.entry.note)
const savedRole = ref(props.entry.role)
const draftNote = ref(props.entry.note)
const draftRole = ref(props.entry.role)
const imageState = ref('无图片')
const imageFeedback = ref('')
const feedback = ref('')

watch(() => props.entry.id, () => {
  editing.value = false
  savedNote.value = props.entry.note
  savedRole.value = props.entry.role
  draftNote.value = props.entry.note
  draftRole.value = props.entry.role
  imageState.value = '无图片'
  imageFeedback.value = ''
  feedback.value = ''
})
watch(imageState, value => {
  if (value !== '可用') imageFeedback.value = ''
})

function beginEdit() {
  draftNote.value = savedNote.value
  draftRole.value = savedRole.value
  editing.value = true
  feedback.value = ''
}
function cancelEdit() {
  draftNote.value = savedNote.value
  draftRole.value = savedRole.value
  editing.value = false
  feedback.value = '已取消编辑，原资料保持不变 · 演示'
}
function saveEdit() {
  savedNote.value = draftNote.value.trim() || props.entry.note
  savedRole.value = draftRole.value.trim() || props.entry.role
  emit('update', { id: props.entry.id, note: savedNote.value, role: savedRole.value })
  editing.value = false
  feedback.value = '资料调整已保存在本次预览 · 演示'
}
function replaceImage() {
  imageState.value = '可用'
  imageFeedback.value = '已替换示例图片 · 未读取本地文件'
}
function confirmArchive() {
  const accepted = globalThis.confirm?.(`确定要归档「${props.entry.name}」吗？`) ?? false
  feedback.value = accepted ? '归档已确认 · 预览未改变真实作品' : '已取消归档，资料仍保留 · 演示'
}
</script>

<template>
  <aside class="rd-world-detail rd-detail-surface" aria-label="资料详情">
    <div class="rd-detail-heading">
      <div><span class="rd-eyebrow">{{ entry.type }} · 资料详情</span><h2>{{ entry.name }}</h2></div>
      <button class="rd-icon-button" type="button" aria-label="关闭资料详情" @click="emit('close')"><PreviewIcon name="close" /></button>
    </div>

    <div class="rd-world-detail-overview">
      <div class="rd-world-detail-copy">
        <span class="rd-badge" :class="`tone-${entry.color}`">{{ entry.type }}</span>
        <template v-if="editing">
          <label class="rd-field">资料角色<input v-model="draftRole" aria-label="资料角色" /></label>
          <label class="rd-field">资料说明<textarea v-model="draftNote" rows="5" aria-label="资料说明" /></label>
        </template>
        <template v-else>
          <p class="rd-world-detail-lead">{{ savedNote }}</p>
          <div class="rd-world-detail-grid"><div><span>资料角色</span><strong>{{ savedRole }}</strong></div><div><span>最近来源</span><strong>{{ entry.source }}</strong></div></div>
        </template>
      </div>
      <section class="rd-world-image" aria-label="资料图片">
        <div class="rd-world-image-preview" :class="`image-${imageState === '可用' ? 'ready' : imageState === '加载失败' ? 'failed' : 'empty'}`" role="img" :aria-label="`图片状态：${imageState}`">
          <span v-if="imageState === '加载中'" class="rd-spinner" />
          <PreviewIcon v-else name="project" />
          <small>{{ imageState }}</small>
        </div>
        <label class="rd-field">图片状态演示<select v-model="imageState" aria-label="图片状态演示"><option>无图片</option><option>加载中</option><option>加载失败</option><option>可用</option></select></label>
        <button v-if="imageState === '无图片'" class="rd-text-button" type="button" @click="replaceImage">添加示例图片 <PreviewIcon name="forward" /></button>
        <button v-else-if="imageState === '加载失败'" class="rd-text-button" type="button" @click="replaceImage">重新加载示例图片 <PreviewIcon name="forward" /></button>
        <button v-else-if="imageState === '可用'" class="rd-text-button" type="button" @click="replaceImage">替换示例图片 <PreviewIcon name="forward" /></button>
        <p v-if="imageFeedback" class="rd-demonstration" role="status">{{ imageFeedback }}</p>
      </section>
    </div>

    <div v-if="imageState === '加载失败'" class="rd-inline-notice tone-orange" role="alert"><strong>! 图片暂时无法显示</strong><p>资料文字仍然可用。可以重新加载，或先保留无图状态。</p></div>
    <div v-else-if="imageState === '加载中'" class="rd-inline-notice tone-blue" role="status"><strong>正在载入示例图片</strong><p>这是状态展示，不会请求图片服务。</p></div>

    <div class="rd-local-toolbar">
      <template v-if="editing">
        <button class="rd-button primary" type="button" @click="saveEdit">保存本地示例</button>
        <button class="rd-button" type="button" @click="cancelEdit">取消编辑</button>
      </template>
      <template v-else>
        <button class="rd-button primary" type="button" @click="beginEdit">编辑资料</button>
        <button class="rd-button" type="button" @click="emit('navigate', 'writing', '本章资料')">回到本章写作</button>
      </template>
    </div>
    <p v-if="feedback" class="rd-inline-notice tone-green" role="status">{{ feedback }}</p>

    <section class="rd-world-history">
      <div class="rd-section-title"><h3>来源与历史</h3><span class="rd-badge tone-blue">可追溯 · 示例</span></div>
      <div class="rd-world-history-source"><div><span>当前来源</span><strong>{{ entry.source }}</strong><small>从正文与世界资料整理而来</small></div><button class="rd-text-button" type="button" @click="emit('navigate', 'search', '正文')">回看原文 <PreviewIcon name="forward" /></button></div>
      <ul class="rd-world-history-list"><li><span>今天</span><div><strong>资料说明已整理</strong><small>保留当前对象与原始来源关系</small></div></li><li><span>昨天</span><div><strong>首次加入世界资料</strong><small>由《潮汐来信》示例内容建立</small></div></li></ul>
    </section>

    <details class="rd-world-danger">
      <summary class="rd-text-button">资料管理 <PreviewIcon name="down" /></summary>
      <p>归档会让资料暂时离开主列表。这里仅展示确认路径，不会改变示例数据。</p>
      <button class="rd-button danger" type="button" @click="confirmArchive">归档资料</button>
    </details>
    <p class="rd-demonstration">本地详情示例。编辑、图片、历史和确认状态不会写入作品或读取文件。</p>
  </aside>
</template>
