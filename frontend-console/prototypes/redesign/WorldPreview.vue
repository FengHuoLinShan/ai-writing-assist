<script setup>
import { computed, reactive, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import { vReveal } from './motion.js'
import { people } from './data.js'
import WorldDetail from './WorldDetail.vue'
import WorldReview from './WorldReview.vue'
import WorldConnections from './WorldConnections.vue'
import WorldImport from './WorldImport.vue'

const props = defineProps({
  state: { type: String, default: 'normal' },
  initialSection: { type: String, default: '全部' },
})
const emit = defineEmits(['open', 'navigate'])

const sections = ['全部', '人物', '地点', '物品', '规则', '组织', '需要决定', '关系', '别名', '世界书']
const tab = ref(sections.includes(props.initialSection) ? props.initialSection : '全部')
const query = ref('')
const view = ref('list')
const selected = ref(null)
const relationMode = ref('graph')
const detailDrafts = reactive({})
const retried = ref(false)

watch(() => props.initialSection, value => {
  if (sections.includes(value)) {
    tab.value = value
  }
})
watch(() => props.state, () => { retried.value = false })

const entries = computed(() => people.map((person, index) => ({
  ...person,
  id: person.name,
  source: index < 2 ? '第一部 · 第三章' : '潮汐来信 · 世界资料',
})))
const filteredEntries = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return entries.value.filter(entry => {
    const matchesTab = tab.value === '全部' || ['需要决定', '关系', '别名'].includes(tab.value) || entry.type === tab.value
    const haystack = `${entry.name}${entry.role}${entry.note}${entry.type}`.toLocaleLowerCase()
    return matchesTab && (!needle || haystack.includes(needle))
  })
})
const selectedEntry = computed(() => entries.value.find(entry => entry.id === selected.value))
const showingStaleData = computed(() => props.state === 'error' && !retried.value)

function chooseSection(value) {
  tab.value = value
  selected.value = null
  if (value === '关系') relationMode.value = 'graph'
}
function selectEntry(entry) {
  selected.value = entry.id
}
function retry() {
  retried.value = true
}
function saveDetailDraft(value) {
  if (!value?.id) return
  detailDrafts[value.id] = { role: value.role, note: value.note }
}
const detailEntry = computed(() => {
  if (!selectedEntry.value) return null
  return { ...selectedEntry.value, ...(detailDrafts[selectedEntry.value.id] || {}) }
})
</script>

