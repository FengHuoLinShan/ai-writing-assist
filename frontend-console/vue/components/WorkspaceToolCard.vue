<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from "vue"
import ActionMenu from "./ActionMenu.vue"
import WorkspaceDrawer from "./WorkspaceDrawer.vue"

defineOptions({ inheritAttrs: false })
const props = defineProps({
  title: { type: String, required: true },
  context: { type: String, default: "" },
  status: { type: String, default: "" },
  actions: { type: Array, default: () => [] },
  moreActions: { type: Array, default: () => [] },
  actionPrefix: { type: String, default: "workspace-tool" },
})
const emit = defineEmits(["select"])
const id = useId()
const media = typeof window !== "undefined" ? window.matchMedia("(max-width: 760px)") : null
const mobile = ref(media?.matches || false)
const drawerOpen = ref(false)
const sidebarTarget = typeof document !== "undefined" && document.getElementById("sidebar-context-slot") ? "#sidebar-context-slot" : ""
const frozen = ref(null)
const section = ref(null)
const actions = computed(() => frozen.value?.actions || props.actions)
const moreActions = computed(() => (frozen.value?.moreActions || props.moreActions).map(action => ({
  ...action, action: action.dataAction || `${props.actionPrefix}-${action.key}`,
})))
function freeze() {
  if (!frozen.value) frozen.value = { actions: props.actions.map(action => ({ ...action })), moreActions: props.moreActions.map(action => ({ ...action })) }
}
function unfreeze(event) {
  if (!section.value?.contains(event.relatedTarget) && !event.relatedTarget?.closest(".action-menu-list")) frozen.value = null
}
function releasePointer() {
  if (!section.value?.contains(document.activeElement)) frozen.value = null
}
async function select(key) {
  const current = [...props.actions, ...props.moreActions].find(action => action.key === key)
  if (!current || current.disabled) return
  const wasOpen = drawerOpen.value
  drawerOpen.value = false
  frozen.value = null
  if (wasOpen) { await nextTick(); await nextTick() }
  if (![...props.actions, ...props.moreActions].some(action => action.key === key && !action.disabled)) return
  emit("select", key)
}
function resize() { mobile.value = media.matches; drawerOpen.value = false; frozen.value = null }
onMounted(() => media?.addEventListener("change", resize))
onBeforeUnmount(() => media?.removeEventListener("change", resize))
</script>

<template>
  <button v-if="mobile" type="button" class="btn workspace-tools-trigger" :aria-expanded="drawerOpen" @click="drawerOpen = true">{{ title }}</button>
  <Teleport :to="mobile ? 'body' : sidebarTarget || 'body'" :disabled="!mobile && !sidebarTarget">
    <WorkspaceDrawer :mobile="mobile" :open="drawerOpen" :title="title" @close="drawerOpen = false; frozen = null">
      <section ref="section" class="workspace-tools" v-bind="$attrs" :aria-label="title" @pointerdown.capture="freeze" @focusin="freeze" @focusout="unfreeze" @pointerleave="releasePointer" @click="drawerOpen && $event.target.closest('button:not(:disabled)') && (drawerOpen = false)">
        <header><strong>{{ title }}</strong><span v-if="context">{{ context }}</span></header>
        <p v-if="status" class="workspace-tools__status" role="status">{{ status }}</p>
        <div v-for="action in actions" :key="action.key" class="workspace-tools__item">
          <button type="button" class="btn workspace-tools__action" :class="{ 'is-primary': action.primary, 'btn-primary': action.primary }"
            :disabled="action.disabled" :data-action="action.dataAction || `${actionPrefix}-${action.key}`"
            :aria-describedby="action.hint ? id + '-' + action.key : undefined" @click="select(action.key)">
            <span>{{ action.label }}</span><span v-if="Number(action.badge) > 0" class="today-count">{{ action.badge }}</span>
          </button>
          <small v-if="action.hint" :id="id + '-' + action.key">{{ action.hint }}</small>
        </div>
        <ActionMenu v-if="moreActions.length || $slots.more" :menu-id="'workspace-tools-' + id" :items="moreActions" :floating="!mobile"
          :label="title + '：更多工具'" trigger-text="更多工具" @select="select($event.key)" @close="frozen = null"><slot name="more" /></ActionMenu>
        <slot />
      </section>
    </WorkspaceDrawer>
  </Teleport>
</template>

<style scoped>
.workspace-tools { display: grid; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--bg-base); min-width: 0; }
.workspace-tools header { display: grid; gap: 4px; padding: 2px 4px; }
.workspace-tools header strong { color: var(--text-secondary); font-size: var(--text-xs); }
.workspace-tools header span { font-size: var(--text-sm); overflow-wrap: anywhere; }
.workspace-tools__status, .workspace-tools__item small { margin: 0; color: var(--text-secondary); font-size: var(--text-xs); overflow-wrap: anywhere; }
.workspace-tools__item small { display: block; padding: 4px; }
.workspace-tools__action { display: flex; width: 100%; min-height: 44px; align-items: center; justify-content: space-between; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 10px; background: var(--bg-panel); color: var(--text-primary); text-align: left; cursor: pointer; font: inherit; }
.workspace-tools__action span:first-child { min-width: 0; overflow-wrap: anywhere; }
.workspace-tools__action:hover:not(:disabled):not(.is-primary) { border-color: var(--accent); background: var(--bg-hover); }
.workspace-tools__action:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.workspace-tools__action.is-primary { border-color: var(--accent); background: var(--accent); color: var(--text-on-accent); }
.workspace-tools__action:disabled { opacity: .55; cursor: not-allowed; }
.workspace-tools :deep(.action-menu), .workspace-tools :deep(.action-menu-btn) { width: 100%; }
.workspace-tools :deep(.action-menu-btn), .workspace-tools :deep([data-role="smart-dedup-action"] .btn) { min-height: 44px; width: 100%; text-align: left; }
.workspace-tools-trigger { min-height: 44px; margin-bottom: var(--space-3); }
</style>
