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
  viewTitle: "#topbar-module",
  projectCreateTitle: "#create-title",
  errorLogBadge: "#error-log-badge",
  errorLogPanel: "#error-log-panel",

  // 空态 / 加载
  emptyState: ".empty-state",
  loading: ".loading",
  loadingSkeleton: ".loading-skeleton",

  // 数据表格
  dataTable: ".data-table",
  tableRow: (id) => `tr[data-id="${id}"]`,
  clickableRow: "tr.clickable",

  // 项目卡片
  projectGrid: ".project-grid",
  projectCard: (id) => `.project-card[data-id="${id}"]`,
  projectCreatePlaceholder: '.project-card-placeholder[data-action="new"]',
  projectSelectVisible: '[data-action="select-visible-projects"]',
  projectImportToggle: '[data-action="toggle-import"]',
  projectImportFile: "#pv-import-file",
  projectImportSubmit: '[data-action="upload-file"]',
  projectImportNewProject: '.project-import-drawer [data-action="import"]',
  projectImportHistory: "#import-list-body",
  projectImportHistoryRetry: '[data-action="retry-import-history"]',
  projectRecycleBin: '[data-action="recycle-bin"]',
  projectRecycleSelectAll: "#recycle-select-all",
  projectRecycleBulkRestore: "#recycle-bulk-restore",
  projectRecycleBulkDelete: "#recycle-bulk-delete",
  projectRecycleCheckbox: (id) => `.recycle-project-checkbox[data-id="${id}"]`,

  // 按钮
  btnPrimary: ".btn-primary",
  btnDanger: ".btn-danger",
  btnSm: ".btn-sm",

  // 模态框
  modalOverlay: "#modal-overlay",
  modalContent: "#modal-content",
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
  toastItems: "#toast-container > *",

  // 主题
  themeGroup: ".topbar-theme",
  themeOption: (theme) => `.theme-dot[data-theme-value="${theme}"]`,

  // 写作台
  writingToolbar: ".writing-toolbar",
  writingWorkspace: ".writing-workspace-layout",
  writingTreeRail: ".writing-tree-rail",
  writingChapterCount: ".writing-tree-rail .chapter-tree-title",
  writingPanelRail: ".writing-panel-rail",
  writingEditorContainer: "#writing-editor-container",
  writingEditor: "#writing-editor",
  writingSheet: ".writing-sheet",
  writingSceneLabel: ".scene-cockpit-switcher__item",
  writingSceneCockpit: ".scene-cockpit",
  mobileQuickNote: ".mobile-quick-note",
  mobileNoteEditor: "#mobile-note-editor",
  writingAiMenu: '[data-action="writing-ai-menu"]',
  writingToolsMenu: '[data-action="writing-more-menu"]',
  deepImportProgress: "#writing-deep-import-bar-container",
  deepImportMapNext: '[data-action="deep-import-map-next"]',

  // 世界书
  worldBibleWorkspace: ".world-bible-workspace",
  worldBibleNewResource: '#sidebar-context-slot [data-action="bible-new-resource"]',
  worldBibleNewPageChoice: '[data-action="bible-new-page-choice"]',
  worldBibleCreateTitle: "#bible-create-title",
  worldBibleSavePage: '[data-action="bible-save-page"]',
  worldBiblePublishPage: '[data-action="bible-publish-page"]',
  worldBibleImproveWithAi: '[data-action="bible-improve-with-ai"]',

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
