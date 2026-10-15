<!-- 写作页引导流程宿主（ADR-0032）：挂在工作区顶部的伙伴区，不新增独立流程页。
     每个停点说明为什么停，并给出作者语言的可执行动作；无流程时整体隐藏。 -->
<template>
  <section v-if="view" class="writing-flow-host" :class="{ 'writing-flow-host--done': isTerminal }" aria-labelledby="writing-flow-title">
    <header class="writing-flow-host__head">
      <div class="writing-flow-host__title">
        <h3 id="writing-flow-title">{{ view.title }}</h3>
        <span class="writing-flow-host__status" :data-status="view.status">{{ statusLabel }}</span>
      </div>
      <button type="button" class="btn btn-sm btn-ghost" data-action="flow-dismiss" @click="controller.dismiss()">收起</button>
    </header>

    <ol class="writing-flow-host__steps">
      <li v-for="step in view.steps" :key="step.step_id" :data-state="step.state">
        <span class="writing-flow-host__dot" aria-hidden="true">{{ stepMark(step.state) }}</span>
        <span class="writing-flow-host__step-title">{{ step.title }}</span>
        <span v-if="step.detail" class="writing-flow-host__step-detail">{{ step.detail }}</span>
      </li>
    </ol>

    <p v-if="view.stop" class="writing-flow-host__reason" role="status">{{ view.stop.reason }}</p>
    <p v-else-if="view.status === 'running'" class="writing-flow-host__reason" role="status">
      正在按流程推进，完成或需要你决定时会停下来说明原因。
    </p>

    <slot />
    <div v-if="!customActions && visibleActions.length" class="writing-flow-host__actions">
      <button
        v-for="action in visibleActions"
        :key="action.action"
        type="button"
        class="btn"
        :class="{ 'btn-primary': action.action === primary?.action }"
        :disabled="controller.state.busy"
        :data-action="`flow-${action.action}`"
        @click="runAction(action)"
      >{{ action.label }}</button>
    </div>

    <div v-if="!customActions && settingsEditable" class="writing-flow-host__settings">
      <label>
        <input
          type="checkbox"
          :checked="Boolean(view.settings?.semantic_review)"
          :disabled="controller.state.busy"
          data-action="flow-toggle-semantic-review"
          @change="onSemanticToggle"
        />
        生成后自动接独立语义审查（含分段检查与必要修复，按实际调用计费）
      </label>
      <label v-if="rollingAvailable" class="writing-flow-host__window">
        采用后规划接下来
        <select
          :value="windowSize"
          :disabled="controller.state.busy"
          data-action="flow-planning-window"
          aria-label="接下来几章的规划窗口"
          @change="onWindowChange"
        ><option v-for="size in [1, 2, 3, 4, 5]" :key="size" :value="size">{{ size }}</option></select>
        章的走向（只生成大纲候选，不生成正文）
      </label>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue"
import { getRouter } from "../../../bridge/index.js"

const props = defineProps({
  controller: { type: Object, required: true },
  customActions: { type: Boolean, default: false },
})

const router = getRouter()
const view = computed(() => props.controller.state.view)
const isTerminal = computed(() => ["completed", "failed", "cancelled"].includes(view.value?.status))
const STATUS_LABELS = {
  running: "进行中",
  waiting_approval: "等你的决定",
  completed: "已完成",
  failed: "已停下",
  cancelled: "已结束",
}
const statusLabel = computed(() => STATUS_LABELS[view.value?.status] || "")
const visibleActions = computed(() => (view.value?.stop?.actions || []).filter((action) => action.action !== "open_writing"))
const primary = computed(() => visibleActions.value[0] || null)
const settingsEditable = computed(() => view.value?.stop?.step_id === "confirm_reference")
const rollingAvailable = computed(() => view.value?.flow_id === "continue_writing")
const windowSize = computed(() => Number(view.value?.settings?.planning_window) || 3)

function onSemanticToggle(event) {
  props.controller.saveSettings(event.currentTarget.checked, windowSize.value)
}

function onWindowChange(event) {
  props.controller.saveSettings(
    Boolean(view.value?.settings?.semantic_review),
    Number(event.currentTarget.value),
  )
}

function stepMark(state) {
  if (state === "done") return "✓"
  if (state === "active") return "●"
  if (state === "blocked") return "!"
  if (state === "skipped") return "—"
  return "○"
}

function runAction(action) {
  if (["confirm_reference", "confirm_rolling"].includes(action.action)) props.controller.confirmReference()
  else if (action.action === "open_candidate") props.controller.openCandidate()
  else if (action.action === "abandon_flow") props.controller.abandonFlow()
  else if (action.action === "skip_layer") props.controller.choose(view.value?.stop?.step_id, { action: "skip_layer" })
  else if (action.action === "finish_flow") {
    props.controller.choose(view.value?.stop?.step_id, { action: "finish_flow" })
  } else if (action.action === "open_outline") {
    router.navigate("outline", "story-outline", true)
  } else if (action.action === "plan_ahead" || action.action === "decline") {
    props.controller.choose("rolling_offer", { action: action.action })
  }
}
</script>

<style scoped>
.writing-flow-host {
  border: 1px solid var(--border, #d9d4c8);
  border-radius: 10px;
  background: var(--surface-raised, #fbfaf7);
  padding: 12px 16px;
  margin: 0 0 12px;
  display: grid;
  gap: 10px;
}

.writing-flow-host--done {
  opacity: 0.92;
}

.writing-flow-host__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.writing-flow-host__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.writing-flow-host__title h3 {
  margin: 0;
  font-size: 15px;
}

.writing-flow-host__status {
  font-size: 12px;
  color: var(--text-muted, #7c7668);
  white-space: nowrap;
}

.writing-flow-host__status[data-status="waiting_approval"] {
  color: var(--warning, #9a6b00);
  font-weight: 600;
}

.writing-flow-host__status[data-status="completed"] {
  color: var(--success, #2e7d4f);
}

.writing-flow-host__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 13px;
}

.writing-flow-host__steps li {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-muted, #7c7668);
}

.writing-flow-host__steps li[data-state="active"] {
  color: var(--text-strong, #33302a);
  font-weight: 600;
}

.writing-flow-host__steps li[data-state="done"] {
  color: var(--text, #4c483e);
}

.writing-flow-host__steps li[data-state="blocked"] {
  color: var(--danger, #a33a2a);
}

.writing-flow-host__step-detail {
  font-weight: 400;
  color: var(--text-muted, #7c7668);
}

.writing-flow-host__reason {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.writing-flow-host__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.writing-flow-host__settings {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  font-size: 13px;
  color: var(--text-muted, #7c7668);
}

.writing-flow-host__settings label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.writing-flow-host__window select {
  min-height: 30px;
  padding: 2px 6px;
}

@media (max-width: 640px) {
  .writing-flow-host {
    padding: 10px 12px;
  }

  .writing-flow-host__steps {
    flex-direction: column;
    gap: 4px;
  }
}
</style>
