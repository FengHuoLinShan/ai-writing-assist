<template>
  <aside id="sidebar">
    <button class="sidebar-project-switcher" type="button" title="切换作品" @click="$emit('navigate', 'project')">
      <span class="sidebar-project-switcher__mark" aria-hidden="true">◆</span>
      <span class="sidebar-project-switcher__copy"><small>当前作品</small><strong>{{ projectTitle || '选择作品' }}</strong></span>
      <span aria-hidden="true">⌄</span>
    </button>
    <nav aria-label="主导航">
      <ul id="nav-list" class="sidebar-desktop-nav">
        <li v-for="item in SHELL_NAV_ITEMS" :key="item.view" class="nav-item" :class="{ active: currentView === item.view || (item.view === 'today' && currentView === 'writing') }"
          :data-view="item.view" :title="item.title" role="button" tabindex="0"
          @click="$emit('navigate', item.view)" @keydown.enter.prevent="$emit('navigate', item.view)" @keydown.space.prevent="$emit('navigate', item.view)">
          <NavIcon :name="item.icon" /><span class="nav-label">{{ item.label }}</span>
        </li>
      </ul>
    </nav>
    <div id="sidebar-context-slot" aria-label="当前页面工具"></div>
    <div class="sidebar-footer">
      <details class="sidebar-more" :open="moreOpen" @toggle="moreOpen = $event.target.open">
        <summary class="nav-item" :class="{ active: moreActive }"><span class="sidebar-more__icon" aria-hidden="true">•••</span><span class="nav-label">更多</span></summary>
        <div class="sidebar-more__panel">
          <strong>更多创作工具</strong>
          <button v-for="item in SHELL_MORE_ITEMS" :key="item.label" type="button" @click="navigateMore(item)">
            <NavIcon :name="item.icon" /><span><b>{{ item.label }}</b><small>{{ item.title }}</small></span>
          </button>
          <button type="button" @click="showHelp"><span class="help-icon">?</span><span><b>帮助与快捷键</b><small>查看常用操作</small></span></button>
        </div>
      </details>
    </div>
    <nav class="sidebar-mobile-nav" aria-label="移动端主导航">
      <button v-for="item in SHELL_MOBILE_NAV_ITEMS" :key="item.view" type="button" :class="{ active: currentView === item.view || (item.view === 'today' && currentView === 'writing') }" @click="navigateMobile(item.view)">
        <NavIcon :name="item.icon" /><span>{{ item.label }}</span>
      </button>
      <button ref="mobileMoreTrigger" type="button" :class="{ active: mobileMoreOpen || moreActive }" aria-controls="sidebar-mobile-sheet" :aria-expanded="mobileMoreOpen" @click="toggleMobileMore">
        <span class="sidebar-more__icon" aria-hidden="true">•••</span><span>全部</span>
      </button>
    </nav>
    <div v-if="mobileMoreOpen" id="sidebar-mobile-sheet" ref="mobileSheet" class="sidebar-mobile-sheet" role="dialog" aria-label="全部功能" @keydown.esc.stop.prevent="closeMobileMore(true)">
      <button type="button" @click="navigateMobile('map')"><NavIcon name="map" /><span>地图</span></button>
      <button type="button" @click="navigateMobile('rag')"><NavIcon name="search" /><span>查找</span></button>
      <button v-for="item in SHELL_MORE_ITEMS" :key="`mobile-${item.label}`" type="button" @click="navigateMobile(item.view)"><NavIcon :name="item.icon" /><span>{{ item.label }}</span></button>
      <button type="button" @click="showHelp"><span class="help-icon">?</span><span>帮助</span></button>
    </div>
  </aside>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"
import NavIcon from "./NavIcon.vue"
import { SHELL_MOBILE_NAV_ITEMS, SHELL_MORE_ITEMS, SHELL_NAV_ITEMS } from "../navigation.js"
const props = defineProps({ currentView: { type: String, default: "project" }, projectTitle: { type: String, default: "" } })
const emit = defineEmits(["navigate", "show-help"])
const moreOpen = ref(false)
const mobileMoreOpen = ref(false)
const mobileMoreTrigger = ref(null)
const mobileSheet = ref(null)
const moreActive = computed(() => ["generate", "project-settings", "settings"].includes(props.currentView))
function navigateMore(item) { moreOpen.value = false; emit("navigate", item.view) }
function navigateMobile(view) { mobileMoreOpen.value = false; emit("navigate", view) }
async function toggleMobileMore() {
  mobileMoreOpen.value = !mobileMoreOpen.value
  if (mobileMoreOpen.value) {
    await nextTick()
    mobileSheet.value?.querySelector("button")?.focus()
  }
}
async function closeMobileMore(restoreFocus = false) {
  mobileMoreOpen.value = false
  if (restoreFocus) {
    await nextTick()
    mobileMoreTrigger.value?.focus()
  }
}
function showHelp() { moreOpen.value = false; mobileMoreOpen.value = false; emit("show-help") }
</script>
