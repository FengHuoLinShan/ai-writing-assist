<!--
  OutlineActionMenu — 行内"更多操作"下拉，DOM 契约对齐 shared/viewHelper.js
  renderActionMenu（.action-menu > .action-menu-btn + .action-menu-list >
  .action-menu-item[data-action][data-*]），实现同 WorldActionMenu。
  开合状态 Vue 内聚：vanilla 靠 bindActionMenus 逐个绑定 + 全局 document click
  关闭，此处等价实现。
-->
<template>
  <div class="action-menu" :class="{ open }" :data-menu-id="menuId">
    <button class="action-menu-btn" type="button" title="更多操作" @click.stop="toggle">···</button>
    <div class="action-menu-list">
      <button
        v-for="item in items"
        :key="item.action"
        class="action-menu-item"
        :class="item.class || ''"
        :data-action="item.action"
        v-bind="dataAttrs(item)"
        @click.stop="select(item)"
      >{{ item.label }}</button>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue"

defineProps({
  menuId: { type: String, required: true },
  items: { type: Array, default: () => [] }, // [{ action, label, class?, data? }]
})

const emit = defineEmits(["select"])

const open = ref(false)

function dataAttrs(item) {
  return Object.fromEntries(
    Object.entries(item.data || {}).map(([key, value]) => [`data-${key}`, value]),
  )
}

function toggle() {
  // 关闭其他菜单（vanilla 同容器互斥语义）
  if (!open.value) {
    document.querySelectorAll(".action-menu.open").forEach((menu) => menu.classList.remove("open"))
  }
  open.value = !open.value
}

function select(item) {
  open.value = false
  emit("select", item)
}

function closeAll() {
  open.value = false
}

onMounted(() => document.addEventListener("click", closeAll))
onBeforeUnmount(() => document.removeEventListener("click", closeAll))
</script>
