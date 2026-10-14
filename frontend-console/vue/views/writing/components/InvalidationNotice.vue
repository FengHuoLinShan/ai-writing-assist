<template>
  <details v-if="notice.coverageOnly" class="writing-coverage-note" aria-label="本次保存的资料核对范围">
    <summary>查看资料核对范围</summary>
    <p v-if="notice.hasUnknownScope">{{ notice.unknownScopeNote }}</p>
    <p v-if="notice.coverageNote">{{ notice.coverageNote }}</p>
    <p>尚未确定有内容需要重算；你可以继续写作。</p>
    <button type="button" class="btn btn-sm" @click="$emit('open')">查看核对详情</button>
  </details>
  <section v-else class="writing-invalidation-notice" aria-label="本次保存的影响范围" role="status">
    <p class="writing-invalidation-notice__headline">{{ notice.headline }}</p>
    <p v-if="notice.hasUnknownScope" class="writing-invalidation-notice__unknown">
      {{ notice.unknownScopeNote }}
    </p>
    <p class="writing-invalidation-notice__hint">
      现在可以继续写作；需要时再从这里查看受影响的内容并选择重算。
    </p>
    <ul v-if="notice.mapEntries?.length" class="writing-invalidation-notice__maps">
      <li v-for="entry in notice.mapEntries" :key="entry.key">
        <span>{{ entry.scopeLabel }}</span>
        <button v-if="entry.mapNodeId" type="button" class="btn btn-sm" @click="getRouter()?.navigate('map', null, true, `node_id=${encodeURIComponent(entry.mapNodeId)}`)">去地图核对</button>
      </li>
    </ul>
    <p v-if="notice.mapCheckNote">{{ notice.mapCheckNote }}</p>
    <button type="button" class="btn btn-sm writing-invalidation-notice__open" @click="$emit('open')">
      查看受影响与重算选项
    </button>
  </section>
</template>

<script setup>
import { getRouter } from "../../../bridge/index.js"
defineProps({
  notice: { type: Object, required: true },
})
defineEmits(["open"])
</script>

<style scoped>
.writing-coverage-note { margin: 0 0 10px; color: var(--text-secondary); font-size: 12px; }
.writing-coverage-note summary { cursor: pointer; padding: 4px 0; }
.writing-coverage-note p { overflow-wrap: anywhere; }
.writing-invalidation-notice {
  margin: 0 0 10px;
  padding: 10px 12px;
  border: 1px solid rgba(176, 132, 32, 0.4);
  border-left: 3px solid rgba(176, 132, 32, 0.8);
  border-radius: 7px;
  background: rgba(176, 132, 32, 0.08);
  display: grid;
  gap: 4px;
  min-width: 0;
}
.writing-invalidation-notice__maps { margin: 0; padding-left: 18px; overflow-wrap: anywhere; }
.writing-invalidation-notice__maps li { margin-top: 4px; }
.writing-invalidation-notice__maps button { margin-left: 6px; white-space: normal; }
.writing-invalidation-notice__headline,
.writing-invalidation-notice__unknown,
.writing-invalidation-notice__hint {
  margin: 0;
  overflow-wrap: anywhere;
}
.writing-invalidation-notice__unknown { color: var(--text-secondary); }
.writing-invalidation-notice__hint { color: var(--text-secondary); font-size: 12px; }
.writing-invalidation-notice__open {
  justify-self: start;
  min-height: 34px;
  max-width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
  text-align: left;
}
</style>
