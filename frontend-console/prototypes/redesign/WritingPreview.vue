<script setup>
import { computed, nextTick, onMounted, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue'
import { useModalDialog } from '../../vue/composables/useModalDialog.js'
import PreviewIcon from './PreviewIcon.vue'
import PreviewNotice from './PreviewNotice.vue'
import { vReveal } from './motion.js'
import { chapters as demoChapters, paragraphs } from './data.js'
const props = defineProps({ state: { type: String, default: 'normal' }, focus: Boolean, externalPanel: Boolean })
const emit = defineEmits(['open','navigate'])
const chapters = reactive(demoChapters.map(chapter => ({ ...chapter })))
const chapterQuery = ref('')
const managing = ref(false)
const checkedChapters = ref([])
const deletedChapters = ref([])
const currentScene = ref('码头上的初次相遇')
const pinnedEvidence = ref(false)
const chapterFeedback = ref('')
const selected = ref(2)
const manuscriptMode = ref('working')
const writingStarted = ref(props.state !== 'empty')
const saveDemoState = ref('ready')
const emptyDraft = reactive({ title: '', content: '' })
const chapterDrafts = reactive(Object.fromEntries(chapters.map((chapter, index) => [index, {
  title: chapter.title,
  content: [chapter.text, ...paragraphs].join('\n\n'),
}]))
)
const emptySaved = reactive({ title: '', content: '' })
const savedDrafts = reactive(Object.fromEntries(chapters.map((chapter, index) => [index, {
  title: chapter.title,
  content: [chapter.text, ...paragraphs].join('\n\n'),
}]))
)
const narrowQuery = globalThis.matchMedia?.('(max-width: 800px)')
const narrow = ref(narrowQuery?.matches || false)
const chaptersOpen = ref(!narrow.value)
const inspectorOpen = ref(!narrow.value)
const reference = ref('本章')
const scrollArea = ref(null)
const editorArea = ref(null)
const titleArea = ref(null)
const chaptersVisible = computed(() => chaptersOpen.value && !props.focus && !props.externalPanel)
const inspectorVisible = computed(() => inspectorOpen.value && !props.focus && !props.externalPanel)
const currentDraft = computed(() => chapterDrafts[selected.value])
const activeDraft = computed(() => props.state === 'empty' ? emptyDraft : currentDraft.value)
const activeSaved = computed(() => props.state === 'empty' ? emptySaved : savedDrafts[selected.value])
const isDirty = computed(() => activeDraft.value.title !== activeSaved.value.title || activeDraft.value.content !== activeSaved.value.content)
const manuscriptIdentity = computed(() => ({
  working: { label: '工作稿', tone: 'blue', readonly: false, detail: '可直接编辑，修改仅保留在本次预览。' },
  published: { label: '正式正文 · 只读', tone: 'green', readonly: true, detail: '这是本作品内的正式版本，当前仅供查看。' },
  history: { label: '历史版本 · 只读', tone: 'teal', readonly: true, detail: '历史版本不会覆盖当前工作稿。' },
  candidate: { label: 'AI 建议 · 待决定', tone: 'purple', readonly: true, detail: '建议尚未采用，正文仍保持不变。' },
}[manuscriptMode.value]))
function toggleChapters() { if (narrow.value) inspectorOpen.value = false; chaptersOpen.value = !chaptersOpen.value }
function toggleInspector() { if (narrow.value) chaptersOpen.value = false; inspectorOpen.value = !inspectorOpen.value }
function showChapters() { chaptersOpen.value = true }
function showInspector() { inspectorOpen.value = true }
function locateChapter(index) {
  const next = Number(index)
  if (!Number.isInteger(next) || next < 0 || next >= chapters.length) return false
  selected.value = next
  writingStarted.value = true
  return true
}
function beginWriting() { writingStarted.value = true; void nextTick(() => { syncEditorArea(); editorArea.value?.focus() }) }
function createChapter() {
  const index = chapters.length
  chapters.push({ title: '新的章节', words: '0', state: '写作中', text: '' })
  chapterDrafts[index] = { title: '新的章节', content: '' }
  savedDrafts[index] = { title: '新的章节', content: '' }
  selected.value = index
}
function deleteSelected() {
  if (!checkedChapters.value.length || !confirm(`将选中的${checkedChapters.value.length}章移入本次预览的历史？可从目录恢复。`)) return
  deletedChapters.value.push(...checkedChapters.value)
  checkedChapters.value = []
  chapterFeedback.value = '已移入历史 · 演示，草稿仍保留'
}
function syncEditorArea() {
  if (titleArea.value && titleArea.value.textContent !== activeDraft.value.title) {
    titleArea.value.textContent = activeDraft.value.title
  }
  if (editorArea.value && editorArea.value.textContent !== activeDraft.value.content) {
    editorArea.value.textContent = activeDraft.value.content
  }
}
function updateContent(event) { activeDraft.value.content = event.currentTarget.innerText || ''; if (saveDemoState.value === 'saved') saveDemoState.value = 'ready' }
function updateTitle(event) { activeDraft.value.title = event.currentTarget.innerText || ''; if (saveDemoState.value === 'saved') saveDemoState.value = 'ready' }
function markSaving() { if (!manuscriptIdentity.value.readonly) saveDemoState.value = 'saving' }
function markSaved() {
  if (manuscriptIdentity.value.readonly) return
  Object.assign(activeSaved.value, activeDraft.value)
  saveDemoState.value = 'saved'
}
function markFailure(kind) { if (!manuscriptIdentity.value.readonly) saveDemoState.value = kind }
function discardChanges() {
  if (manuscriptIdentity.value.readonly || !isDirty.value) return
  if (!globalThis.confirm?.('放弃本次未保存修改？当前示例文字会恢复到上次演示保存的版本。')) return
  Object.assign(activeDraft.value, activeSaved.value)
  saveDemoState.value = 'ready'
  void nextTick(syncEditorArea)
}
function recoverConflict() { if (!manuscriptIdentity.value.readonly) saveDemoState.value = 'ready' }
watch(() => props.focus, async () => {
  const position = scrollArea.value?.scrollTop || 0
  await nextTick()
  if (scrollArea.value) scrollArea.value.scrollTop = position
}, { flush: 'pre' })
watch(() => props.state, value => { writingStarted.value = value !== 'empty' })
watch(selected, () => { saveDemoState.value = 'ready' })
watch([selected, manuscriptMode, () => props.state], async () => { await nextTick(); syncEditorArea() })
const chapterModal = useModalDialog({ isOpen: () => narrow.value && chaptersVisible.value, requestClose: () => { chaptersOpen.value = false } })
const inspectorModal = useModalDialog({ isOpen: () => narrow.value && inspectorVisible.value, requestClose: () => { inspectorOpen.value = false } })
function bindChapter(el) { chapterModal.overlayRef.value = el; chapterModal.dialogRef.value = el }
function bindInspector(el) { inspectorModal.overlayRef.value = el; inspectorModal.dialogRef.value = el }
function syncNarrow(event) { narrow.value = event.matches; chaptersOpen.value = !event.matches; inspectorOpen.value = !event.matches }
onMounted(() => { syncEditorArea(); narrowQuery?.addEventListener?.('change', syncNarrow) })
onBeforeUnmount(() => narrowQuery?.removeEventListener?.('change', syncNarrow))
onDeactivated(() => { if (narrow.value) { chaptersOpen.value = false; inspectorOpen.value = false } })
defineExpose({ toggleChapters, toggleInspector, showChapters, showInspector, locateChapter, chaptersVisible, inspectorVisible })
</script>
<template>
  <div class="rd-writing" :class="{ 'chapters-closed': !chaptersVisible, 'inspector-closed': !inspectorVisible }">
    <aside :ref="bindChapter" :role="narrow ? 'dialog' : undefined" :aria-modal="narrow && chaptersVisible ? 'true' : undefined" @keydown="chapterModal.onKeydown" @focusin="chapterModal.onFocusin" class="rd-chapters" :inert="!chaptersVisible" aria-label="章节目录">
      <div class="rd-panel-heading"><span>章节目录 <small>{{ chapters.length - deletedChapters.length }}</small></span><button class="rd-icon-button" aria-label="收起章节目录" @click="chaptersOpen = false"><span class="rd-button-content"><PreviewIcon name="sidebar"/></span></button></div>
      <button class="rd-volume" @click="emit('open', '第一部 · 潮声', 'outline')"><span class="rd-small-icon tone-blue"><PreviewIcon name="outline" /></span><span>第一部 · 潮声<small>6 章 · 7,828 字</small></span><PreviewIcon name="down"/></button>
      <div class="rd-chapter-search"><label class="rd-sr-only" for="rd-chapter-search">搜索章节</label><input id="rd-chapter-search" v-model="chapterQuery" placeholder="搜索章节"/><button class="rd-text-button" @click="managing = !managing">{{ managing ? '完成管理' : '管理' }}</button></div>
      <div v-if="managing" class="rd-chapter-search"><span>{{ checkedChapters.length }}章已选</span><button class="rd-text-button" :disabled="!checkedChapters.length" @click="deleteSelected">移入历史</button><button v-if="deletedChapters.length" class="rd-text-button" @click="deletedChapters = []; chapterFeedback = '已恢复章节 · 演示'">恢复目录</button></div>
      <div class="rd-chapter-list"><template v-for="(chapter, i) in chapters" :key="i"><label v-if="managing && !deletedChapters.includes(i)" class="rd-check-label"><input v-model="checkedChapters" type="checkbox" :value="i" :aria-label="`选择第${i+1}章`"/>第{{ i + 1 }}章</label><button v-if="!deletedChapters.includes(i) && chapterDrafts[i].title.includes(chapterQuery)" class="rd-chapter" :class="{ selected: selected === i }" :aria-current="selected === i ? 'true' : undefined" @click="selected = i"><span class="rd-chapter-number">{{ String(i + 1).padStart(2, '0') }}</span><span><strong>{{ chapterDrafts[i].title || '未命名章节' }}</strong><small>{{ chapter.words }}<span v-if="i < 3"> 字</span></small></span><span v-if="i < 2" class="rd-check" aria-label="已完成">✓</span><span v-else-if="i === 2" class="rd-writing-dot" aria-label="写作中" /></button></template><p v-if="!chapters.some((_, i) => !deletedChapters.includes(i) && chapterDrafts[i].title.includes(chapterQuery))" class="rd-demonstration">没有匹配章节。调整搜索或新建第一章。</p></div>
      <button class="rd-new-chapter" @click="createChapter"><PreviewIcon name="plus"/>新建章节</button>
      <div class="rd-chapter-bottom"><div class="rd-progress-label"><span>今日写作</span><strong>862 <small>/ 1,500 字</small></strong></div><progress value="862" max="1500" aria-label="示例今日写作进度" /><small>再写 638 字，完成今天的小目标。</small></div>
    </aside>
    <section class="rd-manuscript" aria-label="正文样板">
      <div ref="scrollArea" class="rd-paper-scroll">
        <PreviewNotice :state="state" @action="emit('open', '反馈与保护路径', state === 'conflict' ? 'compare' : 'states')" />
        <article v-reveal="selected" v-if="state !== 'empty' || writingStarted" class="rd-paper" :class="{ 'is-loading': state === 'loading' }">
          <div class="rd-paper-kicker"><span>第一部 · 潮声</span><span>第 {{ selected + 1 }} 章</span></div>
          <div class="rd-local-toolbar rd-writing-controls" aria-label="文稿控制">
            <span class="rd-badge" :class="isDirty ? 'tone-orange' : 'tone-green'">{{ isDirty ? '有未保存修改' : '示例已保存' }} · 演示</span>
            <button class="rd-button" :disabled="manuscriptIdentity.readonly || !isDirty || saveDemoState === 'saving'" @click="markSaving">保存工作稿</button>
            <button v-if="saveDemoState === 'saving'" class="rd-button primary" @click="markSaved">演示保存完成</button>
            <button class="rd-button" :disabled="manuscriptIdentity.readonly || !isDirty" @click="discardChanges">放弃修改</button>
            <button class="rd-text-button" @click="emit('open', '版本历史', 'versions', true)">版本历史 →</button>
            <details class="rd-save-state-menu"><summary class="rd-text-button">演示下一状态</summary><div class="rd-local-toolbar"><button class="rd-text-button" :disabled="manuscriptIdentity.readonly" @click="markFailure('service-failed')">服务失败</button><button class="rd-text-button" :disabled="manuscriptIdentity.readonly" @click="markFailure('backup-failed')">服务与备份都失败</button><button class="rd-text-button" :disabled="manuscriptIdentity.readonly" @click="markFailure('conflict')">冲突</button></div></details>
          </div>
          <div v-if="saveDemoState === 'saved'" class="rd-inline-notice tone-green" aria-live="polite"><strong>✓ 工作稿已保存 · 演示</strong><p>本次预览已记录当前示例版本，没有写入真实作品。</p></div>
          <div v-else-if="saveDemoState === 'service-failed'" class="rd-inline-notice tone-orange" aria-live="polite"><strong>! 服务暂时没有保存成功 · 演示</strong><p>当前文字仍在本页保留，可以重试或先复制保全。</p><button class="rd-button" @click="markSaving">重试保存</button></div>
          <div v-else-if="saveDemoState === 'backup-failed'" class="rd-inline-notice tone-red" aria-live="polite"><strong>! 服务与本机备份都没有成功 · 演示</strong><p>离开或刷新可能丢失当前修改。请先复制文字，再决定是否继续。</p><button class="rd-button" @click="markSaving">再次尝试</button></div>
          <div v-else-if="saveDemoState === 'conflict'" class="rd-inline-notice tone-red" aria-live="polite"><strong>! 发现另一个更新版本 · 演示</strong><p>当前文字仍保留，先比较版本，再决定是否覆盖。</p><button class="rd-button" @click="emit('open', '版本比较', 'compare', true)">打开比较</button><button class="rd-button" @click="recoverConflict">保留当前文字</button></div>
          <h1 id="rd-manuscript-title" ref="titleArea" class="rd-paper-title" :contenteditable="!manuscriptIdentity.readonly" :aria-readonly="String(manuscriptIdentity.readonly)" role="textbox" aria-label="章节标题" data-placeholder="为这一章起个名字…" @input="updateTitle"></h1>
          <div class="rd-paper-meta"><span class="rd-badge" :class="`tone-${manuscriptIdentity.tone}`">{{ manuscriptIdentity.label }}</span><span>林舟 · 白沙港 · 黄昏</span></div>
          <p class="rd-manuscript-hint" :class="{ 'is-readonly': manuscriptIdentity.readonly }">{{ manuscriptIdentity.detail }}</p>
          <div id="rd-manuscript-editor" ref="editorArea" class="rd-prose rd-manuscript-editor" :contenteditable="!manuscriptIdentity.readonly" :aria-readonly="String(manuscriptIdentity.readonly)" role="textbox" aria-multiline="true" aria-label="章节正文" data-placeholder="从这里开始写下这一章…" @input="updateContent"></div>
          <span class="rd-end-mark" aria-hidden="true">· · ·</span>
        </article>
        <section v-else class="rd-empty rd-writing-empty" aria-label="空正文">
          <span class="rd-empty-symbol" aria-hidden="true">✎</span><h2>这一章还没有正文</h2><p>从一个场景开始，让故事继续向前。</p><button class="rd-button primary" @click="beginWriting">开始写作</button>
        </section>
      </div>
      <footer class="rd-editor-footer"><span>{{ activeDraft.content.length.toLocaleString() }} 字<span class="rd-dot-separator">·</span>约 6 分钟阅读</span><label class="rd-manuscript-mode">稿件身份<select v-model="manuscriptMode" aria-label="选择稿件身份"><option value="working">工作稿 · 可编辑</option><option value="published">正式正文 · 只读</option><option value="history">历史版本 · 只读</option><option value="candidate">AI 建议 · 待决定</option></select></label></footer>
    </section>
    <aside :ref="bindInspector" :role="narrow ? 'dialog' : undefined" :aria-modal="narrow && inspectorVisible ? 'true' : undefined" @keydown="inspectorModal.onKeydown" @focusin="inspectorModal.onFocusin" class="rd-inspector" :inert="!inspectorVisible" aria-label="本章资料">
      <div class="rd-panel-heading"><span>本章资料</span><button class="rd-icon-button" aria-label="关闭资料栏" @click="inspectorOpen = false"><span class="rd-button-content"><PreviewIcon name="close"/></span></button></div>
      <div class="rd-segments" :style="{ '--rd-segments': 3, '--rd-selected': ['本章', '人物', '灵感'].indexOf(reference) }" aria-label="资料类别"><button v-for="tab in ['本章', '人物', '灵感']" :key="tab" :aria-pressed="reference === tab" @click="reference = tab">{{ tab }}</button></div>
      <template v-if="reference === '本章'"><section class="rd-inspector-section"><div class="rd-eyebrow">当前场景 · 手动选择</div><label class="rd-field">当前场景<select v-model="currentScene"><option>码头上的初次相遇</option><option>夜探灯塔</option></select></label><button class="rd-text-button" @click="emit('navigate', 'outline', `场景/${currentScene}`)">关联、新建与场景工作台 →</button><p>{{ currentScene === '夜探灯塔' ? '在雾中寻找灯火的来源，让两人面对同一个秘密。' : '让一张旧海图，把两个原本陌生的人带到同一条航线上。' }}</p><div class="rd-detail-line"><span>视角</span><strong>林舟</strong></div><div class="rd-detail-line"><span>地点</span><strong>白沙港 · 旧码头</strong></div><div class="rd-detail-line"><span>时间</span><strong>落潮前的黄昏</strong></div></section>
      <section class="rd-inspector-section"><div class="rd-section-label">写作辅助</div><button class="rd-source-link" @click="emit('navigate', 'map')">本章地图 →</button><button class="rd-source-link" @click="emit('navigate', 'outline')">随时查看大纲 →</button><button class="rd-source-link" @click="emit('navigate', 'search')">查找与钉选证据 →</button><button class="rd-text-button" @click="pinnedEvidence = !pinnedEvidence">{{ pinnedEvidence ? '✓ 已钉选 · 清除' : '钉选灯塔线索' }}</button><p v-if="pinnedEvidence" class="rd-inline-notice tone-teal">第一章：灯塔熄灭了三年。引用待作者决定，不自动插入正文。</p><button class="rd-source-link" @click="chapterFeedback = '本章导出成功的演示状态，不生成真实文件'">导出本章示例 →</button><button class="rd-source-link" @click="emit('navigate', 'tasks')">加入创作计划 →</button><p v-if="chapterFeedback" role="status" class="rd-demonstration">{{ chapterFeedback }}</p></section>
      <section class="rd-insight tone-orange"><div class="rd-inline"><span class="rd-notice-icon">!</span><strong>一个值得留意的细节</strong></div><p>灯塔已熄灭三年。这次亮起，将改变沈雁隐瞒真相的理由。</p><button class="rd-text-button" @click="emit('open', '本章一致性检查', 'conflicts', true)">回看相关设定 <PreviewIcon name="forward"/></button></section>
      <section class="rd-inspector-section"><div class="rd-section-label">这一幕要发生什么<button class="rd-text-button" @click="emit('open', '场景目标', 'scene', true)">详情 <PreviewIcon name="forward"/></button></div><ul class="rd-beats"><li class="done"><span>✓</span>林舟抵达白沙港</li><li class="done"><span>✓</span>沈雁认出海图上的记号</li><li><span>○</span>灯塔亮起，打破沉默</li></ul></section>

      <section class="rd-inspector-section"><div class="rd-section-label">出场人物<span class="rd-muted">02</span></div><button class="rd-person-row" @click="emit('open', '林舟', 'person', true)"><span class="rd-avatar tone-blue">林</span><span><strong>林舟</strong><small>她在寻找父亲留下的答案</small></span><PreviewIcon name="forward"/></button><button class="rd-person-row" @click="emit('open', '沈雁', 'person', true)"><span class="rd-avatar tone-purple">沈</span><span><strong>沈雁</strong><small>他知道更多，却选择沉默</small></span><PreviewIcon name="forward"/></button></section></template>
      <section v-reveal="reference" v-else-if="reference === '人物'" class="rd-inspector-section"><span class="rd-avatar large tone-blue">林</span><h3>林舟</h3><p>她想知道父亲为什么离开，却害怕答案证明，他的离开是一种选择。</p><div class="rd-detail-line"><span>当前欲望</span><strong>找到海图上的灯塔</strong></div><button class="rd-button" @click="emit('open', '林舟 · 人物档案', 'person', true)"><span class="rd-button-content">打开人物档案 <PreviewIcon name="forward"/></span></button></section>
      <section v-reveal="reference" v-else class="rd-inspector-section"><div class="rd-insight tone-purple"><span class="rd-eyebrow">一个可能的方向</span><h3>让沉默先回答</h3><p>不急着让沈雁解释。让他握紧风灯的动作，比对白更早暴露秘密。</p><button class="rd-button purple" @click="emit('open', '比较创作建议', 'compare', true)"><span class="rd-button-content">查看建议</span></button></div></section>

    </aside>
  </div>
</template>

<style scoped>
.rd-chapter-search{padding:10px 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}.rd-chapter-search input{width:100%;min-width:0}.rd-chapter-list>.rd-check-label{padding:8px}.rd-paper-title:empty::before{content:attr(data-placeholder);color:var(--muted);pointer-events:none}.rd-paper-title { min-height:1.3em;display: block; width: 100%; border: 0; padding: 0; margin: 0 0 14px; color: var(--ink); background: transparent; font: inherit; font-size: 34px; line-height: 1.3; font-weight: 650; }
.rd-writing-controls { margin: 0 0 22px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.rd-writing-controls .rd-save-state-menu { margin-left: auto; }
.rd-save-state-menu .rd-local-toolbar { margin: 8px 0 0; }
.rd-paper-title:focus, .rd-manuscript-editor:focus { outline: 2px solid color-mix(in srgb, var(--blue) 45%, transparent); outline-offset: 5px; border-radius: 4px; }
.rd-manuscript-editor { display: block; width: 100%; min-height: 650px; resize: none; overflow: hidden; border: 0; padding: 0; color: var(--ink); background: transparent; font: inherit; font-size: 18px; line-height: 1.95; letter-spacing: .015em; white-space: pre-wrap; }
.rd-manuscript-editor[aria-readonly="true"], .rd-paper-title[aria-readonly="true"] { cursor: default; }
.rd-manuscript-hint { margin: -18px 0 24px; color: var(--muted); font-size: 11px; line-height: 1.7; }
.rd-manuscript-hint.is-readonly { color: var(--purple); }
.rd-writing-empty { max-width: 600px; margin: 0 auto; }
.rd-manuscript-mode { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.rd-manuscript-mode select { border: 0; color: inherit; background: transparent; font: inherit; }
@media (max-width: 760px) {
  .rd-paper-title { font-size: 28px; }
  .rd-manuscript-editor { min-height: 480px; font-size: 17px; }
  .rd-editor-footer { gap: 8px; align-items: start; flex-wrap: wrap; }
  .rd-manuscript-mode { margin-left: auto; }
}
</style>
