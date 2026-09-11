<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { getApi, getRouter, getToast } from "../../../bridge/index.js"
import { useModalDialog } from "../../../composables/useModalDialog.js"
import { displayStateBadgeClass } from "../../../../shared/assetDisplayState.js"
import { LIBRARY_STATE_LABELS } from "../bible/worldCards.js"

const props = defineProps({ projectId: { type: String, default: "" } })

const open = ref(false)
const query = ref("")
const items = ref([])
const loading = ref(false)
const loadError = ref("")
const activeIndex = ref(0)
const searchGeneration = ref(0)
const inputRef = ref(null)
let searchTimer = null
let bound = false

const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({
  isOpen: () => open.value,
  requestClose: close,
})

const KIND_LABELS = { page: "资料页", draft: "工作稿", entity: "人物或设定" }

const rows = computed(() => (items.value || []).map((item, index) => ({
  id: item.id,
  kind: item.kind,
  draftId: item.draft_id || null,
  title: item.title || "未命名资料",
  summary: String(item.summary || ""),
  state: item.working ? "working" : item.state,
  stateLabel: item.working ? "工作稿" : LIBRARY_STATE_LABELS[item.state] || "待完善",
  item_type: item.item_type || "",
  active: index === activeIndex.value,
})))

function handleQuickOpenRequest(event) {
  event.preventDefault()
  openQuickOpen()
}

function openQuickOpen() {
  if (!props.projectId) {
    getToast()?.("请先选择一个作品", "info")
    return
  }
  open.value = true
  query.value = ""
  items.value = []
  loadError.value = ""
  activeIndex.value = 0
  nextTick(() => inputRef.value?.focus())
  scheduleSearch("")
}

function close() {
  open.value = false
  if (searchTimer) clearTimeout(searchTimer)
}

function scheduleSearch(value) {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    void runSearch(value)
  }, 200)
}

function onQueryInput(event) {
  query.value = event.target.value
  activeIndex.value = 0
  scheduleSearch(event.target.value.trim())
}

async function runSearch(value) {
  const api = getApi()
  if (!api?.world?.listWorldLibrary) return
  const generation = ++searchGeneration.value
  loading.value = true
  loadError.value = ""
  try {
    const result = await api.world.listWorldLibrary({
      novel_id: props.projectId,
      q: value || undefined,
      sort: "recent",
      limit: 8,
    })
    if (generation !== searchGeneration.value) return
    items.value = result?.items || []
  } catch (error) {
    if (generation === searchGeneration.value) {
      loadError.value = error?.message || "资料搜索暂时不可用"
      items.value = []
    }
  } finally {
    if (generation === searchGeneration.value) loading.value = false
  }
}

function moveActive(delta) {
  if (!rows.value.length) return
  activeIndex.value = (activeIndex.value + delta + rows.value.length) % rows.value.length
}

function chooseRow(row) {
  if (!row) return
  const router = getRouter()
  const api = getApi()
  if (api?.world?.recordWorldLibraryRecent && props.projectId) {
    api.world.recordWorldLibraryRecent(props.projectId, row.kind, String(row.id)).catch(() => {})
  }
  close()
  const params = new URLSearchParams()
  if (row.kind === "entity") params.set("entity_id", row.id)
  else if (row.draftId) params.set("draft_id", row.draftId)
  else params.set("page_id", row.id)
  router?.navigate("world", "bible", true, params)
}

function onDialogKeydown(event) {
  if (event.key === "ArrowDown") {
    event.preventDefault()
    moveActive(1)
  } else if (event.key === "ArrowUp") {
    event.preventDefault()
    moveActive(-1)
  } else if (event.key === "Enter") {
    event.preventDefault()
    chooseRow(rows.value[activeIndex.value])
  } else {
    onKeydown(event)
  }
}

onMounted(() => {
  if (bound || typeof document === "undefined") return
  const host = document.getElementById("workspace-content")
  if (!host) return
  host.addEventListener("shell:quickopen-request", handleQuickOpenRequest)
  bound = true
})

onBeforeUnmount(() => {
  if (!bound || typeof document === "undefined") return
  const host = document.getElementById("workspace-content")
  host?.removeEventListener("shell:quickopen-request", handleQuickOpenRequest)
  bound = false
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" ref="overlayRef" class="modal-overlay" @click.self="close" @keydown="onDialogKeydown" @focusin="onFocusin">
      <section ref="dialogRef" class="modal-content world-quick-open" role="dialog" aria-modal="true" aria-labelledby="world-quick-open-title" tabindex="-1">
        <header class="world-quick-open__header">
          <h2 id="world-quick-open-title">快速打开资料</h2>
          <button type="button" class="btn-icon" aria-label="关闭" @click="close">×</button>
        </header>
        <div class="world-quick-open__body">
          <input
            ref="inputRef"
            :value="query"
            type="search"
            class="world-quick-open__input"
            placeholder="输入名称、别名或内容，↑↓ 选择，Enter 打开"
            aria-label="搜索资料"
            data-action="world-quick-open-input"
            @input="onQueryInput"
          >
          <p v-if="loadError" class="world-quick-open__hint" role="alert">{{ loadError }}</p>
          <p v-else-if="loading" class="world-quick-open__hint">正在搜索…</p>
          <ul v-else-if="rows.length" class="world-quick-open__list" aria-label="资料结果">
            <li v-for="row in rows" :key="row.id">
              <button
                type="button"
                :class="{ 'world-quick-open__row--active': row.active }"
                :data-quick-open-kind="row.kind"
                @mousemove="activeIndex = rows.indexOf(row)"
                @click="chooseRow(row)"
              >
                <span class="world-quick-open__copy">
                  <strong>{{ row.title }}</strong>
                  <small>{{ KIND_LABELS[row.kind] }}{{ row.item_type ? ` · ${row.item_type}` : "" }}{{ row.summary ? ` · ${row.summary.slice(0, 40)}` : "" }}</small>
                </span>
                <span class="badge" :class="displayStateBadgeClass(row.state)">{{ row.stateLabel }}</span>
              </button>
            </li>
          </ul>
          <p v-else-if="query" class="world-quick-open__hint">没有找到匹配的资料。</p>
          <p v-else class="world-quick-open__hint">显示最近使用的资料；输入关键词搜索全部资料。</p>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.world-quick-open { max-width: 560px; padding: 0; }
.world-quick-open__header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 6px; }
.world-quick-open__header h2 { margin: 0; font-size: var(--text-md); }
.world-quick-open__body { display: grid; gap: 10px; padding: 8px 16px 16px; }
.world-quick-open__input { min-height: 44px; width: 100%; }
.world-quick-open__list { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; max-height: 46vh; max-height: 46dvh; overflow-y: auto; }
.world-quick-open__list button { display: flex; width: 100%; min-height: 48px; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-panel); color: var(--text-primary); padding: 8px 12px; text-align: left; cursor: pointer; }
.world-quick-open__list button:hover, .world-quick-open__row--active { border-color: var(--accent); background: var(--bg-hover); }
.world-quick-open__list button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-quick-open__copy { display: grid; min-width: 0; gap: 2px; }
.world-quick-open__copy strong, .world-quick-open__copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-quick-open__copy small { color: var(--text-muted); }
.world-quick-open__hint { margin: 0; color: var(--text-muted); }
</style>
