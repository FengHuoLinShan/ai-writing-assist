<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import ActionMenu from '../../vue/components/ActionMenu.vue'
import WritingPreview from './WritingPreview.vue'
import SearchPreview from './SearchPreview.vue'
import StructurePreview from './StructurePreview.vue'
import MapPreview from './MapPreview.vue'
import SettingsPreview from './SettingsPreview.vue'
import CandidateReview from './CandidateReview.vue'
import VersionReview from './VersionReview.vue'
import WorldPreview from './WorldPreview.vue'
import ReaderPreview from './ReaderPreview.vue'
import AssistantPreview from './AssistantPreview.vue'
import ImportPreview from './ImportPreview.vue'
import IdentityPreview from './IdentityPreview.vue'
import JourneyPreview from './JourneyPreview.vue'
import JourneySetup from './JourneySetup.vue'
import ConflictReview from './ConflictReview.vue'
import WorkspacePreview from './WorkspacePreview.vue'
import ExperiencePreview from './ExperiencePreview.vue'
import PreviewDialog from './PreviewDialog.vue'
import PreviewNotice from './PreviewNotice.vue'
import { cancelPreviewMotion, setPreviewReducedMotion } from './motion.js'
import { navigation, pageTitles, statusOptions, people } from './data.js'
const initialQuery = new URLSearchParams(window.location.search)
const assistantTask = ref({ status: '待查看', intent: '关于码头相遇的一些想法', progress: 3, prompt: '', reminders: true, beforeWriting: true, dismissed: false })
const candidateDomain = ref('writing')
const candidateContext = ref(null)
const candidates = reactive({
 writing: { status: 'pending', source: '第三章 · 潮汐之间', review: '待审查', stale: false, title: '把沉默留给灯塔' },
 world: { destination: '世界资料', status: 'pending', source: '白沙港 · 地点资料', review: '待审查', stale: false, title: '落潮时出现的石路', original: '旧灯塔与港口之间有一条石路。', suggestion: '只有大潮退去之后，这条石路才会出现。' },
 outline: { status: 'pending', source: '第一部 · 潮声', review: '待审查', stale: false, title: '让秘密更晚一些揭晓', original: '码头相遇后，沈雁解释自己的身世。', suggestion: '码头相遇时只留下动作线索，在夜探灯塔后再揭晓身世。' },
 map: { status: 'pending', source: '白沙港 · 通行关系', review: '待审查', stale: false, title: '补充航线的潮汐限制', original: '沿岸道路可随时通行。', suggestion: '道路仅在落潮时开放，需要标出通行时点。' },
})
const currentCandidate = computed(() => candidates[candidateDomain.value])
const page = ref(Object.hasOwn(pageTitles, initialQuery.get('page')) ? initialQuery.get('page') : 'writing')
const returnTrail = ref([])
const previousPage = computed(() => returnTrail.value.at(-1)?.page || null)
const scrollPositions = new Map()
const initialSection = ref(initialQuery.get('section') || '全部')
const theme = ref(initialQuery.get('theme') === 'dark' ? 'dark' : 'light')
const motionPreference = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')
const systemReducedMotion = ref(motionPreference?.matches || false)
const previewReducedMotion = ref(false)
const reducedMotion = computed(() => systemReducedMotion.value || previewReducedMotion.value)
function syncMotionPreference(event) { systemReducedMotion.value = event.matches }
watch(reducedMotion, setPreviewReducedMotion, { immediate: true })
const state = ref(statusOptions.some(option => option.id === initialQuery.get('state')) ? initialQuery.get('state') : 'normal')
const focus = ref(false)
const dialog = ref(null)
const writingView = ref(null)
const readingView = ref(null)
const focusTrigger = ref(null)
const panelKind = ref(null)
const previewTools = ref(null)
const panelTitle = ref('')
const currentPerson = computed(() => people.find(person => panelTitle.value.startsWith(person.name)) || people[0])
const isExperience = computed(() => ['reading','journeys','identity','settings','components'].includes(page.value))
const isImmersive = computed(() => ['writing','reading','identity'].includes(page.value))
const isReader = computed(() => ['reading','journeys','identity'].includes(page.value))
const title = computed(() => pageTitles[page.value])
function navigate(target, section = '全部', returning = false) {
  if (!Object.hasOwn(pageTitles, target)) return
  const scroller = document.querySelector('#rd-main .rd-page-scroll, #rd-main .rd-paper-scroll')
  scrollPositions.set(page.value, scroller?.scrollTop || 0)
  if (!returning && (target !== page.value || section !== initialSection.value)) returnTrail.value.push({ page: page.value, section: initialSection.value, state: state.value })
  initialSection.value = section
  page.value = target; state.value = 'normal'; focus.value = false
  dialog.value?.close()
  if (previewTools.value) previewTools.value.open = false
  void nextTick(() => {
    document.getElementById('rd-main')?.focus({ preventScroll: true })
    const nextScroller = document.querySelector('#rd-main .rd-page-scroll, #rd-main .rd-paper-scroll')
    if (nextScroller) nextScroller.scrollTop = scrollPositions.get(target) || 0
  })
}
async function locateChapter(index) {
  navigate('writing')
  await nextTick()
  writingView.value?.locateChapter(index)
}
function goBack() {
  const destination = returnTrail.value.pop()
  if (!destination) return
  navigate(destination.page, destination.section, true)
  state.value = destination.state
}
function open(title, kind = 'detail', drawer = false, context = null) {
  if (kind === 'compare' && title.includes('版本')) kind = 'versions'
  panelTitle.value = title
  if (kind === 'compare') candidateDomain.value = title.includes('地图') ? 'map' : title.includes('结构') || title.includes('场景') ? 'outline' : title.includes('资料') || title.includes('世界') ? 'world' : 'writing'
  if (kind === 'compare') {
    candidateContext.value = context
    if (context?.id) {
      const prior = candidates[context.id]
      candidates[context.id] = { ...prior, destination: context.destination, status: context.status, title: context.title, source: context.source, original: context.original, suggestion: context.suggestion, stale: context.stale, review: prior?.review || '待审查' }
      candidateDomain.value = context.id
    }
  }
  dialog.value.open(title, kind, drawer)
}
function setCandidateStatus(value) { currentCandidate.value.status = value; candidateContext.value?.onStatus?.(value) }
function setCandidateStale(value) { currentCandidate.value.stale = value; currentCandidate.value.review = '待审查'; candidateContext.value?.onStale?.(value) }
function toggleChapters() {
  if (panelKind.value) { dialog.value.close(); writingView.value?.showChapters() }
  else writingView.value?.toggleChapters()
}
function toggleInspector() {
  if (panelKind.value) { dialog.value.close(); writingView.value?.showInspector() }
  else writingView.value?.toggleInspector()
}
function toggleFocus() {
  if (!focus.value) dialog.value?.close()
  focus.value = !focus.value
  void nextTick(() => focusTrigger.value?.focus())
}
function handleKeys(event) {
  if (event.key === 'Escape') {
    if (dialog.value?.isOpen) { dialog.value.close(); return }
    if (focus.value) toggleFocus()
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !document.querySelector('#redesign-root dialog[open]')) {
    event.preventDefault(); navigate('search')
  }
}
onMounted(() => {
  window.addEventListener('keydown', handleKeys)
  motionPreference?.addEventListener?.('change', syncMotionPreference)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeys)
  motionPreference?.removeEventListener?.('change', syncMotionPreference)
  cancelPreviewMotion()
  setPreviewReducedMotion(false)
})
const documentMenu = [...navigation.map(item => ({ action: item.id, label: item.title })), { action: 'settings', label: '账户与偏好' }]
const projectMenu = [{ action: 'projects', label: '查看全部作品' },{ action: 'import', label: '导入已有文稿' },{ action: 'settings', label: '作品偏好' }]
</script>
<template>
  <div class="rd-app" :data-theme="theme" :data-reduced-motion="String(reducedMotion)" :class="{ 'rd-immersive': isImmersive, 'rd-document-mode': page === 'writing', 'rd-focus-mode': focus, 'rd-reader-mode': isReader, 'rd-has-panel': panelKind, 'rd-compare-open': panelKind === 'compare' }">
    <a class="rd-skip-link" href="#rd-main">跳到主要内容</a>
    <aside class="rd-sidebar" :inert="isImmersive" aria-label="主要导航">
      <button class="rd-brand" @click="navigate('today')"><span class="rd-brand-mark">N</span><strong>NovelCraft<span>让想象，成为故事。</span></strong></button>
      <div class="rd-project-picker"><span class="rd-mini-cover">潮</span><div><strong>潮汐来信</strong><small>你的创作空间</small></div><ActionMenu menu-id="rd-project" label="作品菜单" trigger-text="⌄" :items="projectMenu" @select="item => navigate(item.action, item.action === 'settings' ? '作品偏好' : '全部')"/></div>
      <nav class="rd-navigation"><template v-for="item in navigation" :key="item.id"><span v-if="item.group" class="rd-nav-group">{{ item.group }}</span><button :aria-current="page === item.id ? 'page' : undefined" @click="navigate(item.id)"><span class="rd-navigation-icon" :class="'tone-' + item.color"><PreviewIcon :name="item.icon"/></span><span>{{ item.title }}</span><span v-if="item.id === 'world'" class="rd-nav-count">3</span><span v-if="item.id === 'writing' && page === 'writing'" class="rd-active-mark"/></button></template></nav>
      <div class="rd-sidebar-bottom"><button class="rd-profile-button" @click="navigate('settings')"><span class="rd-avatar small tone-blue">林</span><span>林间<small>把今天写进故事里</small></span><PreviewIcon name="settings"/></button></div>
    </aside>
    <div class="rd-workspace">
      <header class="rd-topbar">
        <div class="rd-breadcrumb">
          <template v-if="page === 'writing'">
            <div class="rd-document-menu"><ActionMenu menu-id="rd-document" label="浏览作品与工作区" trigger-text="潮汐来信" :items="documentMenu" @select="item => navigate(item.action)"/><PreviewIcon name="down"/></div>
            <span class="rd-document-status">工作稿</span>
          </template>
          <template v-else-if="isImmersive"><button class="rd-icon-button" aria-label="返回" @click="navigate(page === 'reading' ? 'journeys' : 'today')"><span class="rd-button-content"><PreviewIcon name="back"/></span></button><strong>{{ title }}</strong></template>
          <template v-else><div class="rd-mobile-workspace-menu"><ActionMenu menu-id="rd-mobile-workspaces" label="全部工作区" trigger-text="全部" :items="documentMenu" @select="item => navigate(item.action)"/></div><span class="rd-mini-cover">潮</span><strong>潮汐来信</strong></template>
        </div>
        <div v-if="page === 'writing'" class="rd-document-actions">
          <div class="rd-toolbar-group" aria-label="文档视图">
            <button v-if="!focus" class="rd-icon-button" aria-label="切换章节目录" title="章节目录" :aria-pressed="writingView?.chaptersVisible || false" @click="toggleChapters"><span class="rd-button-content"><PreviewIcon name="sidebar"/></span></button>
            <button class="rd-icon-button" aria-label="字体与阅读设置" title="正文排版" @click="open('正文排版', 'type')"><span class="rd-button-content"><PreviewIcon name="type"/></span></button>
            <button class="rd-icon-button" aria-label="版本历史" title="版本历史" @click="open('版本历史', 'versions', true)"><span class="rd-button-content"><PreviewIcon name="clock"/></span></button>
          </div>
          <div class="rd-toolbar-group" aria-label="写作工具">
            <button ref="focusTrigger" class="rd-icon-button" :aria-label="focus ? '退出专注' : '切换专注模式'" :title="focus ? '退出专注 · Esc' : '专注模式'" :aria-pressed="focus" @click="toggleFocus"><span class="rd-button-content"><PreviewIcon name="focus"/></span></button>
            <button v-if="!focus" class="rd-icon-button" aria-label="切换资料栏" title="本章资料" :aria-pressed="writingView?.inspectorVisible || false" @click="toggleInspector"><span class="rd-button-content"><PreviewIcon name="inspector"/></span></button>
          </div>
          <button v-if="!focus" class="rd-assistant-control" aria-label="写作伙伴" title="写作伙伴" :aria-pressed="panelKind === 'ai' || panelKind === 'compare'" @click="panelKind === 'ai' ? dialog.close() : open('写作伙伴', 'ai', true)"><PreviewIcon name="sparkles"/></button>
        </div>
        <div class="rd-topbar-actions">
          <button v-if="previousPage" class="rd-text-button rd-return-context" @click="goBack">返回{{ pageTitles[previousPage] }}</button>
          <template v-if="isReader && page !== 'identity'"><button class="rd-icon-button" aria-label="阅读设置" title="阅读设置" @click="navigate('settings', '外观')"><span class="rd-button-content"><PreviewIcon name="type"/></span></button><button v-if="page === 'reading'" class="rd-icon-button" aria-label="旅程回顾" title="旅程回顾" @click="readingView?.openRecap()"><span class="rd-button-content"><PreviewIcon name="clock"/></span></button></template>
          <button v-else-if="page !== 'writing'" class="rd-icon-button" title="查找 · ⌘ K" aria-label="打开查找" @click="navigate('search')"><span class="rd-button-content"><PreviewIcon name="search"/></span></button>
          <button class="rd-icon-button" :aria-label="theme === 'light' ? '切换到深色' : '切换到浅色'" @click="theme = theme === 'light' ? 'dark' : 'light'"><span class="rd-button-content"><PreviewIcon :name="theme === 'light' ? 'moon' : 'sun'"/></span></button>
        </div>
      </header>
      <main id="rd-main" tabindex="-1">
        <KeepAlive>
        <WritingPreview :key="'writing'" v-if="page === 'writing'" ref="writingView" :state="state" :focus="focus" :external-panel="Boolean(panelKind)" @open="open" @navigate="navigate"/>
        <JourneySetup v-else-if="page === 'journeys' && ['setup','source'].includes(initialSection)" key="journey-setup" :state="state" :initial-section="initialSection" @navigate="navigate" @open="open"/>
        <JourneyPreview v-else-if="page === 'journeys'" key="journeys" :state="state" :initial-section="initialSection" @navigate="navigate" @open="open"/>
        <IdentityPreview v-else-if="page === 'identity'" key="identity" :state="state" @navigate="navigate"/>
        <ImportPreview v-else-if="page === 'import'" key="import" :state="state" :initial-section="initialSection" @open="open" @navigate="navigate"/>
        <AssistantPreview v-else-if="page === 'assistant'" key="assistant" :task="assistantTask" :candidate="candidates.writing" @update:task="value => assistantTask = value" @open="open" @navigate="navigate"/>
        <ReaderPreview v-else-if="page === 'reading'" key="reading" ref="readingView" :state="state" @navigate="navigate"/>
        <WorldPreview v-else-if="page === 'world'" key="world" :state="state" :initial-section="initialSection" @open="open" @navigate="navigate"/>
        <SettingsPreview v-else-if="page === 'settings'" key="settings" :theme="theme" :state="state" :initial-section="initialSection" @theme="value => theme = value" @navigate="navigate" @open="open"/>
        <MapPreview v-else-if="page === 'map'" key="map" :state="state" @navigate="navigate" @open="open"/>
        <StructurePreview v-else-if="page === 'outline'" key="outline" :state="state" :initial-section="initialSection" @open="open" @navigate="navigate"/>
        <SearchPreview v-else-if="page === 'search'" key="search" :state="state" @navigate="navigate" @locate="locateChapter"/>
        <ExperiencePreview v-else-if="isExperience" :reduced-motion="reducedMotion" :system-reduced-motion="systemReducedMotion" @motion-reduced="value => previewReducedMotion = value" :key="page" :initial-section="initialSection" :page="page" :theme="theme" :state="state" @navigate="navigate" @open="open" @theme="value => theme = value" @state="value => state = value"/>
        <WorkspacePreview v-else :key="page" :initial-section="initialSection" :page="page" :state="state" @navigate="navigate" @open="open"/>
        </KeepAlive>
      </main>
      <nav v-if="!focus && page !== 'identity'" class="rd-mobile-nav" aria-label="快捷工作区"><button v-for="item in navigation.filter(item => ['writing','world','outline','journeys'].includes(item.id))" :key="item.id" :aria-current="page === item.id ? 'page' : undefined" @click="navigate(item.id)"><PreviewIcon :name="item.icon"/><span>{{ item.title }}</span></button></nav>
      <details ref="previewTools" class="rd-preview-tools">
        <summary><span class="rd-preview-dot"/>设计预览<PreviewIcon name="down"/></summary>
        <div class="rd-preview-popover"><strong>视觉与交互样板</strong><label>前往页面<select :value="page" aria-label="预览页面" @change="navigate($event.target.value)"><option v-for="(label, id) in pageTitles" :key="id" :value="id">{{ label }}</option></select></label><p>虚构内容，不连接真实作品。刷新恢复示例。</p><label>页面状态<select v-model="state" aria-label="页面演示状态"><option v-for="option in statusOptions" :key="option.id" :value="option.id">{{ option.label }}</option></select></label><button class="rd-button" @click="navigate('components')"><span class="rd-button-content">组件与动效<PreviewIcon name="forward"/></span></button></div>
      </details>
    </div>
    <PreviewDialog ref="dialog" @panel="value => panelKind = value" v-slot="{ kind, close }">
      <template v-if="kind === 'person'"><span class="rd-avatar profile" :class="`tone-${currentPerson.color}`">{{ currentPerson.initials }}</span><h3>{{ currentPerson.role }}</h3><p class="rd-dialog-lead">{{ currentPerson.note }}</p><div class="rd-settings-group"><div class="rd-detail-line"><span>眼前的目标</span><strong>找到海图背后的真相</strong></div><div class="rd-detail-line"><span>内心的牵挂</span><strong>那些未能说出口的告别</strong></div><div class="rd-detail-line"><span>关联章节</span><strong>第一章、第三章</strong></div></div><blockquote>有些人离开，是因为不知道怎样留下。</blockquote><span class="rd-badge tone-purple">2 条相关线索</span></template>
      <AssistantPreview v-else-if="kind === 'ai'" embedded :task="assistantTask" :candidate="candidates.writing" @update:task="value => assistantTask = value" @open="open" @navigate="navigate"/>
      <CandidateReview v-else-if="kind === 'compare'" :candidate="currentCandidate" @update:status="setCandidateStatus" @update:stale="setCandidateStale" @update:review="value => currentCandidate.review = value" @update:revision="value => currentCandidate.revision = value" @navigate="navigate" @close="close" @open="open"/>
      <template v-else-if="kind === 'adopted'"><PreviewNotice state="success" @action="open('版本历史', 'versions', true)"/><p>正式接入时，这里必须等待采用结果确认。当前只是视觉示例。</p></template>
      <template v-else-if="kind === 'rejected'"><span class="rd-color-icon tone-blue">✓</span><h3>保留原来的表达。</h3><p>建议已收起的反馈示例。正文不会因此变化。</p></template>
      <ConflictReview v-else-if="kind === 'conflicts'" @open="open" @navigate="navigate"/>
      <VersionReview v-else-if="kind === 'versions'" @open="open" @close="close"/>
      <template v-else-if="kind === 'new' || kind === 'task'"><p>从一个小小的念头开始，剩下的可以慢慢补全。</p><label class="rd-field">名称<input placeholder="写下一个名字或目标"/></label><label class="rd-field">随手记<textarea rows="4" placeholder="最想留下的那个念头…"/></label><div class="rd-component-row"><button class="rd-button" @click="close"><span class="rd-button-content">取消</span></button><button class="rd-button primary" @click="open('创建反馈示例', 'adopted')"><span class="rd-button-content">创建示例</span></button></div></template>
      <template v-else-if="kind === 'scene' || kind === 'outline'"><span class="rd-badge tone-blue">第一部 · 潮声</span><h3>在一场相遇里，埋下整个故事。</h3><p>林舟寻找答案，沈雁试图保守秘密。海图把他们带到同一个地点，灯塔的亮起迫使他们做出选择。</p><div class="rd-settings-group"><div v-for="item in [['开始','林舟错过最后一班渡船'],['转折','沈雁认出海图上的记号'],['结果','两人决定一起前往旧灯塔']]" :key="item[0]" class="rd-detail-line"><span>{{ item[0] }}</span><strong>{{ item[1] }}</strong></div></div><div class="rd-insight tone-orange"><strong>! 留意人物知识边界</strong><p>林舟此时还不知道沈雁与父亲的关系。让动作透露线索，而不是直接揭晓。</p></div></template>
      <template v-else-if="kind === 'type'"><label class="rd-field">字体<select><option>系统字体</option><option>衬线体示例</option></select></label><label class="rd-field">字号<input type="range" min="16" max="24" value="18"/></label><label class="rd-field">行间距<select><option>舒适</option><option>紧凑</option><option>宽松</option></select></label><p class="rd-muted">排版控件展示，暂不应用到正文。</p></template>
      <template v-else-if="kind === 'danger'"><span class="rd-color-icon tone-red">!</span><h3>重要的动作，值得再确认一次。</h3><p>正式产品会在这里说明影响范围及恢复方式。当前预览不会删除、退出或改变任何真实资料。</p><div class="rd-component-row"><button class="rd-button" @click="close"><span class="rd-button-content">保留并返回</span></button><button class="rd-button danger" @click="open('操作结果示例', 'notification')"><span class="rd-button-content">查看确认后反馈</span></button></div></template>
      <template v-else-if="kind === 'project'"><div class="rd-dialog-hero tone-blue"><span class="rd-eyebrow">一个新的世界</span><h3>{{ panelTitle }}</h3><p>每一页，都是你留下的想象。</p></div><p>设计预览共用《潮汐来信》的示例资料。其他封面用于展示作品档案的视觉层次。</p><button class="rd-button primary" @click="navigate('writing')"><span class="rd-button-content">进入示例写作台 →</span></button></template>
      <template v-else-if="kind === 'import'"><div class="rd-model-card"><span class="rd-color-icon tone-blue"><PreviewIcon name="project"/></span><div><h3>潮汐来信.txt</h3><p>示例文稿 · 6 章 · 7,828 字</p></div><span class="rd-badge tone-green">✓ 已识别</span></div><p>查看章节拆分与资料审阅的样式，不读取本地文件。</p><button class="rd-button primary" @click="open('审阅导入资料', 'compare', true)"><span class="rd-button-content">查看审阅面板 →</span></button></template>
      <template v-else-if="kind === 'journey' || kind === 'branch'"><div class="rd-dialog-hero tone-purple"><span class="rd-ai-spark"><PreviewIcon name="sparkles"/></span><h3>你的选择，会让故事不同。</h3><p>当海雾散去，你会成为留下的人，还是启航的人？</p></div><p>这里展示分支确认与故事开场，不调用模型生成。</p><button class="rd-button purple" @click="navigate('reading')"><span class="rd-button-content">进入示例故事 →</span></button></template>
      <template v-else-if="kind === 'connection' || kind === 'search-status'"><span class="rd-color-icon tone-blue"><PreviewIcon name="search"/></span><h3>清楚知道，当前能做什么。</h3><div class="rd-detail-line"><span>示例连接状态</span><strong>未连接真实服务</strong></div><div class="rd-detail-line"><span>示例内容</span><strong>本地内存中可用</strong></div><div class="rd-insight tone-orange"><strong>! 需要连接后才能继续</strong><p>正式接入时，失败会提供重试与配置入口。预览不会发送连接请求。</p></div></template>
      <template v-else-if="kind === 'notification'"><div class="rd-notice tone-green" role="status"><span class="rd-notice-icon">✓</span><div><strong>示例操作已完成</strong><p>短暂反馈，不打断正在进行的创作。</p></div></div><p>这是通知组件的静态样例，没有执行业务操作。</p></template>
      <template v-else-if="kind === 'states'"><PreviewNotice state="error" @action="open('保存成功反馈', 'adopted')"/><PreviewNotice state="conflict" @action="open('版本比较', 'compare')"/></template>
      <template v-else-if="kind === 'layers'"><label v-for="item in ['地点与名称','人物足迹','航线与关联','地形底图']" :key="item" class="rd-setting-row"><span>{{ item }}</span><input type="checkbox" checked/></label><p class="rd-muted">图层控件示例，当前地图为静态示意图。</p></template>
      <template v-else-if="kind === 'recap'"><span class="rd-badge tone-teal">旅程回顾</span><div v-for="item in ['你抵达了白沙港','一个年轻人认出了你的海图','灯塔亮起，你决定留下来']" :key="item" class="rd-version-row"><span class="rd-check">✓</span><strong>{{ item }}</strong></div></template>
      <template v-else><span class="rd-badge tone-teal">潮汐来信 · 相关资料</span><h3>{{ panelTitle }}</h3><p class="rd-dialog-lead">{{ people.find(person => person.name === panelTitle)?.note || '三年前的那场海难之后，白沙港的灯塔就再也没有亮起。沈雁是最后一个从灯塔回来的人，而林舟的父亲从此失去了踪迹。' }}</p><blockquote>雾从海面升起的时候，灯塔已经熄灭了三年。</blockquote><div class="rd-detail-line"><span>来源</span><strong>第一章 · 雾中的灯塔</strong></div><div class="rd-detail-line"><span>相关人物</span><strong>林舟、沈雁</strong></div><span class="rd-badge tone-purple">✦ 与当前场景相关</span></template>
    </PreviewDialog>
  </div>
</template>
