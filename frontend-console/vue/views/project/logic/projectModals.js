/**
 * 项目新建/编辑/删除/导入为新项目 — 外壳全局 modal 流程，从 views/projectView.js 移植。
 * 内容字符串沿用 esc() 拼装（README「安全与契约」既有豁免，非 Vue 模板场景）。
 * state 写操作经 bridge 取 appState。
 */
import {
  getApi,
  getAppState,
  getCloseModal,
  getConfirmAction,
  getEsc,
  getRouter,
  getShowModalHtml,
  getToast,
} from "../../../bridge/index.js"
import { IMPORT_FILE_ACCEPT, validateImportFile } from "../../../composables/useImportUpload.js"

function mergeProject(projects, project) {
  const items = Array.isArray(projects) ? projects : []
  return items.some((item) => item.id === project.id)
    ? items.map((item) => item.id === project.id ? { ...item, ...project } : item)
    : [...items, project]
}

/** 编辑项目（showModalHtml 表单 + 保存回写 state）。 */
export function editProject(id) {
  const state = getAppState()
  const project = state?.projects?.find((p) => p.id === id)
  if (!project) return
  const esc = getEsc()

  const formHtml = `
    <div class="form-group">
      <label for="edit-title">项目标题</label>
      <input class="form-input" id="edit-title" value="${esc(project.title || project.name || "")}" required />
    </div>
    <div class="form-group">
      <label for="edit-genre">题材</label>
      <input class="form-input" id="edit-genre" value="${esc(project.genre || "")}" />
    </div>
    <div class="form-group">
      <label for="edit-tone">风格基调</label>
      <input class="form-input" id="edit-tone" value="${esc(project.tone || "")}" placeholder="如：黑暗、幽默、写实" />
    </div>
    <div class="form-group">
      <label for="edit-target-length">目标规模</label>
      <select class="form-select" id="edit-target-length">
        <option value="">未设置</option>
        <option value="short" ${project.target_length === "short" ? "selected" : ""}>短篇</option>
        <option value="medium" ${project.target_length === "medium" ? "selected" : ""}>中篇</option>
        <option value="novel" ${project.target_length === "novel" ? "selected" : ""}>长篇</option>
        <option value="epic" ${project.target_length === "epic" ? "selected" : ""}>史诗</option>
      </select>
    </div>
    <div class="form-group">
      <label for="edit-stage">创作阶段</label>
      <select class="form-select" id="edit-stage">
        <option value="">未设置</option>
        <option value="world_building" ${project.current_stage === "world_building" ? "selected" : ""}>世界构建中</option>
        <option value="outlining" ${project.current_stage === "outlining" ? "selected" : ""}>大纲规划中</option>
        <option value="writing" ${project.current_stage === "writing" ? "selected" : ""}>正文写作中</option>
        <option value="revising" ${project.current_stage === "revising" ? "selected" : ""}>修订中</option>
      </select>
    </div>
  `

  getShowModalHtml()("编辑项目", formHtml, [
    {
      text: "保存",
      class: "btn-primary",
      handler: async () => {
        const titleInput = document.getElementById("edit-title")
        const title = titleInput?.value.trim() || ""
        const genre = document.getElementById("edit-genre")?.value
        const tone = document.getElementById("edit-tone")?.value
        const targetLength = document.getElementById("edit-target-length")?.value
        const stage = document.getElementById("edit-stage")?.value

        if (!title) {
          getToast()("请输入项目标题", "warning")
          titleInput?.focus()
          return false
        }

        const payload = {
          title,
          genre: genre || null,
          tone: tone || null,
          target_length: targetLength || null,
          current_stage: stage || null,
        }

        try {
          const updated = await getApi().projects.update(id, payload)
          // 重赋值触发响应式（Vue 侧 useStateKey("projects") 依赖顶层 set）
          state.projects = (state.projects || []).map((p) => (
            p.id === id ? { ...p, ...updated } : p
          ))
          if (state.currentProjectId === id && state.currentProject) {
            state.currentProject = { ...state.currentProject, ...updated }
          }
          getToast()("项目已更新", "success")
          getCloseModal()()
        } catch (err) {
          getToast()(`保存失败：${err.message}`, "error")
          return false
        }
      },
    },
  ])
}

/** 删除项目（二次确认 → 移入回收站）。 */
export function deleteProject(id, { clearCurrentProjectSelection } = {}) {
  const state = getAppState()
  const project = state?.projects?.find((p) => p.id === id)
  if (!project) return
  const name = project.title || project.name || "未命名"
  getConfirmAction()(
    `确定要删除项目「${getEsc()(name)}」吗？删除后可在回收站中恢复。`,
    async () => {
      try {
        await getApi().projects.remove(id)
        getToast()(`项目「${name}」已移至回收站`, "success")
        if (state.currentProjectId === id) {
          clearCurrentProjectSelection?.()
        }
        await getRouter().refresh()
      } catch (err) {
        getToast()(`删除失败：${err.message}`, "error")
      }
    },
    "移至回收站",
  )
}

