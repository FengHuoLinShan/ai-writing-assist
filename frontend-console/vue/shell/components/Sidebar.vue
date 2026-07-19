<template>
  <nav id="sidebar" aria-label="主导航">
    <ul id="nav-list">
      <li v-for="item in SHELL_NAV_ITEMS" :key="item.view" class="nav-item" :class="{ active: currentView === item.view }"
        :data-view="item.view" :data-tooltip="item.title" :title="item.title" role="button" tabindex="0"
        @click="$emit('navigate', item.view)" @keydown.enter.prevent="$emit('navigate', item.view)" @keydown.space.prevent="$emit('navigate', item.view)">
        <NavIcon :name="item.icon" /><span class="nav-label">{{ item.label }}</span>
      </li>
      <li class="nav-item help" data-tooltip="快捷键帮助" title="快捷键帮助" role="button" tabindex="0"
        @click="$emit('show-help')" @keydown.enter.prevent="$emit('show-help')" @keydown.space.prevent="$emit('show-help')">
        <span class="help-icon">?</span><span class="nav-label">帮助</span>
      </li>
    </ul>
  </nav>
</template>

<script setup>
import NavIcon from "./NavIcon.vue"
import { SHELL_NAV_ITEMS } from "../navigation.js"
defineProps({ currentView: { type: String, default: "project" } })
defineEmits(["navigate", "show-help"])
</script>
