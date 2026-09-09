<script setup>
import { computed, ref, watch } from "vue"
import WorkspaceDrawer from "../../../components/WorkspaceDrawer.vue"

const props = defineProps({
  filters: { type: Object, default: () => ({}) },
  topics: { type: Array, default: () => [] },
  totalCount: { type: Number, default: 0 },
  workingCount: { type: Number, default: 0 },
  unclassifiedCount: { type: Number, default: 0 },
  favoriteCount: { type: Number, default: 0 },
  types: { type: Array, default: () => [] },
  projectId: { type: String, default: "" },
})
const emit = defineEmits([
  "select",
  "create-topic",
  "rename-topic",
  "archive-topic",
  "move-topic",
])

const isMobile = ref(
  typeof globalThis.matchMedia === "function"
    && globalThis.matchMedia("(max-width: 760px)").matches,
)
if (typeof globalThis.matchMedia === "function") {
  const mql = globalThis.matchMedia("(max-width: 760px)")
  const onChange = () => { isMobile.value = mql.matches }
  if (typeof mql.addEventListener === "function") mql.addEventListener("change", onChange)
  else if (typeof mql.addListener === "function") mql.addListener(onChange)
}

const drawerOpen = ref(false)
const expandedTopicIds = ref(new Set())
watch(() => props.projectId, () => { expandedTopicIds.value = new Set() }, { immediate: true })

const selectedKey = computed(() => {
  if (props.filters.favorite) return "favorite"
  if (props.filters.topicId) return `topic:${props.filters.topicId}`
  if (props.filters.state === "working") return "working"
  if (props.filters.type) return `type:${props.filters.type}`
  if (props.filters.unclassified) return "unclassified"
  return "all"
})

function selectKey(key) {
  if (key === "all") emit("select", { state: "", type: "", kind: "all", topicId: "", favorite: false, unclassified: false })
  else if (key === "working") emit("select", { state: "working", type: "", kind: "all", topicId: "", favorite: false, unclassified: false })
  else if (key === "favorite") emit("select", { state: "", type: "", kind: "all", topicId: "", favorite: true, unclassified: false })
  else if (key === "unclassified") emit("select", { state: "", type: "", kind: "all", topicId: "", favorite: false, unclassified: true })
  else if (key.startsWith("type:")) emit("select", { state: "", type: key.slice(5), kind: "all", topicId: "", favorite: false, unclassified: false })
  else emit("select", { state: "", type: "", kind: "all", topicId: key.slice(6), favorite: false, unclassified: false })
}

const creating = ref(false)
const creatingParentId = ref(null)
const creatingName = ref("")
const renamingId = ref("")
const renamingName = ref("")
const manageOpenId = ref("")

function startCreate(parentId = null) {
  renamingId.value = ""
  creating.value = true
  creatingParentId.value = parentId
  creatingName.value = ""
}

function submitCreate() {
  const name = creatingName.value.trim()
  if (!name) return
  emit("create-topic", { name, parentId: creatingParentId.value })
  creating.value = false
  creatingName.value = ""
}

function startRename(topic) {
  creating.value = false
  renamingId.value = topic.id
  renamingName.value = topic.name
}

function submitRename() {
  const name = renamingName.value.trim()
  if (!name || !renamingId.value) return
  emit("rename-topic", { topicId: renamingId.value, name })
  renamingId.value = ""
}

function toggleExpand(topicId) {
  const next = new Set(expandedTopicIds.value)
  if (next.has(topicId)) next.delete(topicId)
  else next.add(topicId)
  expandedTopicIds.value = next
}

function isExpanded(topicId) {
  return expandedTopicIds.value.has(topicId) || selectedKey.value === `topic:${topicId}`
}

function moveTopic(topic, direction) {
  emit("move-topic", { topicId: topic.id, direction })
}
</script>

