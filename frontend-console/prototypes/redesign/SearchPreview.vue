<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import { chapters, people } from './data.js'
import { vReveal } from './motion.js'
const props = defineProps({ state: { type: String, default: 'normal' } })
const emit = defineEmits(['navigate', 'locate'])
const query = ref('灯塔')
const category = ref('全部')
const version = ref('工作稿与正式正文')
const mode = ref('原词查找')
const perspective = ref('作者视角')
const chapterFrom = ref(1)
const chapterTo = ref(6)
const sourceState = ref('可用')
const selected = ref(null)
const detail = ref(null)
const pinned = ref([])
const repair = ref('待处理')
watch(() => props.state, () => { repair.value = '待处理' })
let trigger = null
const results = computed(() => {
  const term = query.value.trim()
  if (props.state === 'empty') return []
  return [
    ...chapters.map((chapter, index) => ({ name: chapter.title, text: chapter.text, type: '正文', version: index < 2 ? '正式正文' : '工作稿', index, source: `第${index + 1}章 · ${chapter.title}` })),
    ...people.map(person => ({ name: person.name, text: person.note, type: person.type, index: 2, source: '人物与世界 · 已确认资料' })),
    { name: '码头初遇', text: '灯塔在落潮前亮起，沈雁认出海图，决定带林舟离开码头。', type: '场景', index: 2, source: '第三章 · 当前场景' },
  ].filter(item => (!term || `${item.name}${item.text}`.includes(term)) && (category.value === '全部' || category.value === item.type) && (version.value !== '仅正式正文' || item.type !== '正文' || item.version === '正式正文') && item.index + 1 >= chapterFrom.value && item.index + 1 <= chapterTo.value)
})
async function showSource(item, event) {
  trigger = event.currentTarget
  selected.value = item
  sourceState.value = props.state === 'conflict' ? '已过期' : '可用'
  await nextTick()
  detail.value?.focus({ preventScroll: true })
}
function closeSource() { selected.value = null; trigger?.focus({ preventScroll: true }) }
function pinSource() { if (!pinned.value.some(item => item.name === selected.value.name)) pinned.value.push(selected.value) }
</script>
<template>
  <div class="rd-page-scroll"><div class="rd-page-inner rd-search-workspace">
    <header class="rd-page-heading"><div><span class="rd-eyebrow">潮汐来信 / 资料查找</span><h1>让记忆，有迹可循。</h1><p>从原文、人物和场景中，找回你需要的那一刻。</p></div><span class="rd-badge tone-blue">⌘ K</span></header>
    <form class="rd-search-form" @submit.prevent="selected = null"><PreviewIcon name="search"/><label class="rd-sr-only" for="rd-search-query">查找关键词</label><input id="rd-search-query" v-model="query" placeholder="人物、地点，或一句没写完的话…"/><button class="rd-button primary"><span class="rd-button-content">查找</span></button></form>
    <div class="rd-local-toolbar"><label class="rd-field">查找方式<select v-model="mode"><option>原词查找</option><option>按意思查找 · 演示</option></select></label><label class="rd-field">正文范围<select v-model="version"><option>工作稿与正式正文</option><option>仅正式正文</option></select></label><details class="rd-search-advanced"><summary>更多范围</summary><div class="rd-form-grid"><label class="rd-field">视角<select v-model="perspective"><option>作者视角</option><option>林舟已知的资料</option><option>沈雁已知的资料</option></select></label><label class="rd-field">截至场景<select><option>码头上的初次相遇</option><option>雾中灯塔</option></select></label><label class="rd-field">起始章<input v-model.number="chapterFrom" type="number" min="1" max="6"/></label><label class="rd-field">结束章<input v-model.number="chapterTo" type="number" min="1" max="6"/></label></div><p class="rd-demonstration">高级范围为设计演示；未执行人物知识边界检查。</p></details></div>
    <div class="rd-filter-pills"><button v-for="item in ['全部','正文','人物','地点','场景']" :key="item" :aria-pressed="category === item" @click="category = item">{{ item }}</button></div>
    <p v-if="chapterFrom > chapterTo" class="rd-inline-notice tone-orange" role="alert">起始章不能晚于结束章。调整范围后继续查找。</p>
    <div v-else-if="state === 'loading'" class="rd-dense-empty" role="status"><span class="rd-spinner"/> 正在查找示例资料…</div>
    <div v-else-if="state === 'error' && repair !== '已完成'" class="rd-inline-notice tone-orange"><strong>! 部分资料暂时无法查找</strong><p>正文仍然可以阅读。稍后重试整理，或缩小到原词查找。</p><button class="rd-button" @click="repair = repair === '待处理' ? '修复中' : '已完成'">{{ repair === '待处理' ? '查看修复示例' : repair === '修复中' ? '演示修复完成' : '✓ 修复完成 · 演示' }}</button></div>
    <div v-else class="rd-search-layout" :class="{ 'has-source': selected }">
      <section aria-label="查找结果"><div class="rd-section-title"><h2>{{ results.length }} 条相关资料</h2><span class="rd-muted">{{ mode }} · 示例</span></div><div v-if="!results.length" class="rd-dense-empty"><PreviewIcon name="search"/><h2>还没有找到这条线索</h2><p>试试“灯塔”“林舟”，或缩小关键词。</p><button class="rd-button" @click="query = ''; category = '全部'">查看全部示例资料</button></div>
        <button v-for="item in results" :key="item.name" class="rd-search-result-item" :aria-pressed="selected?.name === item.name" @click="showSource(item, $event)"><span class="rd-badge" :class="item.type === '正文' ? 'tone-blue' : 'tone-teal'">{{ item.type }}</span><h3>{{ item.name }}</h3><p>{{ item.text }}</p><small>{{ item.source }} {{ item.version }} <span>查看来源 →</span></small></button>
      </section>
      <aside v-if="selected" ref="detail" v-reveal="selected.name" class="rd-detail-surface rd-source-detail" tabindex="-1" aria-label="来源预览" @keydown.esc.stop="closeSource"><div class="rd-detail-heading"><div><span class="rd-eyebrow">来源预览</span><h2>{{ selected.name }}</h2></div><button class="rd-icon-button" aria-label="关闭来源预览" @click="closeSource"><PreviewIcon name="close"/></button></div><span class="rd-badge tone-blue">{{ selected.source }}</span><blockquote>{{ selected.text }}</blockquote><label class="rd-field">来源状态演示<select v-model="sourceState"><option>可用</option><option>已过期</option><option>不可用</option></select></label><div v-if="sourceState !== '可用'" class="rd-inline-notice tone-orange"><strong>! {{ sourceState === '已过期' ? '原文已有新修改' : '无法读取这份来源' }}</strong><p>当前片段仅供回看，暂时不能作为新的引用。请重新定位原文。</p><button class="rd-text-button" @click="sourceState = '可用'">演示重新读取 →</button></div><div class="rd-local-toolbar"><button class="rd-button primary" :disabled="sourceState === '不可用'" @click="emit('locate', selected.index)"><span class="rd-button-content">定位到原章</span></button><button class="rd-button" :disabled="sourceState !== '可用' || pinned.some(item => item.name === selected.name)" @click="pinSource">{{ pinned.some(item => item.name === selected.name) ? '✓ 已钉选' : '钉选资料' }}</button></div><p class="rd-demonstration">引用与采用不同。这里只保留本次预览的钉选，不改变正文。</p></aside>
    </div>
    <section v-if="pinned.length" class="rd-detail-surface"><div class="rd-section-title"><h2>本次钉选</h2><button class="rd-text-button" @click="pinned = []">清除钉选</button></div><button v-for="item in pinned" :key="item.name" class="rd-source-link" @click="showSource(item, $event)">{{ item.name }} →</button></section>
  </div></div>
