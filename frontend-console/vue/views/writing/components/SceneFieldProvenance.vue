<template>
  <div class="scene-field-provenance" :aria-label="`${fieldLabel}来源`">
    <p class="scene-field-provenance__head">
      <em class="scene-field-provenance__badge" :class="`is-${provenance.status}`">{{ provenance.statusLabel }}</em>
      <span v-if="provenance.status === 'exact'">这条状态可以在原稿里找到对应段落。</span>
      <span v-else-if="provenance.status === 'unverified'">来源待核实：这条状态暂时没有追到具体稿件段落，不会当作已核对的事实。</span>
      <span v-else>多条记录相互冲突，尚未人工核实；请以正文为准。</span>
    </p>
    <p v-if="provenance.eventId" class="scene-field-provenance__event">记录自一次状态变化（诊断编号 {{ provenance.eventId }}）。</p>
    <ul v-if="provenance.refs.length" class="scene-field-provenance__refs">
      <li v-for="ref in provenance.refs" :key="`${ref.draftId}:${ref.startOffset}:${ref.endOffset}`">
        <span>第 {{ ref.chapterIndex }} 章 · 第 {{ ref.version }} 版工作稿 · 第 {{ ref.startOffset }}–{{ ref.endOffset }} 字</span>
        <button v-if="ref.reopenable && projectId" type="button" class="btn btn-sm" :disabled="reading" @click="reopen(ref)">
          {{ reading ? '正在回读…' : '回看原文' }}
        </button>
        <p v-if="error" role="alert">{{ error }}</p>
        <blockquote v-if="preview">{{ preview }}</blockquote>
      </li>
    </ul>
    <p v-else-if="provenance.status === 'exact'" class="writing-empty-hint">对应的稿件段落暂时无法定位。</p>
  </div>
</template>

<script setup>
import { ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, default: null },
  fieldLabel: { type: String, default: "字段" },
  provenance: { type: Object, required: true },
})
const reading = ref(false), preview = ref(""), error = ref("")
let generation = 0
watch(() => [props.projectId, props.provenance], () => {
  generation += 1
  reading.value = false
  preview.value = ""
  error.value = ""
})
async function reopen(ref) {
  const token = ++generation
  reading.value = true
  preview.value = ""
  error.value = ""
  try {
    const result = await getApi().context.readEvidence({
      novel_id: props.projectId,
      content_mode: ref.contentMode,
      visibility: { mode: "author" },
      source_ref: {
        draft_id: ref.draftId,
        chapter_index: ref.chapterIndex,
        version_number: ref.version,
        content_mode: ref.contentMode,
        start_offset: ref.startOffset,
        end_offset: ref.endOffset,
        source_hash: ref.sourceHash,
        range_hash: ref.rangeHash,
      },
      before: 1,
      after: 1,
    })
    if (token !== generation) return
    preview.value = result?.text || "（这一段没有读到文字）"
  } catch {
    if (token === generation) error.value = "原文暂时回读不到；可能稿件已改动，请以当前稿为准。"
  } finally {
    if (token === generation) reading.value = false
  }
}
</script>

<style scoped>
.scene-field-provenance { margin: 4px 0 0; padding: 6px 8px; border-left: 2px solid var(--border-color, rgba(128, 128, 128, 0.4)); display: grid; gap: 4px; }
.scene-field-provenance__head { margin: 0; }
.scene-field-provenance__badge { font-style: normal; margin-right: 6px; padding: 0 6px; border-radius: 8px; font-size: 12px; }
.scene-field-provenance__badge.is-exact { background: rgba(46, 125, 80, 0.16); }
.scene-field-provenance__badge.is-unverified { background: rgba(176, 132, 32, 0.16); }
.scene-field-provenance__badge.is-conflict { background: rgba(176, 64, 32, 0.16); }
.scene-field-provenance__event { margin: 0; font-size: 12px; opacity: 0.75; }
.scene-field-provenance__refs { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.scene-field-provenance__refs li { display: grid; gap: 2px; }
.scene-field-provenance__refs blockquote { margin: 2px 0 0; padding: 4px 8px; background: rgba(128, 128, 128, 0.12); border-radius: 4px; }
</style>
