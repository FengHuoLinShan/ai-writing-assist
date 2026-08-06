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
      <p>故事总览加载失败</p>
      <p class="outline-empty-detail">{{ loadError }}</p>
      <button class="btn btn-sm" data-action="reload-story-outline" @click="handleReload">重新加载</button>
    </div>

    <!-- ========== 主内容区 ========== -->
    <template v-else>
    <section class="card" aria-labelledby="story-outline-intro-title">
      <div class="section-header">
        <div>
          <h2 id="story-outline-intro-title">故事总览</h2>
          <p class="form-hint">在进入具体篇章前，先确定故事的高层方向。采用修改时会保留当前内容为历史版本，不会自动替你改写篇章或场景。</p>
        </div>
        <div class="view-header__actions">
          <button class="btn btn-sm" data-action="edit-story-outline" @click="showManualEditor">{{ hasCurrentRevision ? '编辑为新版本' : '手工创建' }}</button>
          <button class="btn btn-sm btn-primary" data-action="generate-story-outline" :disabled="hasRunningTask" @click="showGenerateForm">AI 生成故事总览</button>
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

    <!-- ========== 预览编辑器 ========== -->
    <section v-if="preview" class="card" aria-labelledby="story-outline-preview-title">
      <div class="section-header">
        <div>
          <h3 id="story-outline-preview-title">AI 故事总览预览</h3>
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
      <section class="story-outline-list-editor" aria-labelledby="story-outline-storylines-title">
        <div class="section-header">
          <div><h4 id="story-outline-storylines-title">主要剧情线</h4><p class="form-hint">把故事中最重要的发展方向拆成可排序的项目。</p></div>
          <button class="btn btn-sm" type="button" @click="addItem('major_storylines')">新增剧情线</button>
        </div>
        <article v-for="(item, index) in previewContent.major_storylines" :key="`storyline-${index}`" class="card story-outline-list-item">
          <div class="story-outline-list-item__header"><strong>剧情线 {{ index + 1 }}</strong><ListActions :index="index" :length="previewContent.major_storylines.length" @move="moveItem('major_storylines', index, $event)" @remove="removeItem('major_storylines', index)" /></div>
          <div class="form-grid form-grid--2">
            <label class="form-group">名称<input v-model="item.name" class="form-input" /></label>
            <label class="form-group">作用<input v-model="item.narrative_function" class="form-input" placeholder="它在故事中解决什么" /></label>
            <label class="form-group">发展轨迹<textarea v-model="item.trajectory" class="form-textarea" rows="3" /></label>
            <label class="form-group">收束方向<textarea v-model="item.resolution_direction" class="form-textarea" rows="3" /></label>
          </div>
          <label class="form-group">交汇点<input class="form-input" :value="listText(item.intersections)" placeholder="多个内容用换行或顿号分开" @input="setList(item, 'intersections', $event.target.value)" /></label>
        </article>
        <p v-if="!previewContent.major_storylines.length" class="form-hint story-outline-list-empty">还没有主要剧情线，可以稍后再补充。</p>
      </section>

      <section class="story-outline-list-editor" aria-labelledby="story-outline-movements-title">
        <div class="section-header">
          <div><h4 id="story-outline-movements-title">故事推进</h4><p class="form-hint">记录每个阶段结束后，故事状态发生了什么变化。</p></div>
          <button class="btn btn-sm" type="button" @click="addItem('macro_movements')">新增推进</button>
        </div>
        <article v-for="(item, index) in previewContent.macro_movements" :key="`movement-${index}`" class="card story-outline-list-item">
          <div class="story-outline-list-item__header"><strong>推进 {{ index + 1 }}</strong><ListActions :index="index" :length="previewContent.macro_movements.length" @move="moveItem('macro_movements', index, $event)" @remove="removeItem('macro_movements', index)" /></div>
          <div class="form-grid form-grid--2">
            <label class="form-group">名称<input v-model="item.name" class="form-input" /></label>
            <label class="form-group">状态变化<textarea v-model="item.story_state_change" class="form-textarea" rows="3" /></label>
          </div>
          <label class="form-group">关联剧情线<input class="form-input" :value="listText(item.advanced_storylines)" placeholder="多个名称用换行或顿号分开" @input="setList(item, 'advanced_storylines', $event.target.value)" /></label>
        </article>
        <p v-if="!previewContent.macro_movements.length" class="form-hint story-outline-list-empty">还没有故事推进。</p>
      </section>

      <section class="story-outline-list-editor" aria-labelledby="story-outline-decisions-title">
        <div class="section-header">
          <div><h4 id="story-outline-decisions-title">待决定问题</h4><p class="form-hint">保留尚未确定、但会影响后续写作的选择。</p></div>
          <button class="btn btn-sm" type="button" @click="addItem('open_decisions')">新增问题</button>
        </div>
        <article v-for="(item, index) in previewContent.open_decisions" :key="`decision-${index}`" class="card story-outline-list-item">
          <div class="story-outline-list-item__header"><strong>问题 {{ index + 1 }}</strong><ListActions :index="index" :length="previewContent.open_decisions.length" @move="moveItem('open_decisions', index, $event)" @remove="removeItem('open_decisions', index)" /></div>
          <div class="form-grid form-grid--2">
            <label class="form-group">问题<input v-model="item.question" class="form-input" /></label>
            <label class="form-group">影响<textarea v-model="item.why_it_matters" class="form-textarea" rows="3" /></label>
          </div>
          <label class="form-group">可选方向<input class="form-input" :value="listText(item.options)" placeholder="多个方向用换行或顿号分开" @input="setList(item, 'options', $event.target.value)" /></label>
        </article>
        <p v-if="!previewContent.open_decisions.length" class="form-hint story-outline-list-empty">暂时没有待决定问题。</p>
      </section>
      <textarea id="story-outline-preview-major-storylines" hidden :value="JSON.stringify(previewContent.major_storylines)" />
      <textarea id="story-outline-preview-macro-movements" hidden :value="JSON.stringify(previewContent.macro_movements)" />
      <textarea id="story-outline-preview-open-decisions" hidden :value="JSON.stringify(previewContent.open_decisions)" />
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
          <h3 id="story-outline-current-title">当前版本 · v{{ currentRevision.version_number }}</h3>
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
        <h4>故事推进</h4>
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
        <h4>待决定问题</h4>
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
      <h3 id="story-outline-empty-title">尚未创建故事总览</h3>
      <p>可以手工创建，也可以让 AI 生成一份完整可编辑的预览。</p>
    </section>

    <!-- ========== 修订历史 ========== -->
    <section class="card" aria-labelledby="story-outline-history-title">
      <div class="section-header">
        <div>
          <h3 id="story-outline-history-title">历史版本 · {{ historyTotal }}</h3>
          <p class="form-hint">采用历史内容会创建一个新版本，不会改写原有历史。</p>
        </div>
      </div>
      <ul v-if="history.length" class="item-list">
        <li v-for="rev in history" :key="rev.id" class="card">
          <div class="section-header">
            <div>
              <strong>v{{ rev.version_number }} · {{ rev.title }}</strong>
              <p class="form-hint">{{ sourceLabel(rev.source) }} · {{ formatDate(rev.created_at) }}{{ rev.restored_from_revision_id ? ' · 来自历史版本' : '' }}</p>
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
import ListActions from "./StoryListActions.vue"
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
  previewContent.major_storylines = Array.isArray(c.major_storylines) ? JSON.parse(JSON.stringify(c.major_storylines)) : []
  previewContent.macro_movements = Array.isArray(c.macro_movements) ? JSON.parse(JSON.stringify(c.macro_movements)) : []
  previewContent.open_decisions = Array.isArray(c.open_decisions) ? JSON.parse(JSON.stringify(c.open_decisions)) : []
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

const NEW_ITEM = {
  major_storylines: () => ({ name: "", narrative_function: "", trajectory: "", intersections: [], resolution_direction: "" }),
  macro_movements: () => ({ name: "", story_state_change: "", advanced_storylines: [] }),
  open_decisions: () => ({ question: "", why_it_matters: "", options: [] }),
}

function addItem(field) {
  previewContent[field].push(NEW_ITEM[field]())
}

function removeItem(field, index) {
  previewContent[field].splice(index, 1)
}

function moveItem(field, index, direction) {
  const target = index + Number(direction)
  if (target < 0 || target >= previewContent[field].length) return
  const [item] = previewContent[field].splice(index, 1)
  previewContent[field].splice(target, 0, item)
}

function listText(value) {
  return Array.isArray(value) ? value.join("、") : ""
}

function setList(item, field, value) {
  item[field] = String(value || "").split(/[\n、；;]+/u).map((part) => part.trim()).filter(Boolean)
}

/** 重新加载。 */
async function handleReload() {
  await reload()
}
</script>