<template>
  <aside class="world-library-directory" aria-label="资料目录">
    <button
      v-if="isMobile"
      type="button"
      class="btn btn-sm world-library-directory__open"
      data-action="world-library-open-directory"
      :aria-expanded="drawerOpen ? 'true' : 'false'"
      @click="drawerOpen = true"
    >☰ 资料目录</button>
    <WorkspaceDrawer :mobile="isMobile" :open="drawerOpen" title="资料目录" @close="drawerOpen = false">
      <nav class="world-library-directory__nav" aria-label="资料分组">
        <button type="button" :aria-current="selectedKey === 'all' ? 'page' : undefined" @click="selectKey('all')">
          <span>全部资料</span><span v-if="totalCount">{{ totalCount }}</span>
        </button>
        <button type="button" :aria-current="selectedKey === 'working' ? 'page' : undefined" @click="selectKey('working')">
          <span>工作稿</span><span v-if="workingCount">{{ workingCount }}</span>
        </button>
        <button type="button" :aria-current="selectedKey === 'favorite' ? 'page' : undefined" @click="selectKey('favorite')">
          <span>收藏</span><span v-if="favoriteCount">{{ favoriteCount }}</span>
        </button>
        <button type="button" :aria-current="selectedKey === 'unclassified' ? 'page' : undefined" @click="selectKey('unclassified')">
          <span>未归类</span><span v-if="unclassifiedCount">{{ unclassifiedCount }}</span>
        </button>

        <span class="world-library-directory__label">主题目录</span>
        <div
          v-for="topic in topics"
          :key="topic.id"
          class="world-library-directory__topic"
          :class="{ 'world-library-directory__topic--archived': topic.status === 'archived' }"
        >
          <div class="world-library-directory__topic-row">
            <button
              v-if="topic.children?.length"
              type="button"
              class="world-library-directory__toggle"
              :aria-expanded="isExpanded(topic.id) ? 'true' : 'false'"
              :aria-label="isExpanded(topic.id) ? `收起 ${topic.name}` : `展开 ${topic.name}`"
              @click="toggleExpand(topic.id)"
            >{{ isExpanded(topic.id) ? '▾' : '▸' }}</button>
            <span v-else class="world-library-directory__toggle world-library-directory__toggle--leaf" aria-hidden="true">·</span>
            <button
              type="button"
              class="world-library-directory__topic-name"
              :aria-current="selectedKey === `topic:${topic.id}` ? 'page' : undefined"
              @click="selectKey(`topic:${topic.id}`)"
            >
              <span>{{ topic.name }}</span><span v-if="topic.member_count">{{ topic.member_count }}</span>
            </button>
            <button
              type="button"
              class="world-library-directory__manage"
              :aria-expanded="manageOpenId === topic.id ? 'true' : 'false'"
              :aria-label="`管理主题 ${topic.name}`"
              @click="manageOpenId = manageOpenId === topic.id ? '' : topic.id"
            >⋯</button>
          </div>
          <form v-if="renamingId === topic.id" class="world-library-directory__rename" @submit.prevent="submitRename()">
            <label><span class="sr-only">主题名称</span>
              <input v-model="renamingName" type="text" maxlength="80" required>
            </label>
            <button class="btn btn-sm btn-primary" type="submit">保存</button>
            <button class="btn btn-sm btn-ghost" type="button" @click="renamingId = ''">取消</button>
          </form>
          <div v-if="manageOpenId === topic.id" class="world-library-directory__actions">
            <button type="button" @click="startRename(topic)">改名</button>
            <button type="button" @click="moveTopic(topic, -1)">上移</button>
            <button type="button" @click="moveTopic(topic, 1)">下移</button>
            <button type="button" @click="startCreate(topic.id)">新建子主题</button>
            <button v-if="topic.status === 'active'" type="button" @click="emit('archive-topic', { topicId: topic.id, archived: true })">归档</button>
            <button v-else type="button" @click="emit('archive-topic', { topicId: topic.id, archived: false })">恢复</button>
          </div>
          <div v-if="isExpanded(topic.id) && topic.children?.length" class="world-library-directory__children">
            <button
              v-for="child in topic.children"
              :key="child.id"
              type="button"
              :aria-current="selectedKey === `topic:${child.id}` ? 'page' : undefined"
              @click="selectKey(`topic:${child.id}`)"
            >
              <span>{{ child.name }}</span><span v-if="child.member_count">{{ child.member_count }}</span>
            </button>
          </div>
        </div>
        <form v-if="creating && !creatingParentId" class="world-library-directory__create" @submit.prevent="submitCreate()">
          <label><span class="sr-only">主题名称</span>
            <input v-model="creatingName" type="text" maxlength="80" placeholder="新主题名称" required>
          </label>
          <button class="btn btn-sm btn-primary" type="submit">创建</button>
          <button class="btn btn-sm btn-ghost" type="button" @click="creating = false">取消</button>
        </form>
        <button type="button" class="world-library-directory__add" data-action="world-library-create-topic" @click="startCreate(null)">＋ 新建主题</button>
        <div v-if="creating && creatingParentId" class="world-library-directory__hint">正在为子主题命名，请在主题行的“新建子主题”处完成。</div>

        <span v-if="types.length" class="world-library-directory__label">按类型</span>
        <button
          v-for="type in types"
          :key="type.value"
          type="button"
          :aria-current="selectedKey === `type:${type.value}` ? 'page' : undefined"
          @click="selectKey(`type:${type.value}`)"
        >
          <span>{{ type.label }}</span><span v-if="type.count">{{ type.count }}</span>
        </button>
      </nav>
    </WorkspaceDrawer>
  </aside>
