<!--
  OutlineStoryTab — outline/story-outline 子标签根组件。
  DOM class/id/data-action 保持 E2E 视觉/行为契约；事件由 Vue 绑定。
  模态框操作（生成表单、手动编辑、历史查看）仍走 showModalHtml 外壳。
-->
<template>
  <div class="story-outline-workspace">
    <!-- ========== 无项目 ========== -->
    <div v-if="!projectId" class="empty-state"><p>请先选择项目。</p></div>

    <!-- ========== 加载错误 ========== -->
    <div v-else-if="loadError" class="empty-state" role="alert">
      <div class="empty-icon">!</div>
      <p>小说总纲加载失败</p>
      <p class="outline-empty-detail">{{ loadError }}</p>
      <button class="btn btn-sm" data-action="reload-story-outline" @click="handleReload">重新加载</button>
    </div>

    <!-- ========== 主内容区 ========== -->
    <template v-else>
    <section class="card" aria-labelledby="story-outline-intro-title">
      <div class="section-header">
        <div>
          <h2 id="story-outline-intro-title">小说总纲</h2>
          <p class="form-hint">位于世界设定之后、正式写作之前，用于设计至少覆盖半部小说的高层方向。
          采用总纲只会创建新的总纲 revision，不会创建篇章纲、剧情线或 Scene。</p>
        </div>
        <div class="view-header__actions">
          <button class="btn btn-sm" data-action="edit-story-outline" @click="showManualEditor">{{ hasCurrentRevision ? '编辑为新版本' : '手工创建' }}</button>
          <button class="btn btn-sm btn-primary" data-action="generate-story-outline" :disabled="hasRunningTask" @click="showGenerateForm">AI 生成总纲</button>
          <button class="btn btn-sm btn-ghost" data-action="reload-story-outline" @click="handleReload">重新加载</button>
        </div>
      </div>
      <p v-if="assetLoadError" class="form-error" role="status">{{ assetLoadError }}</p>
      <p v-if="taskNotice" class="form-error" role="alert">{{ taskNotice }}</p>
    </section>

    <!-- ========== 任务进度 ========== -->
    <section v-if="taskProgress" class="outline-progress-card-wrap">
      <WorkflowProgressCard
        :progress="taskProgress"
        variant="card"
        title="AI 小说总纲"
        :message="taskProgress.message || ''"
        :attention-required="Boolean(taskProgress?.failed || taskProgress?.stateUnknown)"
      >
        <div v-if="canCancelTask || showDismissTask" class="workflow-progress__actions">
          <button v-if="canCancelTask" class="btn btn-sm btn-ghost" data-action="cancel-story-outline-task" :disabled="cancelPending" @click="cancelTask">{{ cancelPending ? '取消中...' : '取消生成' }}</button>
          <button v-if="showDismissTask" class="btn btn-sm btn-ghost" data-action="dismiss-story-outline-task" @click="dismissTask">关闭任务</button>
        </div>
      </WorkflowProgressCard>
    </section>

    <!-- ========== 预览编辑器 ========== -->
    <section v-if="preview" class="card" aria-labelledby="story-outline-preview-title">
      <div class="section-header">
        <div>
          <h3 id="story-outline-preview-title">AI 总纲完整预览</h3>
          <p class="form-hint">生成结果尚未写入总纲。所有字段都可编辑；只有点击"采用为新版本"才会写入。</p>
        </div>
      </div>
      <div class="form-group">
        <label for="story-outline-preview-title-input">标题</label>
        <input class="form-input" id="story-outline-preview-title-input" :value="previewContent.title" @input="previewContent.title = $event.target.value" />
      </div>
      <div class="form-grid form-grid--2">
        <div class="form-group">
          <label for="story-outline-preview-premise">核心前提</label>
          <textarea class="form-textarea" id="story-outline-preview-premise" rows="5" :value="previewContent.creative_core?.premise" @input="previewContent.creative_core.premise = $event.target.value"></textarea>
        </div>
        <div class="form-group">
          <label for="story-outline-preview-tone">基调与读者承诺</label>
          <textarea class="form-textarea" id="story-outline-preview-tone" rows="5" :value="previewContent.creative_core?.tone_and_reader_promise" @input="previewContent.creative_core.tone_and_reader_promise = $event.target.value"></textarea>
        </div>
        <div class="form-group">
          <label for="story-outline-preview-engine">故事引擎</label>
          <textarea class="form-textarea" id="story-outline-preview-engine" rows="5" :value="previewContent.creative_core?.story_engine" @input="previewContent.creative_core.story_engine = $event.target.value"></textarea>
        </div>
        <div class="form-group">
          <label for="story-outline-preview-ending">结局方向（可留空）</label>
          <textarea class="form-textarea" id="story-outline-preview-ending" rows="5" :value="previewEndingRaw" @input="previewEndingRaw = $event.target.value"></textarea>
        </div>
      </div>
      <div class="form-group">
        <label for="story-outline-preview-markdown">高层总纲（Markdown）</label>
        <textarea class="form-textarea" id="story-outline-preview-markdown" rows="14" :value="previewContent.outline_markdown" @input="previewContent.outline_markdown = $event.target.value"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-preview-major-storylines">主要剧情线（JSON 数组）</label>
        <p class="form-hint">每项字段：name、narrative_function、trajectory、intersections 字符串数组、resolution_direction。可以是 []。</p>
        <textarea class="form-textarea" id="story-outline-preview-major-storylines" rows="12" :value="jsonText.major_storylines" @input="jsonText.major_storylines = $event.target.value"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-preview-macro-movements">宏观推进（JSON 数组）</label>
        <p class="form-hint">每项字段：name、story_state_change、advanced_storylines 字符串数组；它们是浏览导航摘要，不作为数据库关联键。可以是 []。</p>
        <textarea class="form-textarea" id="story-outline-preview-macro-movements" rows="10" :value="jsonText.macro_movements" @input="jsonText.macro_movements = $event.target.value"></textarea>
      </div>
      <div class="form-group">
        <label for="story-outline-preview-open-decisions">开放决策（JSON 数组）</label>
        <p class="form-hint">每项字段：question、why_it_matters、options 字符串数组。可以是 []。</p>
        <textarea class="form-textarea" id="story-outline-preview-open-decisions" rows="10" :value="jsonText.open_decisions" @input="jsonText.open_decisions = $event.target.value"></textarea>
      </div>
      <p id="story-outline-apply-error" class="form-error" role="alert">{{ applyError }}</p>
      <div class="form-actions">
        <button class="btn btn-sm btn-primary" data-action="apply-story-outline-preview" @click="applyPreview">采用为新版本</button>
        <button class="btn btn-sm btn-ghost" data-action="discard-story-outline-preview" @click="discardPreview">放弃此建议</button>
      </div>
    </section>

    <!-- ========== 当前版本 / 空状态 ========== -->
    <section v-if="currentRevision" class="card" aria-labelledby="story-outline-current-title">
      <div class="section-header">
        <div>
          <h3 id="story-outline-current-title">当前总纲 · v{{ currentRevision.version_number }}</h3>
          <p class="form-hint">{{ sourceLabel(currentRevision.source) }} · {{ formatDate(currentRevision.created_at) }}</p>
        </div>
      </div>
      <section><h4>{{ currentRevision.title }}</h4></section>
      <div class="form-grid form-grid--2">
        <div class="card"><h4>核心前提</h4><p>{{ currentRevision.creative_core?.premise }}</p></div>
        <div class="card"><h4>基调与读者承诺</h4><p>{{ currentRevision.creative_core?.tone_and_reader_promise }}</p></div>
        <div class="card"><h4>故事引擎</h4><p>{{ currentRevision.creative_core?.story_engine }}</p></div>
        <div class="card"><h4>结局方向</h4><p>{{ currentRevision.creative_core?.ending_direction || '待决定' }}</p></div>
      </div>
      <section><h4>高层总纲</h4><pre class="generate-markdown-pre">{{ currentRevision.outline_markdown }}</pre></section>
      <section>
        <h4>主要剧情线</h4>
        <template v-if="currentRevision.major_storylines?.length">
          <article v-for="(item, idx) in currentRevision.major_storylines" :key="idx" class="card">
            <h5>{{ item.name }}</h5>
            <p><strong>叙事功能：</strong>{{ item.narrative_function }}</p>
            <p><strong>轨迹：</strong>{{ item.trajectory }}</p>
            <p><strong>交汇点：</strong>{{ (item.intersections || []).join('、') || '暂无' }}</p>
            <p><strong>收束方向：</strong>{{ item.resolution_direction }}</p>
          </article>
        </template>
        <p v-else class="form-hint">暂无。</p>
      </section>
      <section>
        <h4>宏观推进</h4>
        <template v-if="currentRevision.macro_movements?.length">
          <article v-for="(item, idx) in currentRevision.macro_movements" :key="idx" class="card">
            <h5>{{ item.name }}</h5>
            <p>{{ item.story_state_change }}</p>
            <p><strong>推进剧情线：</strong>{{ (item.advanced_storylines || []).join('、') || '暂无' }}</p>
          </article>
        </template>
        <p v-else class="form-hint">暂无。</p>
      </section>
      <section>
        <h4>开放决策</h4>
        <template v-if="currentRevision.open_decisions?.length">
          <article v-for="(item, idx) in currentRevision.open_decisions" :key="idx" class="card">
            <h5>{{ item.question }}</h5>
            <p>{{ item.why_it_matters }}</p>
            <p><strong>可选方向：</strong>{{ (item.options || []).join('、') || '暂无' }}</p>
          </article>
        </template>
        <p v-else class="form-hint">暂无。</p>
      </section>
    </section>
    <section v-else-if="!loadError && projectId" class="empty-state" aria-labelledby="story-outline-empty-title">
      <div class="empty-icon">&#128209;</div>
      <h3 id="story-outline-empty-title">尚未创建小说总纲</h3>
      <p>可以手工创建，也可以让 AI 生成一份完整可编辑的预览。</p>
    </section>

    <!-- ========== 修订历史 ========== -->
    <section class="card" aria-labelledby="story-outline-history-title">
      <div class="section-header">
        <div>
          <h3 id="story-outline-history-title">修订历史 · {{ historyTotal }}</h3>
          <p class="form-hint">采用历史内容会复制其内容并创建更高版本号的新 revision，不会原地回滚或改写历史。</p>
        </div>
      </div>
      <ul v-if="history.length" class="item-list">
        <li v-for="rev in history" :key="rev.id" class="card">
          <div class="section-header">
            <div>
              <strong>v{{ rev.version_number }} · {{ rev.title }}</strong>
              <p class="form-hint">{{ sourceLabel(rev.source) }} · {{ formatDate(rev.created_at) }}{{ rev.restored_from_revision_id ? ` · 来自历史 revision ${rev.restored_from_revision_id}` : '' }}</p>
            </div>
            <div class="view-header__actions">
              <span v-if="rev.id === current?.current_revision_id || rev.is_current" class="badge badge-success">当前版本</span>
              <button class="btn btn-sm" data-action="view-story-outline-revision" :data-id="rev.id" @click="viewRevision(rev.id)">查看</button>
              <button class="btn btn-sm btn-primary" data-action="restore-story-outline-revision" :data-id="rev.id" :disabled="rev.id === current?.current_revision_id || rev.is_current" @click="restoreRevision(rev.id)">采用为新版本</button>
            </div>
          </div>
        </li>
      </ul>
      <p v-else class="form-hint">还没有历史版本。</p>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import WorkflowProgressCard from "../../../components/WorkflowProgressCard.vue"
