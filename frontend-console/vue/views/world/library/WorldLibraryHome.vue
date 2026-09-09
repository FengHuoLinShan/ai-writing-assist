<script setup>
import { computed } from "vue"
import { cardsFromLibraryItems } from "../bible/worldCards.js"
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"

const props = defineProps({
  overview: { type: Object, default: null },
  typeOptions: { type: Array, default: () => [] },
  metaFor: { type: Function, required: true },
})
const emit = defineEmits(["open", "select-topic", "select-type", "select-working", "create-topic", "browse-all"])

function toCards(items) {
  return cardsFromLibraryItems(items).map((card) => ({
    ...card,
    stateLabel: card.stateLabel,
  }))
}

const workingCards = computed(() => toCards(props.overview?.working_items || []))
const recentCards = computed(() => toCards(props.overview?.recent_items || []))
const favoriteCards = computed(() => toCards(props.overview?.favorite_items || []))
const topics = computed(() => props.overview?.topics || [])
const totals = computed(() => props.overview?.totals || {})
const typeFacets = computed(() => {
  const counts = new Map(
    (props.overview?.type_facets || []).map((facet) => [String(facet.type), Number(facet.count || 0)]),
  )
  const known = props.typeOptions
    .filter((option) => counts.has(option.value))
    .map((option) => ({ value: option.value, label: option.label, count: counts.get(option.value) }))
  const extra = Array.from(counts.entries())
    .filter(([value]) => !props.typeOptions.some((option) => option.value === value))
    .map(([value, count]) => ({ value, label: value, count }))
  return [...known, ...extra].sort((left, right) => right.count - left.count)
})

function formatTime(value) {
  if (!value) return ""
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })
}
</script>

