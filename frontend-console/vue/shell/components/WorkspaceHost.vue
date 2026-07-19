<template>
  <main id="workspace" ref="workspace" tabindex="-1">
    <div id="workspace-content" ref="routeHost" data-imperative-route-host="hash-router"></div>
  </main>
</template>

<script setup>
import { onMounted, ref } from "vue"
const emit = defineEmits(["ready"])
const workspace = ref(null)
const routeHost = ref(null)
onMounted(() => emit("ready", routeHost.value))
defineExpose({ getRouteHost: () => routeHost.value, focus: () => workspace.value?.focus() })
</script>
