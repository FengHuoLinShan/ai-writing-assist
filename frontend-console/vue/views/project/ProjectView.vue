<script setup>
import { computed, ref, watch } from "vue"
import ProjectCard from "./components/ProjectCard.vue"
import ImportDrawer from "./components/ImportDrawer.vue"
import {
  clearBulkSelection,
  getBulkSelection,
  reconcileBulkSelection,
  runBulkAction,
  bulkResultMessage,
  selectedItemsFrom,
  toggleBulkSelection,
} from "../../../shared/bulkSelection.js"
import {
  getApi,
  getAppState,
  getConfirmAction,
  getRouter,
  getToast,
  useStateKey,
} from "../../bridge/index.js"
import {
  filterProjects,
  projectCountLabel,
  projectName,
  sortedProjects,
} from "./logic/projectFilter.js"
import { clearCurrentProjectSelection, loadProjectsIntoState } from "./logic/projectState.js"
import {
  deleteProject as deleteProjectModal,
  editProject as editProjectModal,
  importAsNewProject,
  showCreateForm,
} from "./logic/projectModals.js"
import { showRecycleBin } from "./logic/recycleBin.js"
import { PROJECT_CARDS_SCOPE, projectSession } from "./projectSession.js"

/**
 * 项目页（作品档案）— vanilla projectView 的 Vue island 版本。
 * 数据由 island load() 预取（loadProjectsIntoState），错误态经 props 传入。
 */
const props = defineProps({
  loadError: { type: String, default: null },
})

const projects = useStateKey("projects")
const currentProjectId = useStateKey("currentProjectId")
const session = projectSession
const selection = getBulkSelection(session, PROJECT_CARDS_SCOPE)

const allProjects = computed(() => sortedProjects(projects.value || [], currentProjectId.value))
const visibleProjects = computed(() => filterProjects(allProjects.value, session.searchQuery))
const visibleIds = computed(() => visibleProjects.value.map((p) => p.id).filter(Boolean))
const totalCount = computed(() => (projects.value || []).length)

// 与 vanilla 一致：每次可见集合变化时 reconcile 选择集（剔除不可见项）
watch(visibleIds, (ids) => {
  reconcileBulkSelection(session, PROJECT_CARDS_SCOPE, ids)
}, { immediate: true })

const currentName = computed(() => {
  const current = (projects.value || []).find((p) => String(p.id) === String(currentProjectId.value || ""))
  return current ? projectName(current) : "尚未选择"
})

const filterCountLabel = computed(() => projectCountLabel(visibleProjects.value.length, allProjects.value.length))

const searchInput = ref(null)
const manageMode = ref(false)

function clearProjectSearch() {
  session.searchQuery = ""
  searchInput.value?.focus()
}

function toggleImportSection() {
  if (allProjects.value.length === 0) {
    importAsNewProject()
    return
  }
  session.importSectionOpen = !session.importSectionOpen
}

function openProject(id) {
  const state = getAppState()
  const project = (state?.projects || []).find((p) => p.id === id)
  if (!project) return
  state.currentProjectId = id
  state.currentProject = project
  getToast()(`已切换到项目：${project.title || project.name}`, "success")
  getRouter().navigate("today")
}

function toggleSelect(id, checked) {
  toggleBulkSelection(session, PROJECT_CARDS_SCOPE, id, checked)
}

function selectAllVisible() {
  for (const project of visibleProjects.value) {
    toggleBulkSelection(session, PROJECT_CARDS_SCOPE, project.id, true)
  }
}

function clearSelection() {
  clearBulkSelection(session, PROJECT_CARDS_SCOPE)
}

