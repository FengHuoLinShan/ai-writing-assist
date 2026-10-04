<template>
  <div class="writing-version-diff">
    <div class="writing-version-diff__stats" aria-label="版本差异统计">
      <span>{{ leftLabel }} {{ stats.leftChars || 0 }} 字</span>
      <span>{{ rightLabel }} {{ stats.rightChars || 0 }} 字</span>
      <span>修改 {{ stats.changedParagraphs || 0 }} 段</span>
      <span>移动 {{ stats.movedParagraphs || 0 }} 段</span>
    </div>
    <div v-if="diff.identical" class="writing-version-diff__identical">两个版本正文完全一致</div>
    <div v-if="diff.fallbackUsed" class="writing-version-diff__notice">章节较长，已使用安全降级对齐。</div>
    <div class="writing-version-diff__grid" role="table" aria-label="文本并排差异">
      <div class="writing-version-diff__header" role="columnheader">{{ leftLabel }}</div>
      <div class="writing-version-diff__header" role="columnheader">{{ rightLabel }}</div>
      <template v-for="(row, index) in rows" :key="index">
        <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell" data-side="左">
          <template v-if="row.leftSegments?.length">
            <component
              :is="segment.type === 'delete' ? 'mark' : 'span'"
              v-for="(segment, i) in row.leftSegments"
              :key="i"
              :class="{ 'writing-version-diff__removed': segment.type === 'delete' }"
            >{{ segment.text }}</component>
          </template>
          <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
        </div>
        <div class="writing-version-diff__cell" :class="`writing-version-diff__cell--${row.type}`" role="cell" data-side="右">
          <template v-if="row.rightSegments?.length">
            <component
              :is="segment.type === 'insert' ? 'mark' : 'span'"
              v-for="(segment, i) in row.rightSegments"
              :key="i"
              :class="{ 'writing-version-diff__added': segment.type === 'insert' }"
            >{{ segment.text }}</component>
          </template>
          <span v-else class="writing-version-diff__placeholder">此侧无对应段落</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
/**
 * VersionTextDiff — 纯文本段落差异的安全渲染（{{ }} 按片段转义，不经任何 HTML 注入）。
 * 从写作模块 VersionHistoryDialog 的差异渲染抽出，供写作版本历史、实体历史对比等共用。
 * 输入是 shared/versionDiff.js buildVersionDiff 的结果。
 */
import { computed } from "vue"

const props = defineProps({
  diff: { type: Object, required: true },
  leftLabel: { type: String, default: "左侧版本" },
  rightLabel: { type: String, default: "右侧版本" },
})

const stats = computed(() => props.diff?.stats || {})
const rows = computed(() => (Array.isArray(props.diff?.rows) ? props.diff.rows : []))
</script>