<template>
  <div class="world-library-home">
    <section v-if="workingCards.length" class="world-library-home__section" aria-label="继续编辑">
      <header class="world-library-home__heading">
        <h3>继续编辑</h3>
        <button type="button" data-action="world-home-more-working" @click="emit('select-working')">查看全部工作稿</button>
      </header>
      <ul class="world-library-home__list">
        <li v-for="card in workingCards" :key="card.key">
          <button type="button" data-action="world-home-open" @click="emit('open', card)">
            <span class="world-library-home__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
            <span class="world-library-home__copy">
              <strong>{{ card.title }}</strong>
              <small>{{ card.summary || '还没有摘要' }}</small>
            </span>
            <span class="badge" :class="displayStateBadgeClass(card.state)">{{ card.stateLabel }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section v-if="recentCards.length" class="world-library-home__section" aria-label="最近使用">
      <header class="world-library-home__heading"><h3>最近使用</h3></header>
      <ul class="world-library-home__list world-library-home__list--compact">
        <li v-for="card in recentCards" :key="card.key">
          <button type="button" data-action="world-home-open" @click="emit('open', card)">
            <span class="world-library-home__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
            <span class="world-library-home__copy"><strong>{{ card.title }}</strong><small>{{ metaFor(card).label }}</small></span>
            <span v-if="card.lastOpenedAt" class="world-library-home__time">{{ formatTime(card.lastOpenedAt) }}</span>
          </button>
        </li>
      </ul>
    </section>

    <section v-if="favoriteCards.length" class="world-library-home__section" aria-label="收藏">
      <header class="world-library-home__heading"><h3>收藏</h3></header>
      <ul class="world-library-home__list world-library-home__list--compact">
        <li v-for="card in favoriteCards" :key="card.key">
          <button type="button" data-action="world-home-open" @click="emit('open', card)">
            <span class="world-library-home__symbol" aria-hidden="true">{{ metaFor(card).symbol }}</span>
            <span class="world-library-home__copy"><strong>{{ card.title }}</strong><small>{{ metaFor(card).label }}</small></span>
            <span v-if="card.isFavorite" class="world-library-home__time" aria-label="已收藏">★</span>
          </button>
        </li>
      </ul>
    </section>

    <section class="world-library-home__section" aria-label="主题目录">
      <header class="world-library-home__heading">
        <h3>主题目录</h3>
        <button type="button" data-action="world-home-create-topic" @click="emit('create-topic')">＋ 新建主题</button>
      </header>
      <ul v-if="topics.length" class="world-library-home__topics">
        <li v-for="topic in topics" :key="topic.id">
          <button type="button" data-action="world-home-open-topic" @click="emit('select-topic', topic.id)">
            <span>{{ topic.name }}</span>
            <small>{{ topic.member_count ? `${topic.member_count} 项` : '空主题' }}</small>
          </button>
        </li>
      </ul>
      <p v-else class="world-library-home__empty">还没有主题。用主题把同一份资料按写作视角分组，一份资料可以加入多个主题。</p>
    </section>

    <section class="world-library-home__section" aria-label="按类型筛选">
      <header class="world-library-home__heading">
        <h3>按类型</h3>
        <button type="button" data-action="world-home-browse-all" @click="emit('browse-all')">浏览全部 {{ totals.all || 0 }} 项资料</button>
      </header>
      <div v-if="typeFacets.length" class="world-library-home__types" role="group" aria-label="类型筛选">
        <button
          v-for="facet in typeFacets"
          :key="facet.value"
          type="button"
          class="world-library-home__type-chip"
          data-action="world-home-select-type"
          @click="emit('select-type', facet.value)"
        >{{ facet.label }} <small>{{ facet.count }}</small></button>
      </div>
      <p v-else class="world-library-home__empty">项目里还没有资料，先新建一份资料再回来整理。</p>
    </section>
  </div>
</template>

<style scoped>
.world-library-home { display: grid; gap: 22px; }
.world-library-home__section { display: grid; gap: 10px; }
.world-library-home__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.world-library-home__heading h3 { margin: 0; font-size: var(--text-md); }
.world-library-home__heading > button { border: 0; background: transparent; color: var(--accent); cursor: pointer; padding: 4px 0; min-height: 36px; }
.world-library-home__heading > button:hover { text-decoration: underline; }
.world-library-home__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-library-home__list li > button { display: grid; width: 100%; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 12px; min-height: 52px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 8px 12px; color: inherit; text-align: left; cursor: pointer; }
.world-library-home__list li > button:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-library-home__list li > button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-home__list--compact li > button { min-height: 48px; }
.world-library-home__symbol { display: grid; width: 36px; height: 36px; place-items: center; border-radius: var(--radius-sm); background: var(--bg-hover); color: var(--text-secondary); }
.world-library-home__copy { display: grid; min-width: 0; gap: 2px; }
.world-library-home__copy strong, .world-library-home__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-library-home__copy small { color: var(--text-muted); }
.world-library-home__time { color: var(--text-muted); font-size: 12px; }
.world-library-home__topics { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }
.world-library-home__topics button { display: flex; width: 100%; min-height: 60px; flex-direction: column; align-items: flex-start; justify-content: center; gap: 2px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 10px 14px; color: inherit; text-align: left; cursor: pointer; }
.world-library-home__topics button:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-library-home__topics small { color: var(--text-muted); }
.world-library-home__types { display: flex; flex-wrap: wrap; gap: 8px; }
.world-library-home__type-chip { display: inline-flex; min-height: 40px; align-items: center; gap: 6px; border: 1px solid var(--border); border-radius: 999px; background: var(--bg-panel); color: var(--text-primary); padding: 6px 14px; cursor: pointer; }
.world-library-home__type-chip:hover { border-color: var(--accent); background: var(--bg-hover); }
.world-library-home__type-chip small { color: var(--text-muted); }
.world-library-home__empty { margin: 0; color: var(--text-muted); }
@media (max-width: 760px) {
  .world-library-home__list li > button { min-height: 56px; }
  .world-library-home__list--compact li > button { min-height: 48px; }
  .world-library-home__heading > button,
  .world-library-home__topics button,
  .world-library-home__type-chip { min-height: 44px; }
}
</style>