/** 新建项目（showModalHtml 表单 + 创建后进入写作台）。 */
export function showCreateForm() {
  const formHtml = `
    <div class="form-group">
      <label for="create-title">项目名称 *</label>
      <input class="form-input" id="create-title" placeholder="输入小说名称" required />
    </div>
    <div class="form-row">
      <div class="form-group">
        <label for="create-genre">题材</label>
        <select class="form-select" id="create-genre">
          <option value="">选择题材</option>
          <option value="fantasy">奇幻</option>
          <option value="scifi">科幻</option>
          <option value="mystery">悬疑</option>
          <option value="romance">言情</option>
          <option value="wuxia">武侠</option>
          <option value="xianxia">仙侠</option>
          <option value="horror">恐怖</option>
          <option value="historical">历史</option>
          <option value="other">其他</option>
        </select>
      </div>
      <div class="form-group">
        <label for="create-language">语言</label>
        <select class="form-select" id="create-language">
          <option value="zh" selected>中文</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label for="create-tone">基调</label>
      <input class="form-input" id="create-tone" placeholder="如：黑暗、幽默、写实" />
    </div>
  `

  getShowModalHtml()("新建项目", formHtml, [
    {
      text: "创建",
      class: "btn-primary",
      handler: async () => {
        const titleInput = document.getElementById("create-title")
        const title = titleInput?.value.trim() || ""
        if (!title) {
          getToast()("请输入项目标题", "warning")
          titleInput?.focus()
          return false
        }

        try {
          const project = await getApi().projects.create({
            title,
            genre: document.getElementById("create-genre")?.value || "",
            tone: document.getElementById("create-tone")?.value || "",
            language: "zh",
          })
          getToast()(`项目 "${title}" 已创建`, "success")
          const state = getAppState()
          if (state) {
            state.currentProjectId = project.id
            state.currentProject = project
          }
          getRouter().navigate("writing")
        } catch (err) {
          getToast()(`创建失败：${err.message}`, "error")
          return false
        }
      },
    },
  ])
}

/**
 * 导入为新项目（动态 file input → 建项目 → 上传 → 进写作台）。
 * 对应 vanilla importFile：api.imports.upload 无进度回调路径。
 */
export function importAsNewProject() {
  const input = document.createElement("input")
  input.type = "file"
  input.accept = IMPORT_FILE_ACCEPT
  input.onchange = async () => {
    if (!input.files || !input.files[0]) return
    const file = input.files[0]
    const toast = getToast()
    const validationError = validateImportFile(file)
    if (validationError) {
      toast(validationError, "error")
      return
    }
    const projectName = file.name.replace(/\.[^.]+$/, "").trim() || "未命名小说"

    getConfirmAction()(
      `将创建新项目「${projectName}」并导入文件「${file.name}」。是否继续？`,
      async () => {
        const state = getAppState()
        const selectionAtStart = state?.currentProjectId || null
        let createdProject = null
        try {
          createdProject = await getApi().projects.create({
            title: projectName,
            genre: "",
            tone: "",
            language: "zh",
          })
          if (state) {
            state.projects = mergeProject(state.projects, createdProject)
            if ((state.currentProjectId || null) === selectionAtStart) {
              state.currentProjectId = createdProject.id
              state.currentProject = createdProject
            }
          }

          const result = await getApi().imports.upload(createdProject.id, file)
          try {
            const data = await getApi().projects.list()
            if (state) state.projects = mergeProject(data.items || data || [], createdProject)
          } catch {
            if (state) state.projects = mergeProject(state.projects, createdProject)
          }
          const selectionUnchanged = !state || [selectionAtStart, createdProject.id].includes(state.currentProjectId || null)
          if (state && selectionUnchanged) {
            state.currentProjectId = createdProject.id
            state.currentProject = createdProject
          }
          const nextStep = result.imported_chapters > 0
            ? "，可在写作台按需启动场景自动提取"
            : ""
          toast(`项目「${projectName}」已创建，共解析 ${result.total_chapters || 0} 章，已保存 ${result.imported_chapters || 0} 章为章节工作稿${nextStep}`, "success")
          getApi().clearCache()
          if (selectionUnchanged) {
            await getRouter().navigate("writing")
            await getRouter().refresh()
          }
        } catch (err) {
          const detail = err.message || "导入失败"
          if (!createdProject) {
            toast(detail.includes("格式") || detail.includes("大小") || detail.includes("限制") ? detail : `导入失败：${detail}`, "error")
            return
          }
          getApi().clearCache()
          const selectionUnchanged = !state || [selectionAtStart, createdProject.id].includes(state.currentProjectId || null)
          if (state) {
            state.projects = mergeProject(state.projects, createdProject)
            if (selectionUnchanged) {
              state.currentProjectId = createdProject.id
              state.currentProject = createdProject
            }
          }
          const location = selectionUnchanged ? "已保留并选中，可在项目页重新导入文件" : "已保留在项目列表，可稍后选择并重新导入文件"
          toast(`导入失败：${detail}。项目「${projectName}」${location}`, "error")
          if (selectionUnchanged) {
            await getRouter().navigate("project")
            await getRouter().refresh()
          }
        }
      },
      "创建并导入",
    )
  }
  input.click()
}