</template>
<style>
#redesign-root .rd-search-workspace{max-width:1150px}#redesign-root .rd-search-form{display:flex;gap:14px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:12px 16px;box-shadow:0 5px 20px #14233a06}#redesign-root .rd-search-form input{flex:1;border:0;background:transparent;font-size:18px;padding:8px;min-width:0}#redesign-root .rd-search-layout{display:grid;grid-template-columns:minmax(0,1fr);gap:28px;margin-top:25px}#redesign-root .rd-search-layout.has-source{grid-template-columns:minmax(0,1fr) minmax(260px,.8fr)}#redesign-root .rd-search-result-item{display:block;width:100%;padding:22px 0;border-bottom:1px solid var(--line);border-radius:8px}#redesign-root .rd-search-result-item:hover,#redesign-root .rd-search-result-item[aria-pressed='true']{background:var(--blue-bg)}#redesign-root .rd-search-result-item h3{font-size:18px;margin:12px 0 7px}#redesign-root .rd-search-result-item p{font-size:14px;line-height:1.9;color:var(--muted)}#redesign-root .rd-search-result-item small{display:flex;justify-content:space-between;margin-top:15px;color:var(--muted)}#redesign-root .rd-search-result-item small span{color:var(--blue)}#redesign-root .rd-source-detail{position:sticky;top:20px}#redesign-root .rd-source-detail blockquote{font-size:17px;line-height:2;margin:25px 0;padding-left:16px;border-left:3px solid var(--blue)}#redesign-root .rd-search-advanced summary{padding:12px;color:var(--blue);cursor:pointer}#redesign-root .rd-search-advanced[open]{flex-basis:100%;padding:15px;background:var(--surface);border-radius:12px}@media(max-width:800px){#redesign-root .rd-search-layout.has-source{grid-template-columns:1fr}#redesign-root .rd-source-detail{position:static;grid-row:1}#redesign-root .rd-search-form{padding:8px}#redesign-root .rd-search-form input{font-size:16px}}
</style>
