<script setup>
import { computed, ref, watch } from 'vue'
import PreviewIcon from './PreviewIcon.vue'

const props = defineProps({ kind: { type: String, default: '需要决定' } })
const emit = defineEmits(['open', 'navigate'])

function buildItems(kind) {
  if (kind === '关系') return [
    { id: 'relation-lin-shen', left: '林舟', relation: '与', right: '沈雁', proposal: '共同守着灯塔熄灭的秘密', quote: '他的手指收紧了一瞬，像是认出了什么。', source: '第三章 · 潮汐之间', stale: false, decision: 'undecided' },
    { id: 'relation-harbor-lighthouse', left: '白沙港', relation: '通向', right: '旧灯塔', proposal: '道路只在落潮时出现', quote: '湿漉漉的石阶一直伸进海里。', source: '第一章 · 雾中的灯塔', stale: true, decision: 'undecided' },
  ]
  if (kind === '别名') return [
    { id: 'alias-shen-keeper', target: '沈雁', alias: '守塔人', aliasType: '称号', proposal: '附着到已有对象“沈雁”', quote: '也守着关于那场海难的最后一个秘密。', source: '世界资料 · 人物整理', stale: false, decision: 'undecided' },
    { id: 'alias-harbor-old', target: '白沙港', alias: '旧港', aliasType: '简称', proposal: '附着到已有对象“白沙港”', quote: '信封上的邮戳属于一个早已消失的港口。', source: '第二章 · 一封迟到的信', stale: true, decision: 'undecided' },
  ]
  return [
    { id: 'candidate-shen', name: '沈雁', type: '人物', action: '补充人物说明', proposal: '灯塔守望者，知道海难留下的最后一个秘密。', quote: '守着一座不再亮起的灯塔，也守着关于那场海难的最后一个秘密。', source: '第一部 · 第三章', stale: false, decision: 'undecided' },
    { id: 'candidate-harbor', name: '白沙港', type: '地点', action: '补充地点限制', proposal: '每逢大潮，海面会浮出一条通向旧灯塔的石路。', quote: '三面环山的小港口。每逢大潮，海面会浮出一条通向旧灯塔的石路。', source: '第一部 · 第三章', stale: true, decision: 'undecided' },
    { id: 'candidate-map', name: '北境海图', type: '物品', action: '建立资料', proposal: '一张会随潮汐改变的海图，银色标记只在月光下显现。', quote: '纸的边缘已经起了毛，靠近北方的地方有一圈淡淡的水渍。', source: '第一部 · 第三章', stale: false, decision: 'confirmed' },
  ]
}

const items = ref(buildItems(props.kind))
const query = ref('')
const selectedIds = ref(new Set())
const feedback = ref('')

watch(() => props.kind, kind => {
  items.value = buildItems(kind)
  query.value = ''
  selectedIds.value = new Set()
  feedback.value = ''
})

const visibleItems = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return items.value.filter(item => !needle || `${item.name || ''}${item.left || ''}${item.right || ''}${item.target || ''}${item.alias || ''}${item.proposal}${item.quote}`.toLocaleLowerCase().includes(needle))
})
const pendingItems = computed(() => visibleItems.value.filter(item => item.decision === 'undecided'))
const handledItems = computed(() => visibleItems.value.filter(item => item.decision !== 'undecided'))
const selectedCount = computed(() => selectedIds.value.size)
const allVisibleSelected = computed(() => pendingItems.value.length > 0 && pendingItems.value.every(item => selectedIds.value.has(item.id)))
const selectedHasStale = computed(() => pendingItems.value.some(item => selectedIds.value.has(item.id) && item.stale))
const title = computed(() => props.kind === '需要决定' ? '逐项看清，再决定资料的去向。' : props.kind === '关系' ? '关系也需要来源与判断。' : '别名附着在对象上，不另起一个名字。')
const description = computed(() => props.kind === '需要决定' ? '候选资料来自同一段故事，确认后才会进入本次世界资料。' : props.kind === '关系' ? '先确认人物与地点之间的表达，再决定是否保留这条关系。' : '每个别名都有明确归属、分类和来源，确认后仍属于原对象。')

function toggle(id, checked) {
  const next = new Set(selectedIds.value)
  checked ? next.add(id) : next.delete(id)
  selectedIds.value = next
}
function toggleAll(checked) {
  selectedIds.value = checked ? new Set(pendingItems.value.map(item => item.id)) : new Set()
}
function decide(ids, decision) {
  const chosen = new Set(ids)
  if (decision === 'confirmed' && items.value.some(item => chosen.has(item.id) && item.stale)) {
    feedback.value = '有资料的来源已经过期，暂时不能确认；可以逐项拒绝或重新查看来源。'
    return
  }
  items.value = items.value.map(item => chosen.has(item.id) ? { ...item, decision } : item)
  selectedIds.value = new Set()
  feedback.value = decision === 'confirmed' ? `已确认 ${ids.length} 项资料 · 演示` : `已拒绝 ${ids.length} 项资料 · 演示`
}
function itemName(item) { return item.name || (item.left ? `${item.left} ${item.relation} ${item.right}` : `${item.alias} → ${item.target}`) }
function openCompare(item) {
  emit('open', `世界资料 · ${itemName(item)}`, 'compare', true, {
    destination: '世界资料', id: `world-${item.id}`, title: itemName(item), source: item.source,
    original: item.quote, suggestion: item.proposal, stale: item.stale,
    status: item.decision === 'confirmed' ? 'adopted' : item.decision === 'rejected' ? 'rejected' : 'pending',
    onStatus(status) {
      if (status === 'pending') items.value = items.value.map(value => value.id === item.id ? { ...value, decision: 'undecided' } : value)
      else decide([item.id], status === 'adopted' ? 'confirmed' : 'rejected')
    },
    onStale(stale) { items.value = items.value.map(value => value.id === item.id ? { ...value, stale } : value) },
  })
}
</script>

