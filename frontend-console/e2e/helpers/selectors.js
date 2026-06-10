/**
 * 统一 DOM 选择器常量
 */

export const SEL = {
  // 顶部状态栏
  topbarTitle: ".logo",
  topbarProject: "#topbar-project",
  topbarStatus: "#topbar-status",

  // 侧边栏
  sidebar: "#sidebar",
  navItem: (view) => `[data-view="${view}"]`,

  // 工作区
  workspace: "#workspace",
  workspaceContent: "#workspace-content",
  viewTitle: "#view-title",
  viewActions: "#view-actions",

  // 空态 / 加载
  emptyState: ".empty-state",
  loading: ".loading",

  // 数据表格
  dataTable: ".data-table",
  tableRow: (id) => `tr[data-id="${id}"]`,
  clickableRow: "tr.clickable",

  // 项目卡片
  projectGrid: ".project-grid",
  projectCard: (id) => `.project-card[data-id="${id}"]`,

  // 按钮
  btnPrimary: ".btn-primary",
  btnDanger: ".btn-danger",
  btnSm: ".btn-sm",

  // 模态框
  modalOverlay: "#modal-overlay",
  modalTitle: "#modal-title",
  modalBody: "#modal-body",
  modalFooter: "#modal-footer",
  modalClose: "#modal-close",

  // 表单
  formInput: ".form-input",
  formSelect: ".form-select",
  formTextarea: ".form-textarea",

  // Toast
  toastContainer: "#toast-container",

  // 命令栏
  commandInput: "#command-input",
  commandPrompt: "#command-prompt",
  commandBar: "#command-bar",

  // 帮助
  helpOverlay: "#help-overlay",
  helpClose: "#help-close",

  // 右侧批注区
  contextualNotes: "#contextual-notes",

  // 子标签
  subnavItem: (sub) => `[data-subview="${sub}"]`,
}
