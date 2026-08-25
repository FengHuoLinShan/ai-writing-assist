<!--
  OutlineStoryTab — outline/story-outline 子标签根组件。
  DOM class/id/data-action 保持 E2E 视觉/行为契约；事件由 Vue 绑定。
  短任务（生成表单、历史查看）仍走 showModalHtml；手工长表单进入可恢复的路由页面。
-->
<template>
  <div class="story-outline-workspace">
    <!-- ========== 无项目 ========== -->
    <div v-if="!projectId" class="empty-state"><p>请先选择项目。</p></div>

    <!-- ========== 加载错误 ========== -->
    <div v-else-if="loadError" class="empty-state" role="alert">
      <div class="empty-icon">!</div>
      <p>故事总览加载失败</p>
      <p class="outline-empty-detail">{{ loadError }}</p>
      <button type="button" class="btn btn-sm" data-action="reload-story-outline" :disabled="reloading" @click="handleReload">{{ reloading ? '重新加载中…' : '重新加载' }}</button>
    </div>

    <!-- ========== 主内容区 ========== -->
    <template v-else>
    <section v-if="taskProgress && (!preview || !taskProgress.terminal)" class="outline-task-status" aria-labelledby="story-outline-active-task-title">
      <h3 id="story-outline-active-task-title" class="outline-task-status__title">AI 任务</h3>
      <WorkflowProgressCard
        :progress="taskProgress"
        variant="card"
        title="AI 故事总览"
        :message="taskProgress.message || ''"
        :attention-required="Boolean(taskProgress?.failed || taskProgress?.stateUnknown)"
        :show-task-id="false"
      >
        <div v-if="canCancelTask || showDismissTask" class="workflow-progress__actions">
          <button v-if="canCancelTask" class="btn btn-sm btn-ghost" data-action="cancel-story-outline-task" :disabled="cancelPending" @click="cancelTask">{{ cancelPending ? '取消中...' : '取消生成' }}</button>
          <button v-if="showDismissTask" class="btn btn-sm btn-ghost" data-action="dismiss-story-outline-task" @click="dismissTask">关闭任务</button>
        </div>
      </WorkflowProgressCard>
    </section>

    <section
      class="story-outline-primary"
      :class="hasCurrentRevision ? 'story-outline-intro' : 'story-outline-onboarding'"
      aria-labelledby="story-outline-intro-title"
    >
      <div class="story-outline-primary__layout">
        <div class="story-outline-primary__copy">
          <span v-if="!hasCurrentRevision" class="story-outline-primary__eyebrow">从这里开始</span>
          <h2 id="story-outline-intro-title">{{ hasCurrentRevision ? '调整整体方向' : '先确定故事方向' }}</h2>
          <p>{{ hasCurrentRevision
            ? '编辑或采用 AI 建议都会创建新版本，当前内容保留在历史中，不会自动改写篇章或场景。'
            : '用核心前提、读者期待和主要推进先锁定全书方向；这里只整理总览，不会自动创建篇章或场景。' }}</p>
        </div>
        <div class="story-outline-primary__actions" aria-label="故事总览操作">
          <template v-if="hasCurrentRevision">
            <button type="button" class="btn btn-sm btn-primary" data-action="edit-story-outline" @click="openManualEditor">编辑为新版本</button>
            <button type="button" class="btn btn-sm" data-action="generate-story-outline" :disabled="hasRunningTask" @click="showGenerateForm">AI 生成新方案</button>
          </template>
          <template v-else>
            <button type="button" class="btn btn-sm btn-primary" data-action="generate-story-outline" :disabled="hasRunningTask" @click="showGenerateForm">AI 生成可编辑预览</button>
            <button type="button" class="btn btn-sm" data-action="edit-story-outline" @click="openManualEditor">手工创建</button>
          </template>
          <details class="scene-workbench-tools story-outline-more">
            <summary class="btn btn-sm btn-ghost">更多</summary>
            <div class="scene-workbench-tools__menu">
              <button type="button" class="btn btn-sm" data-action="reload-story-outline" :disabled="reloading" @click="handleReloadFromMenu">{{ reloading ? '重新加载中…' : '重新加载内容' }}</button>
            </div>
          </details>
        </div>
      </div>
      <p v-if="!hasCurrentRevision" class="story-outline-primary__note">AI 只生成可编辑预览，由你确认采用后才会成为新版本。</p>
      <p v-if="assetLoadError" class="form-error" role="status">{{ assetLoadError }}</p>
      <p v-if="taskNotice" class="form-error" role="alert">{{ taskNotice }}</p>
    </section>

    <!-- ========== 预览编辑器 ========== -->
    <section v-if="preview" class="story-outline-preview" aria-labelledby="story-outline-preview-title" :aria-busy="applying ? 'true' : undefined">
      <header class="story-outline-preview__header">
        <div>
          <span class="story-outline-primary__eyebrow">尚未采用</span>
          <h3 id="story-outline-preview-title">检查 AI 建议</h3>
          <p>先按你的想法修改。这里的内容只保存在本机，点击“采用为新版本”后才会写入故事总览。</p>
        </div>
        <p class="story-outline-preview__save-state" role="status" aria-live="polite">{{ previewSaveState }}</p>
      </header>
      <aside v-if="previewRestored" class="story-outline-editor-notice" role="status">
        <div><strong>已恢复上次修改</strong><p>你对这份 AI 建议的修改已从本机带回，可以继续核对。</p></div>
      </aside>
      <aside v-if="previewConflict" class="story-outline-editor-notice story-outline-editor-notice--warning" role="alert">
        <div><strong>采用前，当前版本被更新了</strong><p>本机修改没有丢失。先同步最新版本基准，再核对并采用。</p></div>
        <button type="button" class="btn btn-sm" data-action="sync-story-outline-preview" :disabled="rebasingPreview" @click="rebasePreview">{{ rebasingPreview ? '同步中…' : '同步最新版本' }}</button>
      </aside>
      <p v-if="previewStorageError" class="form-error" role="alert">{{ previewStorageError }}</p>
      <form @submit.prevent="applyPreview">
        <StoryOutlineEditorFields :model-value="preview.content" prefix="story-outline-preview" />
        <p v-if="applyError" id="story-outline-apply-error" class="form-error" role="alert" tabindex="-1">{{ applyError }}</p>
        <footer class="story-outline-preview__actions">
          <span class="form-hint">修改会自动暂存在本机；尚未采用的内容不会改变当前版本。</span>
          <div>
            <button type="button" class="btn btn-sm btn-ghost" data-action="discard-story-outline-preview" :disabled="applying" @click="discardPreview">放弃此建议</button>
            <button type="submit" class="btn btn-sm btn-primary" data-action="apply-story-outline-preview" :disabled="applying || previewConflict">{{ applying ? '采用中…' : '采用为新版本' }}</button>
          </div>
        </footer>
      </form>
    </section>

    <!-- ========== 当前版本 ========== -->
    <article v-if="currentRevision" class="card story-outline-document" aria-labelledby="story-outline-current-title">
      <header class="story-outline-document__header">
        <span class="story-outline-document__version">当前版本 · v{{ currentRevision.version_number }}</span>
        <h3 id="story-outline-current-title">{{ currentRevision.title }}</h3>
        <p class="form-hint">{{ sourceLabel(currentRevision.source) }} · {{ formatDate(currentRevision.created_at) }}</p>
      </header>

      <section class="story-outline-document__section" aria-labelledby="story-outline-core-title">
        <h4 id="story-outline-core-title">故事核心</h4>
        <dl class="story-outline-core">
          <div><dt>核心前提</dt><dd>{{ currentRevision.creative_core?.premise }}</dd></div>
          <div><dt>基调与读者承诺</dt><dd>{{ currentRevision.creative_core?.tone_and_reader_promise }}</dd></div>
          <div><dt>故事引擎</dt><dd>{{ currentRevision.creative_core?.story_engine }}</dd></div>
          <div><dt>结局方向</dt><dd>{{ currentRevision.creative_core?.ending_direction || '待决定' }}</dd></div>
        </dl>
      </section>

      <section class="story-outline-document__section" aria-labelledby="story-outline-body-title">
        <h4 id="story-outline-body-title">总览正文</h4>
        <p class="story-outline-document__prose">{{ readableOutline(currentRevision.outline_markdown) }}</p>
      </section>

      <section class="story-outline-document__section" aria-labelledby="story-outline-storylines-read-title">
        <h4 id="story-outline-storylines-read-title">主要剧情线</h4>
        <ol v-if="currentRevision.major_storylines?.length" class="story-outline-entry-list">
          <li v-for="(item, idx) in currentRevision.major_storylines" :key="idx" class="story-outline-entry">
            <div class="story-outline-entry__title"><span aria-hidden="true">{{ idx + 1 }}</span><h5>{{ item.name }}</h5></div>
            <dl class="story-outline-entry__details">
              <div><dt>作用</dt><dd>{{ item.narrative_function }}</dd></div>
              <div><dt>发展轨迹</dt><dd>{{ item.trajectory }}</dd></div>
              <div><dt>交汇点</dt><dd>{{ (item.intersections || []).join('、') || '暂无' }}</dd></div>
              <div><dt>收束方向</dt><dd>{{ item.resolution_direction }}</dd></div>
            </dl>
          </li>
        </ol>
        <p v-else class="form-hint">还没有主要剧情线。</p>
      </section>

      <section class="story-outline-document__section" aria-labelledby="story-outline-movements-read-title">
        <h4 id="story-outline-movements-read-title">故事推进</h4>
        <ol v-if="currentRevision.macro_movements?.length" class="story-outline-entry-list">
          <li v-for="(item, idx) in currentRevision.macro_movements" :key="idx" class="story-outline-entry">
            <div class="story-outline-entry__title"><span aria-hidden="true">{{ idx + 1 }}</span><h5>{{ item.name }}</h5></div>
            <p class="story-outline-entry__lead">{{ item.story_state_change }}</p>
            <p class="story-outline-entry__meta"><strong>推进剧情线</strong>{{ (item.advanced_storylines || []).join('、') || '暂无' }}</p>
          </li>
        </ol>
        <p v-else class="form-hint">还没有故事推进。</p>
      </section>

      <section class="story-outline-document__section" aria-labelledby="story-outline-decisions-read-title">
        <h4 id="story-outline-decisions-read-title">待决定问题</h4>
        <ol v-if="currentRevision.open_decisions?.length" class="story-outline-entry-list">
          <li v-for="(item, idx) in currentRevision.open_decisions" :key="idx" class="story-outline-entry">
            <div class="story-outline-entry__title"><span aria-hidden="true">{{ idx + 1 }}</span><h5>{{ item.question }}</h5></div>
            <p class="story-outline-entry__lead">{{ item.why_it_matters }}</p>
            <p class="story-outline-entry__meta"><strong>可选方向</strong>{{ (item.options || []).join('、') || '暂无' }}</p>
          </li>
        </ol>
        <p v-else class="form-hint">目前没有待决定问题。</p>
      </section>
    </article>

    <!-- ========== 修订历史 ========== -->
    <details v-if="pastRevisionTotal || pastRevisions.length" class="card story-outline-history" aria-labelledby="story-outline-history-title">
      <summary aria-describedby="story-outline-history-hint">
        <span id="story-outline-history-title" class="story-outline-history__title">过往版本</span>
        <span class="story-outline-history__count">{{ pastRevisionTotal }} 份</span>
      </summary>
      <div class="story-outline-history__body">
        <p id="story-outline-history-hint" class="form-hint">查看不会改变当前内容；采用时会先确认，并创建一个新版本。</p>
        <ul class="story-outline-history__list">
          <li v-for="rev in pastRevisions" :key="rev.id" class="story-outline-history__item">
            <div class="story-outline-history__copy">
              <strong>v{{ rev.version_number }} · {{ rev.title }}</strong>
              <p class="form-hint">{{ sourceLabel(rev.source) }} · {{ formatDate(rev.created_at) }}{{ rev.restored_from_revision_id ? ' · 来自过往版本' : '' }}</p>
            </div>
            <div class="story-outline-history__actions">
              <button type="button" class="btn btn-sm btn-ghost" data-action="view-story-outline-revision" :data-id="rev.id" @click="viewRevision(rev.id)">查看内容</button>
              <button type="button" class="btn btn-sm" data-action="restore-story-outline-revision" :data-id="rev.id" @click="restoreRevision(rev.id)">采用为新版本</button>
            </div>
          </li>
        </ul>
      </div>
    </details>
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from "vue"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"
import StoryOutlineEditorFields from "./StoryOutlineEditorFields.vue"
import { useStoryOutline } from "./useStoryOutline.js"
import { getRouter } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, default: null },
  current: { type: Object, default: null },
  history: { type: Array, default: () => [] },
  historyTotal: { type: Number, default: 0 },
  characters: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
  loadError: { type: String, default: null },
  assetLoadError: { type: String, default: null },
})

