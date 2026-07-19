<template>
  <aside v-if="model.open" id="outline-float-panel" class="outline-float-panel">
    <div class="outline-float-header">
      <span>大纲</span>
      <button class="btn-icon" title="关闭大纲浮窗" @click="$emit('close')">×</button>
    </div>
    <div id="outline-float-body" class="outline-float-body">
      <p v-if="model.loading" class="muted">加载中...</p>
      <p v-else-if="model.error" class="muted" role="alert">{{ model.error }}</p>
      <p v-else-if="!model.threads.length" class="muted">暂无大纲条目</p>
      <div v-else class="outline-float-list">
        <article v-for="thread in model.threads" :key="thread.id" class="outline-float-item">
          <div class="outline-float-title">{{ thread.title || thread.name || '未命名剧情线' }}</div>
          <div class="outline-float-chapters">
            <button
              v-for="chapter in thread.chapter_ids || thread.chapters || []"
              :key="chapter"
              class="outline-float-chapter"
              :class="{ current: Number(chapter) === currentChapter }"
              @click="$emit('select', Number(chapter))"
            >{{ chapter }}</button>
            <span v-if="!(thread.chapter_ids || thread.chapters || []).length" class="muted">暂无章节映射</span>
          </div>
        </article>
      </div>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  model: { type: Object, required: true },
  currentChapter: { type: Number, default: null },
})
defineEmits(["close", "select"])
</script>
