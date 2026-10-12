<!-- 新书开篇引导流程卡（BR-5）：挂在首页的伙伴区，空项目时出现。
     从一句构想到方向卡选择、世界观骨架逐条取舍与采用；全程只在做真实
     选择时停下，其余自动衔接。所有 AI 输出都是候选，采用由作者决定。 -->
<template>
  <section v-if="available && (allowStart || controller.state.view)" class="opening-flow" aria-labelledby="opening-flow-title">
    <template v-if="!controller.state.view">
      <header class="opening-flow__head">
        <h3 id="opening-flow-title">从一句构想开始新书</h3>
        <p>写下你想写的故事，先帮你生成几个开篇方向，再长出世界观骨架。</p>
      </header>
      <textarea
        v-model="vision"
        rows="2"
        maxlength="2000"
        placeholder="例如：一座随月潮起落的城市，守钟人在长夜里争夺报时的权柄。"
        data-action="opening-vision"
        aria-label="一句构想"
      ></textarea>
      <div class="opening-flow__hints">
        <input v-model="genreHint" type="text" maxlength="200" placeholder="题材意向（可不填）" aria-label="题材意向" />
        <input v-model="lengthHint" type="text" maxlength="200" placeholder="篇幅意向（可不填）" aria-label="篇幅意向" />
      </div>
      <div class="opening-flow__actions">
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!vision.trim() || controller.state.busy"
          data-action="opening-start"
          @click="start"
        >开始新书开篇</button>
        <span class="opening-flow__note">开始后会先生成方向卡（一轮生成，必要时修复格式）；随时可以结束，已确认的内容保留。</span>
      </div>
      <p v-if="controller.state.error" class="opening-flow__error" role="alert">{{ controller.state.error }}</p>
    </template>

    <template v-else>
      <header class="opening-flow__head">
        <h3 id="opening-flow-title">{{ controller.state.view.title }}</h3>
        <span class="opening-flow__status" :data-status="controller.state.view.status">{{ statusLabel }}</span>
      </header>
      <ol class="opening-flow__steps">
        <li v-for="step in controller.state.view.steps" :key="step.step_id" :data-state="step.state">
          <span aria-hidden="true">{{ stepMark(step.state) }}</span>
          <span>{{ step.title }}</span>
        </li>
      </ol>
      <p v-if="controller.state.view.stop" class="opening-flow__reason" role="status">
        {{ controller.state.view.stop.reason }}
      </p>
      <p v-else-if="controller.state.view.status === 'running'" class="opening-flow__reason" role="status">
        正在按流程推进，需要你决定时会停下来说明原因。
      </p>

      <!-- 方向卡选择 -->
      <div v-if="cards.length" class="opening-flow__cards">
        <article
          v-for="(card, index) in cards"
          :key="`${card.title}-${index}`"
          class="opening-flow__card"
          :class="{ 'is-chosen': selectedIndex === index }"
        >
          <label class="opening-flow__card-pick">
            <input
              v-model="selectedIndex"
              type="radio"
              name="opening-direction"
              :value="index"
              data-action="opening-pick-card"
            />
            <strong>{{ card.title }}</strong>
          </label>
          <dl class="opening-flow__fields">
            <div v-for="column in FIELD_COLUMNS" :key="column.key">
              <dt>{{ column.label }}</dt>
              <dd v-if="selectedIndex !== index">{{ card[column.key] }}</dd>
              <textarea
                v-else
                v-model="editable[column.key]"
                rows="2"
                maxlength="300"
                :aria-label="column.label"
              ></textarea>
            </div>
          </dl>
        </article>
      </div>
      <div v-if="atDirectionStop" class="opening-flow__actions">
        <button
          type="button"
          class="btn btn-primary"
          :disabled="controller.state.busy || selectedIndex < 0"
          data-action="opening-choose-direction"
          @click="chooseDirection"
        >用这个方向继续</button>
        <button
          v-if="panel?.more_allowed"
          type="button"
          class="btn btn-ghost"
          :disabled="controller.state.busy"
          data-action="opening-more-cards"
          @click="controller.choose('choose_direction', { action: 'more_cards' })"
        >都不满意，再要一批（一轮生成，必要时修复格式）</button>
        <button type="button" class="btn btn-ghost" :disabled="controller.state.busy" @click="controller.abandonFlow()">结束流程</button>
      </div>

      <OpeningSkeletonReview ref="skeletonReview" v-if="panel?.package?.package_suggestion_id && (atAdoptStop || panel?.adopted)"
        :project-id="projectId" :package-id="panel.package.package_suggestion_id" :adopted="Boolean(panel.adopted)"
        @adopt="hash => controller.choose('adopt_skeleton', { action: 'adopt_skeleton', expected_preview_hash: hash })"
        @rolled-back="skeletonReversed = true" />
      <p v-if="skeletonReversed" role="status">本次骨架采用已撤销；保留内容请在撤销回执中核对。</p>

      <!-- 骨架可用：下一步由作者选 -->
      <div v-if="atReadyStop" class="opening-flow__actions">
        <button type="button" class="btn btn-primary" data-action="opening-first-chapter" @click="goOutlineSuggestion">生成故事总纲建议</button>
        <button type="button" class="btn" data-action="opening-deepen" @click="goWorldDeepen">继续深化世界观</button>
        <button type="button" class="btn" data-action="opening-write-first" @click="goWriting">开始写第一章</button>
      </div>

      <!-- 通用停点动作（阻断等） -->
      <div v-if="genericActions.length" class="opening-flow__actions">
        <button
          v-for="action in genericActions"
          :key="action.action"
          type="button"
          class="btn"
          :data-action="`opening-${action.action}`"
          @click="runAction(action)"
        >{{ action.label }}</button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { getApi, getRouter, getToast } from "../../../bridge/index.js"
