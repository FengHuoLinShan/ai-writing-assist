<template>
  <aside v-if="model.open" id="outline-float-panel" class="outline-float-panel" aria-label="大纲浮窗">
    <div class="outline-float-header">
      <span>大纲</span>
      <button type="button" class="btn-icon" title="关闭大纲浮窗" aria-label="关闭大纲浮窗" @click="$emit('close')">×</button>
    </div>
    <div id="outline-float-body" class="outline-float-body">
      <p v-if="model.loading" class="muted" role="status">加载中...</p>
      <p v-else-if="model.error" class="muted" role="alert">{{ model.error }}</p>
      <p v-else-if="!model.threads.length" class="muted">暂无大纲条目</p>
      <div v-else class="outline-float-list">
        <article v-for="thread in model.threads" :key="thread.id" class="outline-float-item">
          <div class="outline-float-title">{{ thread.title || thread.name || '未命名剧情线' }}</div>
          <div class="outline-float-chapters">
            <button
              v-for="chapter in thread.chapter_ids || thread.chapters || []"
              :key="chapter"
              type="button"
              class="outline-float-chapter"
              :class="{ current: Number(chapter) === currentChapter }"
              :aria-label="`打开第 ${Number(chapter)} 章`"
              :aria-current="Number(chapter) === currentChapter ? 'true' : undefined"
              @click="$emit('select', Number(chapter))"
            >{{ chapter }}</button>
            <span v-if="!(thread.chapter_ids || thread.chapters || []).length" class="muted">暂无章节映射</span>
          </div>
        </article>
      </div>
      <section class="outline-arc-section" aria-labelledby="outline-arc-heading">
        <header class="outline-arc-heading">
          <div>
            <h2 id="outline-arc-heading">人物弧线：作者计划 / 实际对照</h2>
            <p v-if="currentScene" class="muted">
              截止 {{ currentScene.title || '当前 Scene' }}<span v-if="currentScene.scene_index != null"> · Scene {{ currentScene.scene_index + 1 }}</span>
            </p>
            <p v-else class="muted">先在写作工作区选择一个 Scene。</p>
          </div>
          <button
            v-if="currentScene && !model.arcLoading"
            type="button"
            class="btn-icon"
            aria-label="刷新人物弧线对照"
            title="刷新人物弧线对照"
            @click="$emit('refresh-arcs')"
          >↻</button>
        </header>
        <p v-if="model.arcLoading" class="muted" role="status">正在核对人物弧线与截止点证据…</p>
        <p v-else-if="model.arcError" class="muted" role="alert">{{ model.arcError }}</p>
        <p v-else-if="!currentScene" class="muted">人物弧线对照需要一个有效 Scene 截止点。</p>
        <p v-else-if="!model.characterArcs?.length" class="muted">
          {{ model.arcGaps?.[0] || '当前 Scene 没有可核验的人物。' }}
        </p>
        <p v-if="model.arcOmission" class="muted">{{ model.arcOmission }}</p>
        <article
          v-for="arc in model.characterArcs || []"
          :key="arc.character_id"
          class="outline-arc-card"
        >
          <header class="outline-arc-card__header">
            <h3>{{ arc.character_name }}</h3>
            <span v-if="arc.is_pov" class="outline-arc-badge">POV</span>
          </header>
          <p v-if="arc.comparisonError" class="muted" role="alert">{{ arc.comparisonError }}</p>
          <template v-else-if="arc.comparison">
            <p class="outline-arc-cutoff">
              截止第 {{ arc.comparison.cutoff.chapter_cutoff || '—' }} 章
              <span v-if="arc.comparison.coverage === 'complete'">· 资料覆盖完整</span>
              <span v-else-if="arc.comparison.coverage === 'partial'">· 资料部分覆盖</span>
              <span v-else>· 资料覆盖未知</span>
            </p>
            <p v-if="arc.comparison.plan_archived" class="outline-arc-status">作者计划已归档；没有把归档计划当作当前安排。</p>
            <template v-else>
              <div class="outline-arc-plan-label">
                <span>作者确认计划</span>
                <span v-if="arc.comparison.plan" class="muted">
                  v{{ arc.comparison.plan.version }} · {{ sourceLabel(arc.comparison.plan.source) }} · 仅供导演
                </span>
                <span v-else class="muted">尚未确认</span>
              </div>
              <textarea
                class="outline-arc-editor"
                :value="model.arcDrafts?.[arc.character_id] ?? arc.comparison.plan?.plan_text ?? ''"
                :disabled="model.arcSavingCharacter === arc.character_id || publicDemo"
                :aria-label="`${arc.character_name}的人物弧计划`"
                placeholder="写下作者希望人物逐步改变的方向。计划不会成为正文事实或角色已知内容。"
                rows="4"
                @input="$emit('update-arc-draft', arc.character_id, $event.target.value)"
              />
              <p v-if="model.arcPreviews?.[arc.character_id]" class="outline-arc-preview" role="status">
                已预览为 v{{ model.arcPreviews[arc.character_id].expected_version + 1 }}。请核对上方计划，再明确确认保存。
              </p>
              <p v-if="model.arcErrors?.[arc.character_id]" class="muted" role="alert">
                {{ model.arcErrors[arc.character_id] }}
              </p>
              <div class="outline-arc-actions">
                <button
                  v-if="model.arcPreviews?.[arc.character_id]"
                  type="button"
                  class="btn btn-sm btn-primary"
                  :disabled="model.arcSavingCharacter === arc.character_id || publicDemo"
                  @click="$emit('confirm-arc', arc.character_id)"
                >确认保存 v{{ model.arcPreviews[arc.character_id].expected_version + 1 }}</button>
                <button
                  v-else
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcSavingCharacter === arc.character_id || publicDemo || !(model.arcDrafts?.[arc.character_id] ?? arc.comparison.plan?.plan_text ?? '').trim()"
                  @click="$emit('preview-arc', arc.character_id)"
                >预览保存</button>
                <button
                  v-if="model.arcPreviews?.[arc.character_id]"
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('cancel-arc-preview', arc.character_id)"
                >取消预览</button>
                <button
                  v-if="model.arcRestorePreviews?.[arc.character_id]?.action === 'archive'"
                  type="button"
                  class="btn btn-sm btn-primary"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('confirm-archive', arc.character_id)"
                >确认归档计划</button>
                <button
                  v-else-if="arc.comparison.plan && !publicDemo"
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('preview-archive', arc.character_id)"
                >预览归档</button>
                <button
                  v-if="model.arcRestorePreviews?.[arc.character_id]"
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('cancel-arc-management-preview', arc.character_id)"
                >取消此操作预览</button>
                <button
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcHistoryLoading === arc.character_id"
                  @click="$emit('toggle-arc-history', arc.character_id)"
                >{{ model.arcHistoryOpen?.[arc.character_id] ? '收起版本记录' : '版本记录' }}</button>
              </div>
            </template>
            <div v-if="arc.comparison.plan_archived" class="outline-arc-actions">
              <button
                type="button"
                class="btn btn-sm"
                :disabled="model.arcHistoryLoading === arc.character_id"
                @click="$emit('toggle-arc-history', arc.character_id)"
              >{{ model.arcHistoryOpen?.[arc.character_id] ? '收起版本记录' : '版本记录与恢复' }}</button>
            </div>
            <div v-if="model.arcHistoryOpen?.[arc.character_id]" class="outline-arc-history">
              <p v-if="model.arcHistoryLoading === arc.character_id" class="muted" role="status">正在读取版本记录…</p>
              <p v-else-if="model.arcHistoryErrors?.[arc.character_id]" class="muted" role="alert">
                {{ model.arcHistoryErrors[arc.character_id] }}
              </p>
              <template v-else>
                <p v-if="model.arcHistory?.[arc.character_id]?.deleted" class="outline-arc-status">此计划已归档。</p>
                <p v-if="model.arcHistory?.[arc.character_id]?.deleted && !publicDemo">
                  <button
                    v-if="!model.arcRestorePreviews?.[arc.character_id]"
                    type="button"
                    class="btn btn-sm"
                    :disabled="model.arcSavingCharacter === arc.character_id"
                    @click="$emit('preview-unarchive', arc.character_id)"
                  >预览恢复计划</button>
                  <button
                    v-else-if="model.arcRestorePreviews?.[arc.character_id]?.action === 'unarchive'"
                    type="button"
                    class="btn btn-sm btn-primary"
                    :disabled="model.arcSavingCharacter === arc.character_id"
                    @click="$emit('confirm-unarchive', arc.character_id)"
                  >确认恢复计划</button>
                </p>
                <ol v-if="model.arcHistory?.[arc.character_id]?.items?.length" class="outline-arc-history__list">
                  <li v-for="version in model.arcHistory[arc.character_id].items" :key="version.revision_id">
                    <span>v{{ version.version }} · {{ sourceLabel(version.source) }}</span>
                    <button
                      v-if="!publicDemo && !model.arcHistory?.[arc.character_id]?.deleted && version.source !== 'author_archive' && version.version !== model.arcHistory?.[arc.character_id]?.current_version"
                      type="button"
                      class="btn btn-sm"
                      :disabled="model.arcSavingCharacter === arc.character_id"
                      @click="$emit('preview-restore-arc', arc.character_id, version.revision_id)"
                    >预览恢复</button>
                  </li>
                </ol>
                <p v-else class="muted">还没有历史版本。</p>
                <p v-if="model.arcRestorePreviews?.[arc.character_id]" class="outline-arc-preview" role="status">
                  {{ model.arcRestorePreviews[arc.character_id].effect || '已准备恢复预览。' }}
                </p>
                <button
                  v-if="model.arcRestorePreviews?.[arc.character_id]"
                  type="button"
                  class="btn btn-sm"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('cancel-arc-management-preview', arc.character_id)"
                >取消此操作预览</button>
                <button
                  v-if="model.arcRestorePreviews?.[arc.character_id]?.action === 'restore' && !model.arcHistory?.[arc.character_id]?.deleted"
                  type="button"
                  class="btn btn-sm btn-primary"
                  :disabled="model.arcSavingCharacter === arc.character_id"
                  @click="$emit('confirm-restore-arc', arc.character_id)"
                >确认恢复此版本</button>
              </template>
            </div>
            <section class="outline-arc-actual" :aria-label="`${arc.character_name}截止点已核验实际证据`">
              <h4>截止点正文证据</h4>
              <ul v-if="arc.comparison.actual_events?.length">
                <li v-for="(event, index) in arc.comparison.actual_events" :key="`${event.chapter_index}-${index}-${event.range_hash}`">
                  <span class="outline-arc-evidence-meta">{{ event.source_label }} · {{ event.field }}：{{ valueLabel(event.value) }}</span>
                  <blockquote>{{ event.quote }}</blockquote>
                </li>
              </ul>
              <p v-else class="muted">没有满足正文来源核验的经历记录。</p>
            </section>
            <details v-if="arc.comparison.unknowns?.length" class="outline-arc-unknowns">
              <summary>未知与缺口（{{ arc.comparison.unknowns.length }}）</summary>
              <ul><li v-for="gap in arc.comparison.unknowns" :key="gap">{{ gap }}</li></ul>
            </details>
          </template>
        </article>
      </section>
    </div>
  </aside>
</template>

<script setup>
defineProps({
  model: { type: Object, required: true },
  currentChapter: { type: Number, default: null },
  currentScene: { type: Object, default: null },
  publicDemo: { type: Boolean, default: false },
})
defineEmits([
  "close", "select", "refresh-arcs", "update-arc-draft", "preview-arc",
  "confirm-arc", "cancel-arc-preview", "toggle-arc-history", "preview-restore-arc",
  "confirm-restore-arc", "preview-unarchive", "confirm-unarchive",
  "preview-archive", "confirm-archive",
  "cancel-arc-management-preview",
])

function sourceLabel(source) {
  return {
    author_confirmed: "作者确认",
    author_restore: "由历史恢复",
    author_archive: "归档记录",
    author_unarchive: "由归档恢复",
  }[source] || "来源待核对"
}

function valueLabel(value) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value)
  if (Array.isArray(value)) return value.length ? `已记录 ${value.length} 项状态` : "空记录"
  if (value && typeof value === "object") {
    const label = value.label || value.summary || value.name
    return typeof label === "string" ? label : "已记录结构化状态"
  }
  return "状态已记录"
}

</script>