<template>
  <section class="rd-world-review" :aria-label="`${props.kind}审阅`">
    <header class="rd-world-review-heading">
      <div><span class="rd-eyebrow">世界资料 / {{ props.kind }} · 本次预览</span><h2>{{ title }}</h2><p>{{ description }}</p></div>
      <span class="rd-badge" :class="pendingItems.length ? 'tone-orange' : 'tone-green'">待决定 {{ pendingItems.length }} 项</span>
    </header>

    <div class="rd-world-review-filter">
      <label class="rd-search compact"><PreviewIcon name="search" /><input v-model="query" type="search" :aria-label="`搜索${props.kind}待处理项`" :placeholder="props.kind === '别名' ? '搜索别名或对象' : '搜索人物、地点或来源'" /></label>
      <span class="rd-muted">当前筛选 {{ visibleItems.length }} 项</span>
    </div>

    <template v-if="pendingItems.length">
      <div class="rd-world-review-bulk">
        <label><input type="checkbox" :checked="allVisibleSelected" aria-label="全选当前待处理项" @change="toggleAll($event.target.checked)" />全选当前筛选</label>
        <span v-if="selectedCount" class="rd-badge tone-blue">已选 {{ selectedCount }} 项</span>
        <button class="rd-button primary" type="button" :disabled="!selectedCount || selectedHasStale" @click="decide([...selectedIds], 'confirmed')">批量确认</button>
        <button class="rd-button" type="button" :disabled="!selectedCount" @click="decide([...selectedIds], 'rejected')">批量拒绝</button>
      </div>
      <p v-if="selectedHasStale" class="rd-inline-notice tone-orange" role="alert">! 已选资料含过期来源，批量确认已暂停；批量拒绝仍可执行。</p>
    </template>

    <section v-if="pendingItems.length" class="rd-world-review-bucket" aria-labelledby="world-review-pending-title">
      <div class="rd-section-title"><h3 id="world-review-pending-title">等待你决定</h3><span class="rd-muted">逐项确认或拒绝</span></div>
      <article v-for="item in pendingItems" :key="item.id" class="rd-world-review-row" :class="{ 'is-selected': selectedIds.has(item.id), 'is-stale': item.stale }">
        <input type="checkbox" :aria-label="`选择待处理项 ${itemName(item)}`" :checked="selectedIds.has(item.id)" @change="toggle(item.id, $event.target.checked)" />
        <div class="rd-world-review-row-copy">
          <div class="rd-world-review-row-title">
            <strong v-if="props.kind === '需要决定'">{{ item.name }}</strong>
            <strong v-else-if="props.kind === '关系'">{{ item.left }} {{ item.relation }} {{ item.right }}</strong>
            <strong v-else>{{ item.alias }}</strong>
            <span v-if="props.kind === '需要决定'" class="rd-badge tone-blue">{{ item.type }} · {{ item.action }}</span>
            <span v-else-if="props.kind === '关系'" class="rd-badge tone-purple">关系候选</span>
            <span v-else class="rd-badge tone-teal">归属 {{ item.target }} · 已有对象</span>
            <span v-if="item.stale" class="rd-badge tone-red">来源已过期</span>
          </div>
          <p>{{ item.proposal }}</p>
          <blockquote>“{{ item.quote }}”</blockquote>
          <small>来源：{{ item.source }} · {{ item.stale ? '需要重新确认' : '可回看' }}</small>
        </div>
        <div class="rd-world-review-row-actions">
          <button class="rd-text-button" type="button" @click="openCompare(item)">查看差异 <PreviewIcon name="forward" /></button>
          <button class="rd-button primary" type="button" :disabled="item.stale" @click="decide([item.id], 'confirmed')">确认这项</button>
          <button class="rd-button" type="button" @click="decide([item.id], 'rejected')">拒绝这项</button>
        </div>
      </article>
    </section>
    <section v-else class="rd-world-review-empty rd-empty"><span class="rd-empty-symbol"><PreviewIcon name="check" /></span><h3>当前筛选没有待决定项</h3><p>已确认或已拒绝的资料仍保留在下方历史中。</p></section>

    <section v-if="handledItems.length" class="rd-world-review-bucket is-handled" aria-labelledby="world-review-handled-title">
      <div class="rd-section-title"><h3 id="world-review-handled-title">已处理</h3><span class="rd-muted">与待决定项目分开显示</span></div>
      <div v-for="item in handledItems" :key="item.id" class="rd-world-review-handled-row">
        <div><strong v-if="props.kind === '需要决定'">{{ item.name }}</strong><strong v-else-if="props.kind === '关系'">{{ item.left }} {{ item.relation }} {{ item.right }}</strong><strong v-else>{{ item.alias }} · {{ item.target }}</strong><small>{{ item.source }}</small></div>
        <span class="rd-badge" :class="item.decision === 'confirmed' ? 'tone-green' : 'tone-teal'">{{ item.decision === 'confirmed' ? '已确认' : '已拒绝' }}</span><button class="rd-text-button" type="button" @click="openCompare(item)">重开差异</button>
      </div>
    </section>

    <p v-if="feedback" class="rd-inline-notice" :class="feedback.includes('过期') ? 'tone-orange' : 'tone-green'" role="status">{{ feedback }}</p>
    <p class="rd-demonstration">本地审阅示例；确认、拒绝和批量范围不会写入世界资料。需要查看正文差异时，统一打开主壳“审阅世界资料”比较面板。</p>
  </section>
</template>