import { useStoryOutline } from "./useStoryOutline.js"

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

// ---- 预览编辑器双向绑定 ----

const previewContent = reactive({
  title: "",
  creative_core: { premise: "", tone_and_reader_promise: "", story_engine: "", ending_direction: null },
  outline_markdown: "",
  major_storylines: [],
  macro_movements: [],
  open_decisions: [],
})

const jsonText = reactive({
  major_storylines: "[]",
  macro_movements: "[]",
  open_decisions: "[]",
})

/** 预览结束时结尾方向原始字符串（null 转 ""）。 */
const previewEndingRaw = ref("")

/** 同步 preview reactive 副本。 */
function syncPreview() {
  const c = ctx.preview.value?.content
  if (!c) return
  previewContent.title = c.title || ""
  previewContent.creative_core.premise = c.creative_core?.premise || ""
  previewContent.creative_core.tone_and_reader_promise = c.creative_core?.tone_and_reader_promise || ""
  previewContent.creative_core.story_engine = c.creative_core?.story_engine || ""
  previewContent.creative_core.ending_direction = c.creative_core?.ending_direction ?? null
  previewEndingRaw.value = c.creative_core?.ending_direction ?? ""
  previewContent.outline_markdown = c.outline_markdown || ""
  previewContent.major_storylines = Array.isArray(c.major_storylines) ? c.major_storylines : []
  previewContent.macro_movements = Array.isArray(c.macro_movements) ? c.macro_movements : []
  previewContent.open_decisions = Array.isArray(c.open_decisions) ? c.open_decisions : []
  jsonText.major_storylines = JSON.stringify(previewContent.major_storylines, null, 2)
  jsonText.macro_movements = JSON.stringify(previewContent.macro_movements, null, 2)
  jsonText.open_decisions = JSON.stringify(previewContent.open_decisions, null, 2)
}

watch(() => ctx.preview.value, (val) => {
  if (val?.content) syncPreview()
}, { immediate: true })

// ---- 从 composable 解构（避免模板中写 ctx.xxx） ----

const {
  current,
  currentRevision,
  hasCurrentRevision,
  projectId,
  history,
  historyTotal,
  characters,
  entities,
  loadError,
  assetLoadError,
  preview,
  applyError,
  taskProgress,
  taskNotice,
  cancelPending,
  hasRunningTask,
  canCancelTask,
  showDismissTask,
  showGenerateForm,
  applyPreview,
  discardPreview,
  cancelTask,
  dismissTask,
  showManualEditor,
  viewRevision,
  restoreRevision,
  reload,
  collectEditor,
} = ctx

// ---- 辅助函数 ----

const SOURCE_LABELS_RECORD = {
  manual: "手工创建",
  ai_generated: "AI 生成后采用",
  restored: "从历史版本采用",
}

function sourceLabel(source) {
  return SOURCE_LABELS_RECORD[source] || source || "未知来源"
}

function formatDate(value) {
  if (!value) return "时间未知"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN")
}

/** 重新加载。 */
async function handleReload() {
  await reload()
}
</script>