import OpeningSkeletonReview from "./OpeningSkeletonReview.vue"
import { createGuidedFlowController } from "../../writing/controllers/guidedFlowController.js"

const props = defineProps({
  projectId: { type: String, required: true },
  allowStart: { type: Boolean, default: true },
  available: { type: Boolean, default: false },
})

const api = getApi()
const router = getRouter()
const toast = getToast()

const FIELD_COLUMNS = [
  { key: "genre_promise", label: "题材承诺" },
  { key: "central_conflict", label: "主冲突" },
  { key: "protagonist_goal", label: "主角与目标" },
  { key: "world_tone", label: "世界基调与独特设定" },
  { key: "reader_promise", label: "读者期待" },
  { key: "main_risk", label: "主要风险" },
]

const controller = createGuidedFlowController({
  api,
  toast,
  getProjectId: () => props.projectId,
})
const skeletonReview = ref(null)
const skeletonReversed = ref(false)
const vision = ref("")
const genreHint = ref("")
const lengthHint = ref("")
const selectedIndex = ref(-1)
const editable = ref({})

const view = computed(() => controller.state.view)
const panel = computed(() => view.value?.panel || null)
const cards = computed(() => panel.value?.cards || [])
const stopStep = computed(() => view.value?.stop?.step_id || "")
const atDirectionStop = computed(() => stopStep.value === "choose_direction" && cards.value.length > 0)
const atAdoptStop = computed(() => stopStep.value === "adopt_skeleton")
const atReadyStop = computed(
  () => !skeletonReversed.value && view.value?.status === "completed" && stopStep.value === "skeleton_ready",
)
const STATUS_LABELS = {
  running: "进行中",
  waiting_approval: "等你的决定",
  completed: "已完成",
  failed: "已停下",
  cancelled: "已结束",
}
const statusLabel = computed(() => STATUS_LABELS[view.value?.status] || "")

const HANDLED_ACTIONS = new Set(["more_cards", "open_package", "adopt_skeleton"])
const genericActions = computed(() =>
  (view.value?.stop?.actions || []).filter((action) => !HANDLED_ACTIONS.has(action.action)),
)

function stepMark(state) {
  if (state === "done") return "✓"
  if (state === "active") return "●"
  if (state === "blocked") return "!"
  if (state === "skipped") return "—"
  return "○"
}

async function start() {
  const input = {
    vision: vision.value.trim(),
    ...(genreHint.value.trim() ? { genre_hint: genreHint.value.trim() } : {}),
    ...(lengthHint.value.trim() ? { length_hint: lengthHint.value.trim() } : {}),
  }
  const started = await controller.startFlow("new_book_opening", { input })
  if (started) {
    // 开始即授权第一批方向卡：推进一次生成（成本已在开始说明）。
    await controller.advance({})
  }
}

