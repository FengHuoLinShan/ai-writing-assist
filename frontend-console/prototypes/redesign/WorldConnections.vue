<script setup>
import { computed, ref } from 'vue'
import PreviewIcon from './PreviewIcon.vue'
import { people } from './data.js'

const emit = defineEmits(['navigate'])
const selectedName = ref('林舟')
const nodes = [
  { name: '林舟', x: 180, y: 140, tone: 'blue', role: '追寻真相的人' },
  { name: '沈雁', x: 420, y: 75, tone: 'purple', role: '灯塔守望者' },
  { name: '白沙港', x: 420, y: 220, tone: 'teal', role: '故事开始的地方' },
  { name: '北境海图', x: 675, y: 140, tone: 'orange', role: '一条不曾存在的航线' },
]
const links = [
  { from: '林舟', to: '沈雁', label: '共同的秘密' },
  { from: '林舟', to: '白沙港', label: '重返故乡' },
  { from: '沈雁', to: '北境海图', label: '知道它的来处' },
]
const selected = computed(() => people.find(person => person.name === selectedName.value) || people[0])
const related = computed(() => links.filter(link => link.from === selectedName.value || link.to === selectedName.value).map(link => ({ ...link, other: link.from === selectedName.value ? link.to : link.from })))
function select(name) { selectedName.value = name }
function position(name) { return nodes.find(node => node.name === name) }
</script>

<template>
  <section class="rd-world-connections" aria-label="世界关系与知识图谱">
    <header class="rd-world-review-heading">
      <div><span class="rd-eyebrow">世界资料 / 关系 · 本次预览</span><h2>从一个对象，看见它与故事的牵连。</h2><p>图形只帮助你看方向；对象列表提供完整的键盘与触摸路径。</p></div>
      <span class="rd-badge tone-blue">{{ nodes.length }} 个对象 · {{ links.length }} 条关系</span>
    </header>
    <div class="rd-world-graph-layout">
      <div class="rd-world-graph-wrap">
        <svg class="rd-world-graph" viewBox="0 0 800 300" role="img" aria-label="林舟、沈雁、白沙港和北境海图之间的关系示意">
          <g class="rd-world-graph-links" aria-hidden="true"><g v-for="link in links" :key="`${link.from}-${link.to}`"><line :x1="position(link.from).x" :y1="position(link.from).y" :x2="position(link.to).x" :y2="position(link.to).y" /><text :x="(position(link.from).x + position(link.to).x) / 2" :y="(position(link.from).y + position(link.to).y) / 2 - 7">{{ link.label }}</text></g></g>
          <g v-for="node in nodes" :key="node.name" class="rd-world-graph-node" :class="[`tone-${node.tone}`, { selected: selectedName === node.name }]" aria-hidden="true"><circle :cx="node.x" :cy="node.y" :r="selectedName === node.name ? 27 : 21" /><text :x="node.x" :y="node.y + 5">{{ node.name.slice(0, 1) }}</text></g>
        </svg>
        <p class="rd-demonstration">关系图为示意辅助，不需要拖动或缩放；选择对象请使用下方列表。</p>
      </div>
      <div class="rd-world-node-list" role="list" aria-label="可选择的关系对象">
        <button v-for="node in nodes" :key="node.name" class="rd-world-node-button" :class="{ selected: selectedName === node.name }" type="button" :aria-pressed="selectedName === node.name" @click="select(node.name)">
          <span class="rd-small-icon" :class="`tone-${node.tone}`"><span>{{ node.name.slice(0, 1) }}</span></span><span><strong>{{ node.name }}</strong><small>{{ node.role }}</small></span><PreviewIcon name="forward" />
        </button>
      </div>
    </div>
    <section class="rd-world-connection-detail" aria-label="选中对象关系详情">
      <div class="rd-detail-heading"><div><span class="rd-eyebrow">已选择对象 · {{ selected.type }}</span><h2>{{ selected.name }}</h2></div><span class="rd-badge" :class="`tone-${selected.color}`">{{ selected.role }}</span></div>
      <p>{{ selected.note }}</p>
      <div class="rd-world-related-list"><div v-for="item in related" :key="`${item.other}-${item.label}`"><span>关联对象</span><strong>{{ item.other }}</strong><small>{{ item.label }} · 来源：第三章 · 潮汐之间</small></div></div>
      <div class="rd-local-toolbar"><button class="rd-button" type="button" @click="emit('navigate', selected.type === '地点' ? 'map' : 'writing', selected.type === '地点' ? '浏览' : '本章资料')">{{ selected.type === '地点' ? '在地图中查看' : '回到本章写作' }}</button><button class="rd-text-button" type="button" @click="emit('navigate', 'search', '正文')">回看来源 <PreviewIcon name="forward" /></button></div>
    </section>
    <p class="rd-demonstration">关系示例只保留在本次预览，不修改对象、正文或关系资料。</p>
  </section>
</template>