function runBulkDelete() {
  const items = selectedItemsFrom(projects.value || [], selection)
  if (!items.length) {
    getToast()("请先选择项目", "warning")
    return
  }
  getConfirmAction()(`确定将选中的 ${items.length} 个项目移入回收站吗？`, async () => {
    const result = await runBulkAction(items, async (project) => {
      await getApi().projects.remove(project.id)
    })
    getToast()(
      bulkResultMessage(result, "批量移入回收站", (item) => item.title || item.name || item.id),
      result.failed.length ? "warning" : "success",
    )
    clearBulkSelection(session, PROJECT_CARDS_SCOPE)
    await loadProjectsIntoState()
    await getRouter().refresh()
  }, "移入回收站")
}

function deleteProject(id) {
  deleteProjectModal(id, { clearCurrentProjectSelection })
}

function importSelectedFileAsNewProject(file) {
  importAsNewProject(file)
}

async function retryProjects() {
  await loadProjectsIntoState()
  await getRouter().refresh()
}
</script>

<template>
  <section class="project-catalog" aria-labelledby="project-catalog-title">
    <header class="project-archive-hero project-toolbar">
      <div class="project-archive-hero__folio" aria-hidden="true">
        <span>NC</span>
        <strong>{{ String(Math.max(totalCount, 1)).padStart(2, "0") }}</strong>
        <span>2026</span>
      </div>
      <div class="project-archive-hero__copy">
        <div class="project-archive-hero__kicker">
          <span>STORY ARCHIVE</span>
          <i aria-hidden="true"></i>
          <span>全部项目</span>
        </div>
        <h1 id="project-catalog-title"><span>作品</span><em>档案</em></h1>
        <p>收拢每一个世界，标记每一次续写。让正在发生的故事始终位于视线中心。</p>
      </div>
      <div class="project-archive-hero__summary">
        <span class="project-archive-hero__summary-label">PROJECT INDEX</span>
        <strong data-role="project-total-count">{{ totalCount }} 个项目</strong>
        <div class="project-archive-hero__current">
          <span>CURRENT / 当前</span>
          <b :title="currentName">{{ currentName }}</b>
        </div>
        <div class="project-archive-hero__actions">
          <button class="btn btn-primary" data-action="new" @click="showCreateForm">新建空白作品</button>
          <button class="btn btn-ghost" data-action="toggle-import" @click="toggleImportSection">{{ session.importSectionOpen ? "收起导入" : "导入已有作品" }}</button>
          <button class="btn btn-ghost" data-action="manage-projects" @click="manageMode = !manageMode">{{ manageMode ? "完成管理" : "管理作品" }}</button>
          <button v-if="manageMode" class="btn btn-ghost" data-action="recycle-bin" @click="showRecycleBin()">回收站</button>
        </div>
      </div>
      <div class="project-archive-hero__geometry" aria-hidden="true">
        <i></i><i></i><i></i><i></i>
      </div>
    </header>

    <div v-if="session.importSectionOpen" class="project-import-drawer">
      <ImportDrawer @import-new-project="importSelectedFileAsNewProject" />
    </div>

    <div v-if="props.loadError && allProjects.length === 0" class="empty-state project-catalog-state" role="alert">
      <div class="project-catalog-state__mark" aria-hidden="true">!</div>
      <div class="project-catalog-state__copy">
        <span class="project-catalog-state__index">CONNECTION / 00</span>
        <h2>项目列表暂时无法加载</h2>
        <p>{{ props.loadError }}</p>
        <div class="actions">
          <button class="btn btn-primary" data-action="retry-projects" @click="retryProjects">重新连接</button>
        </div>
      </div>
    </div>

    <div v-else-if="allProjects.length === 0" class="empty-state project-catalog-state project-catalog-state--first">
      <div class="project-catalog-state__mark" aria-hidden="true">
        <span>新</span>
        <i></i>
      </div>
      <div class="project-catalog-state__copy">
        <span class="project-catalog-state__index">FIRST STORY / 01</span>
        <h2>开始你的第一部小说</h2>
        <p>使用上方的“新建空白作品”或“导入已有作品”开始，两种方式之后都可以继续写作。</p>
      </div>
    </div>

    <template v-else>
      <div v-if="props.loadError" class="alert alert-warning" role="alert">
        <span>项目列表刷新失败，当前显示上次已加载的内容。</span>
        <button class="btn btn-sm" data-action="retry-projects" @click="retryProjects">重试</button>
      </div>
      <div class="project-index-bar">
        <div class="view-toolbar project-search-toolbar" role="search" aria-label="搜索项目">
          <label for="project-search-input">
            <span aria-hidden="true">SEARCH / 01</span>
            <span class="sr-only">按名称搜索</span>
          </label>
          <input
            class="form-input"
            id="project-search-input"
            data-role="project-search"
            type="search"
            v-model="session.searchQuery"
            placeholder="输入项目名称"
            autocomplete="off"
            ref="searchInput"
          />
          <button class="btn btn-sm btn-ghost" data-action="clear-project-search" :disabled="!session.searchQuery" @click="clearProjectSearch">清除</button>
          <span class="view-toolbar__count" data-role="project-filter-count" aria-live="polite">
            {{ filterCountLabel }}
          </span>
          <span class="bulk-toolbar__hint">当前项目优先 · 其余按最近更新排序</span>
        </div>
        <div v-if="manageMode" class="project-index-bar__bulk">
          <button class="btn btn-sm" data-action="select-visible-projects" :disabled="visibleIds.length === 0" :aria-label="`全选当前可见的 ${visibleIds.length} 个项目`" @click="selectAllVisible">全选当前可见项目</button>
          <div class="bulk-toolbar" data-scope="project-cards">
            <div class="bulk-toolbar__status">
              <strong>{{ selection.size }}</strong>
              <span>项目已选</span>
              <span class="bulk-toolbar__hint">只处理当前可见项目</span>
            </div>
            <div class="bulk-toolbar__actions">
              <button
                class="btn btn-sm btn-danger"
                data-action="bulk-run"
                data-scope="project-cards"
                data-bulk-action="delete-projects"
                data-bulk-static-disabled="false"
                :disabled="selection.size === 0"
                @click="runBulkDelete"
              >批量移入回收站</button>
              <button class="btn btn-sm" data-action="bulk-clear" data-scope="project-cards" :disabled="selection.size === 0" @click="clearSelection">清空</button>
            </div>
            <span class="sr-only">已选择 {{ selection.size }} 项目</span>
          </div>
        </div>
      </div>
      <div class="project-grid">
        <div v-if="visibleProjects.length === 0" class="empty-state" data-role="project-search-empty">
          <h2>没有找到匹配项目</h2>
          <p>没有名称包含「{{ session.searchQuery.trim() }}」的项目。</p>
          <div class="actions">
            <button class="btn btn-primary" data-action="clear-project-search" @click="clearProjectSearch">清除搜索</button>
          </div>
        </div>
        <template v-else>
          <ProjectCard
            v-for="(project, index) in visibleProjects"
            :key="project.id"
            :project="project"
            :index="index"
            :is-current="String(project.id) === String(currentProjectId || '')"
            :selected="selection.has(String(project.id))"
            :manage="manageMode"
            @open="openProject"
            @toggle-select="toggleSelect"
            @edit="editProjectModal"
            @delete="deleteProject"
          />
        </template>
        <div
          v-if="visibleProjects.length > 0"
          class="project-card project-card-placeholder"
          data-action="new"
          role="button"
          tabindex="0"
          aria-label="创建新项目"
          @click="showCreateForm"
          @keydown.enter="showCreateForm"
          @keydown.space.prevent="showCreateForm"
        >
          <div class="project-card-placeholder__visual" aria-hidden="true">
            <span>+</span>
            <i></i>
          </div>
          <div class="project-card-placeholder__copy">
            <span>NEW FILE / {{ String(visibleProjects.length + 1).padStart(2, "0") }}</span>
            <strong>创建新项目</strong>
            <p>为一个新世界建立独立档案。</p>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