</template>

<style scoped>
.world-library-directory { min-width: 0; }
.world-library-directory__open { width: 100%; margin-bottom: 10px; }
.world-library-directory__nav { position: sticky; top: 12px; display: grid; gap: 2px; max-height: calc(100vh - 96px); overflow-y: auto; }
.world-library-directory__nav > button,
.world-library-directory__topic-name,
.world-library-directory__children button {
  display: flex; min-height: 38px; width: 100%; align-items: center; justify-content: space-between; gap: 8px;
  border: 0; border-radius: var(--radius-sm); padding: 8px 10px; color: var(--text-secondary);
  background: transparent; text-align: left; cursor: pointer; font-size: var(--text-sm, 14px);
}
.world-library-directory__nav > button:hover,
.world-library-directory__nav > button[aria-current="page"],
.world-library-directory__topic-name:hover,
.world-library-directory__topic-name[aria-current="page"],
.world-library-directory__children button:hover,
.world-library-directory__children button[aria-current="page"] { color: var(--text-primary); background: var(--bg-hover); }
.world-library-directory__nav button:focus-visible,
.world-library-directory__topic button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.world-library-directory__label { padding: 14px 10px 4px; color: var(--text-muted); font-size: 12px; }
.world-library-directory__topic { display: grid; }
.world-library-directory__topic-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 2px; }
.world-library-directory__toggle { min-width: 26px; min-height: 38px; border: 0; background: transparent; color: var(--text-muted); cursor: pointer; }
.world-library-directory__toggle--leaf { text-align: center; cursor: default; }
.world-library-directory__manage { min-width: 30px; min-height: 38px; border: 0; background: transparent; color: var(--text-muted); cursor: pointer; border-radius: var(--radius-sm); }
.world-library-directory__manage:hover { color: var(--text-primary); background: var(--bg-hover); }
.world-library-directory__topic--archived .world-library-directory__topic-name { color: var(--text-muted); text-decoration: line-through; }
.world-library-directory__children { display: grid; padding-left: 16px; }
.world-library-directory__actions { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 10px 8px; }
.world-library-directory__actions button { min-height: 32px; border: 1px solid var(--border); border-radius: var(--radius-sm); background: var(--bg-panel); color: var(--text-secondary); padding: 4px 10px; font-size: 12px; cursor: pointer; }
.world-library-directory__actions button:hover { color: var(--text-primary); border-color: var(--accent); }
.world-library-directory__rename, .world-library-directory__create { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; padding: 4px 10px 8px; }
.world-library-directory__rename input, .world-library-directory__create input { min-height: 36px; width: 100%; }
.world-library-directory__add { display: flex; min-height: 38px; width: 100%; align-items: center; gap: 6px; border: 1px dashed var(--border); border-radius: var(--radius-sm); padding: 8px 10px; color: var(--text-secondary); background: transparent; cursor: pointer; }
.world-library-directory__add:hover { color: var(--text-primary); border-color: var(--accent); }
.world-library-directory__hint { padding: 4px 10px 8px; color: var(--text-muted); font-size: 12px; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (max-width: 760px) {
  .world-library-directory__nav { position: static; max-height: none; overflow: visible; }
  .world-library-directory__nav > button,
  .world-library-directory__topic-name,
  .world-library-directory__children button,
  .world-library-directory__manage,
  .world-library-directory__toggle,
  .world-library-directory__add { min-height: 44px; }
  .world-library-directory__actions button { min-height: 40px; }
}
</style>