const ctx = useStoryOutline(props)

const reloading = ref(false)

// ---- 从 composable 解构（避免模板中写 ctx.xxx） ----

const {
  current,
  currentRevision,
  hasCurrentRevision,
  projectId,
  history,
  historyTotal,
  loadError,
  assetLoadError,
  preview,
  applyError,
  applying,
  previewConflict,
  rebasingPreview,
  previewRestored,
  previewStorageError,
  previewSaveState,
  taskProgress,
  taskNotice,
  cancelPending,
  hasRunningTask,
  canCancelTask,
  showDismissTask,
  showGenerateForm,
  applyPreview,
  rebasePreview,
  discardPreview,
  cancelTask,
  dismissTask,
  viewRevision,
  restoreRevision,
  reload,
  readableOutline,
} = ctx

const pastRevisions = computed(() => history.value.filter((revision) => (
  revision.id !== current.value?.current_revision_id && !revision.is_current
)))
const pastRevisionTotal = computed(() => Math.max(
  pastRevisions.value.length,
  (Number(historyTotal.value) || history.value.length) - (hasCurrentRevision.value ? 1 : 0),
))

// ---- 辅助函数 ----

const SOURCE_LABELS_RECORD = {
  manual: "手工创建",
  ai_generated: "AI 生成后采用",
  restored: "从历史版本采用",
}

function sourceLabel(source) {
  return SOURCE_LABELS_RECORD[source] || "其他方式创建"
}

function formatDate(value) {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN")
}

function openManualEditor() {
  getRouter()?.navigate("outline", "story-outline", true, new URLSearchParams("edit=1"))
}

/** 重新加载。 */
async function handleReload() {
  if (reloading.value) return false
  reloading.value = true
  try {
    return await reload()
  } finally {
    reloading.value = false
  }
}

async function handleReloadFromMenu(event) {
  const details = event.currentTarget.closest("details")
  details.open = false
  details.querySelector(":scope > summary")?.focus()
  await handleReload()
}
</script>
