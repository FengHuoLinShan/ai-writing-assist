<template>
  <div v-if="model.open" class="modal-overlay" role="dialog" aria-modal="true" aria-label="版本历史">
    <div class="modal-content modal-content--wide writing-version-history-modal">
      <div class="modal-header">
        <h3>版本历史</h3>
        <button class="btn-icon" aria-label="关闭" @click="close">×</button>
      </div>
      <div class="modal-body">
        <div class="writing-version-history-list">
          <article v-for="version in versions" :key="version.id" class="writing-version-history-item">
            <div>
              <strong>v{{ version.version_number }}</strong>
              <span class="pill">{{ statusLabel(version) }}</span>
              <span v-if="version.updated_at" class="muted">{{ version.updated_at }}</span>
            </div>
            <div class="row-actions">
              <button class="btn btn-sm" @click="$emit('preview', version.id)">预览</button>
              <button v-if="isActive(version)" class="btn btn-sm" @click="$emit('restore', version)">基于此版本创建</button>
              <button v-if="isActive(version)" class="btn btn-sm btn-danger" @click="$emit('delete', version)">删除</button>
            </div>
          </article>
        </div>
        <div v-if="versions.length >= 2" class="writing-version-diff-controls">
          <select v-model="model.leftId" aria-label="左侧版本">
            <option v-for="version in versions" :key="`l-${version.id}`" :value="version.id">v{{ version.version_number }}</option>
          </select>
          <select v-model="model.rightId" aria-label="右侧版本">
            <option v-for="version in versions" :key="`r-${version.id}`" :value="version.id">v{{ version.version_number }}</option>
          </select>
          <button class="btn btn-primary" :disabled="model.loading" @click="$emit('compare')">{{ model.loading ? '比较中...' : '比较版本' }}</button>
        </div>
        <p v-if="model.error" role="alert" class="writing-empty-hint">{{ model.error }}</p>
        <div v-if="model.diffOpen && model.diff" class="writing-version-diff">
          <div class="writing-version-diff__stats">
            <span>左侧 {{ model.diff.stats.leftChars }} 字</span>
            <span>右侧 {{ model.diff.stats.rightChars }} 字</span>
            <span>修改 {{ model.diff.stats.changedParagraphs }} 段</span>
            <span>移动 {{ model.diff.stats.movedParagraphs }} 段</span>
          </div>
          <div v-if="model.diff.identical" class="writing-version-diff__identical">两个版本正文完全一致</div>
          <div v-if="model.diff.fallbackUsed" class="writing-version-diff__notice">章节较长，已使用安全降级对齐。</div>
          <div class="writing-version-diff__grid" role="table" aria-label="正文版本并排差异">
            <div class="writing-version-diff__header" role="columnheader">左侧版本</div>
            <div class="writing-version-diff__header" role="columnheader">右侧版本</div>
            <template v-for="(row, index) in model.diff.rows" :key="index">
              <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell">
                <template v-if="row.leftSegments?.length">
                  <component :is="segment.type === 'delete' ? 'mark' : 'span'" v-for="(segment, i) in row.leftSegments" :key="i" :class="{ 'writing-version-diff__removed': segment.type === 'delete' }">{{ segment.text }}</component>
                </template>
                <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
              </div>
              <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell">
                <template v-if="row.rightSegments?.length">
                  <component :is="segment.type === 'insert' ? 'mark' : 'span'" v-for="(segment, i) in row.rightSegments" :key="i" :class="{ 'writing-version-diff__added': segment.type === 'insert' }">{{ segment.text }}</component>
                </template>
                <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  model: { type: Object, required: true },
  versions: { type: Array, default: () => [] },
})
defineEmits(["preview", "restore", "delete", "compare"])
const close = () => { props.model.open = false; props.model.diffOpen = false }
const isActive = (version) => version.display_state ? version.display_state === "active" : !["candidate", "deprecated"].includes(version.status)
const statusLabel = (version) => version.status === "published" ? "已发布" : version.status === "candidate" ? "待处理" : version.status === "deprecated" ? "历史" : "工作稿"
</script>