<template>
  <div class="rd-page-scroll">
    <div class="rd-page-inner rd-world-preview">
      <header class="rd-page-heading">
        <div>
          <span class="rd-eyebrow">潮汐来信 / 世界资料</span>
          <h1>让故事里的每一个名字，都有来处。</h1>
          <p>人物、地点与规则集中在这里，写作时随时回来查看。</p>
        </div>
        <button class="rd-button primary" type="button" @click="emit('open', '添加世界资料', 'new')">
          <span class="rd-button-content"><PreviewIcon name="plus" />添加资料</span>
        </button>
      </header>

      <div v-if="state === 'loading'" class="rd-world-loading" role="status" aria-live="polite">
        <span class="rd-spinner" />正在整理世界资料…<small>示例加载状态</small>
      </div>
      <section v-else-if="state === 'empty'" class="rd-world-empty rd-empty">
        <span class="rd-empty-symbol"><PreviewIcon name="world" /></span>
        <h2>世界还没有留下资料</h2>
        <p>从一个人物、一处地点，或一条故事规则开始。</p>
        <button class="rd-button primary" type="button" @click="emit('open', '添加世界资料', 'new')">添加第一项资料</button>
        <small>空态演示 · 不会写入真实作品</small>
      </section>
      <template v-else>
        <div v-if="showingStaleData" class="rd-inline-notice tone-orange" role="alert">
          <strong>! 最新资料暂时无法读取</strong>
          <p>下面保留上次示例内容。你的筛选和当前选择仍然可用，恢复后再试一次。</p>
          <button class="rd-button" type="button" @click="retry">重试读取示例</button>
        </div>
        <div v-else-if="props.state === 'error' && retried" class="rd-inline-notice tone-green" role="status">
          <strong>✓ 示例资料已重新载入</strong>
          <p>这是本地预览反馈，没有请求服务或修改作品。</p>
        </div>

        <div class="rd-world-controls">
          <nav class="rd-filter-pills" aria-label="世界资料分类">
            <button v-for="section in sections" :key="section" type="button" :aria-pressed="tab === section" @click="chooseSection(section)">
              {{ section }}<span v-if="section === '需要决定'" class="rd-count tone-orange">3</span>
            </button>
          </nav>
          <div class="rd-world-actions">
            <label class="rd-search compact">
              <PreviewIcon name="search" />
              <input v-model="query" type="search" placeholder="搜索资料" aria-label="搜索世界资料" />
            </label>
            <div class="rd-view-toggle" aria-label="资料密度">
              <button type="button" aria-label="列表视图" :aria-pressed="view === 'list'" @click="view = 'list'"><PreviewIcon name="sidebar" /></button>
              <button type="button" aria-label="卡片视图" :aria-pressed="view === 'cards'" @click="view = 'cards'"><PreviewIcon name="world" /></button>
            </div>
          </div>
        </div>

        <div v-if="tab === '关系'" class="rd-world-subview-toggle" role="tablist" aria-label="关系视图"><button :aria-selected="relationMode === 'graph'" @click="relationMode = 'graph'">关系图谱</button><button :aria-selected="relationMode === 'review'" @click="relationMode = 'review'">关系审阅</button></div>
        <KeepAlive>
        <WorldConnections v-if="tab === '关系' && relationMode === 'graph'" @navigate="(...args) => emit('navigate', ...args)" />
        <WorldReview v-else-if="tab === '关系' || ['需要决定', '别名'].includes(tab)" :key="tab" :kind="tab" @open="(...args) => emit('open', ...args)" @navigate="(...args) => emit('navigate', ...args)" />
        <WorldImport @recovered="retried = true" v-else-if="tab === '世界书'" :state="state" :initial-section="initialSection" @open="(...args) => emit('open', ...args)" @navigate="(...args) => emit('navigate', ...args)" />
        </KeepAlive>

        <div v-if="!['关系', '需要决定', '别名', '世界书'].includes(tab) && filteredEntries.length" class="rd-world-results" :class="`is-${view}`" v-reveal="tab">
          <button v-for="entry in filteredEntries" :key="entry.id" class="rd-world-entry" :class="{ selected: selected === entry.id }" type="button" :aria-pressed="selected === entry.id" @click="selectEntry(entry)">
            <span class="rd-world-entry-mark" :class="`tone-${entry.color}`">
              <span v-if="entry.type === '人物'" class="rd-card-letter">{{ entry.initials }}</span>
              <PreviewIcon v-else :name="entry.type === '地点' ? 'map' : entry.type === '物品' ? 'project' : entry.type === '规则' ? 'outline' : 'world'" />
            </span>
            <span class="rd-world-entry-copy">
              <strong>{{ entry.name }}</strong>
              <small>{{ entry.type }} · {{ entry.role }}</small>
              <span>{{ entry.note }}</span>
            </span>
            <span class="rd-world-entry-meta"><small>{{ entry.source }}</small><PreviewIcon name="forward" /></span>
          </button>
        </div>
        <section v-else-if="!['关系', '需要决定', '别名', '世界书'].includes(tab)" class="rd-world-empty rd-empty" aria-live="polite">
          <span class="rd-empty-symbol"><PreviewIcon name="search" /></span>
          <h2>没有找到匹配的资料</h2>
          <p>试试更短的关键词，或换一个分类。</p>
          <button class="rd-text-button" type="button" @click="query = ''; chooseSection('全部')">清除筛选 <PreviewIcon name="forward" /></button>
        </section>

        <WorldDetail v-if="detailEntry" :entry="detailEntry" @close="selected = null" @update="saveDetailDraft" @navigate="(...args) => emit('navigate', ...args)" />
      </template>
    </div>
  </div>
</template>

<style src="./world-preview.css"></style>