function pickEditable() {
  const card = cards.value[selectedIndex.value]
  editable.value = card
    ? Object.fromEntries(FIELD_COLUMNS.map((column) => [column.key, card[column.key] || ""]))
    : {}
}

watch(selectedIndex, pickEditable)

async function chooseDirection() {
  if (selectedIndex.value < 0) return null
  const result = await controller.choose("choose_direction", {
    action: "choose",
    card_index: selectedIndex.value,
    fields: { ...editable.value },
  })
  if (result) selectedIndex.value = -1
  return result
}

function openPackage() {
  skeletonReview.value?.$el?.scrollIntoView?.({ block: "nearest" })
}

function goOutlineSuggestion() {
  router.navigate("outline", "story-outline", true)
}

function goWorldDeepen() {
  router.navigate(
    "generate",
    null,
    true,
    new URLSearchParams({ tab: "world", target: "core_entity", preset: "world_core" }),
  )
}

function goWriting() {
  router.navigate("writing")
}

function runAction(action) {
  if (action.action === "open_package") return openPackage()
  if (action.action === "abandon_flow") return controller.abandonFlow()
  return null
}

onMounted(async () => {
  if (!props.available || !props.projectId) return
  if (!api.assistant?.guidedFlowActive) return
  const active = await (api.assistant.guidedFlowLatest ? api.assistant.guidedFlowLatest(props.projectId, "new_book_opening") : api.assistant.guidedFlowActive(props.projectId)).catch(() => null)
  if (active?.run_id && active.flow_id === "new_book_opening") {
    await controller.attachRun(active.run_id)
  }
})

onBeforeUnmount(() => controller.dispose())
</script>

<style scoped>
.opening-flow {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  padding: 16px;
  display: grid;
  gap: 12px;
}

.opening-flow__head h3 {
  margin: 0 0 4px;
  font-size: 15px;
}

.opening-flow__head p {
  margin: 0;
  color: var(--text-muted);
  font-size: 13px;
}

.opening-flow__status {
  font-size: 12px;
  color: var(--text-muted);
}

.opening-flow__status[data-status="waiting_approval"] {
  color: var(--warning, #9a6b00);
  font-weight: 600;
}

.opening-flow__status[data-status="completed"] {
  color: var(--success, #2e7d4f);
}

.opening-flow textarea,
.opening-flow input[type="text"] {
  width: 100%;
  min-height: 38px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-panel, #fff);
  color: var(--text-primary);
  box-sizing: border-box;
}

.opening-flow__hints {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.opening-flow__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.opening-flow__note {
  font-size: 12px;
  color: var(--text-muted);
}

.opening-flow__error {
  margin: 0;
  color: var(--danger, #b42318);
  font-size: 13px;
}

.opening-flow__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 13px;
  color: var(--text-muted);
}

.opening-flow__steps li {
  display: flex;
  align-items: center;
  gap: 6px;
}

.opening-flow__steps li[data-state="active"] {
  color: var(--text-primary);
  font-weight: 600;
}

.opening-flow__steps li[data-state="blocked"] {
  color: var(--danger, #a33a2a);
}

.opening-flow__reason {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.opening-flow__cards {
  display: grid;
  gap: 10px;
}

.opening-flow__card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  display: grid;
  gap: 8px;
}

.opening-flow__card.is-chosen {
  border-color: var(--accent);
}

.opening-flow__card-pick {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.opening-flow__fields {
  margin: 0;
  display: grid;
  gap: 6px;
}

.opening-flow__fields div {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 8px;
  align-items: start;
}

.opening-flow__fields dt {
  font-size: 12px;
  color: var(--text-muted);
}

.opening-flow__fields dd {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
}

.opening-flow__fields textarea {
  min-height: 52px;
}

.opening-flow__skeleton {
  display: grid;
  gap: 8px;
}

.opening-flow__skeleton p {
  margin: 0;
  font-size: 13px;
}

@media (max-width: 640px) {
  .opening-flow__hints {
    grid-template-columns: 1fr;
  }

  .opening-flow__fields div {
    grid-template-columns: 1fr;
  }
}
</style>
