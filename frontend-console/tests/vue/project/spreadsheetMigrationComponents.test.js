/**
 * 表格迁移组件测试 — ImportDrawer 页签（正文 accept 不变）、映射步骤与预览步骤。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount } from "@vue/test-utils"
import ImportDrawer from "../../../vue/views/project/components/ImportDrawer.vue"
import MigrationSheetMappingStep from "../../../vue/views/project/components/spreadsheetMigration/MigrationSheetMappingStep.vue"
import MigrationPreviewStep from "../../../vue/views/project/components/spreadsheetMigration/MigrationPreviewStep.vue"
import { resetBridgeOverrides, setBridgeOverrides } from "../../../vue/bridge/index.js"
import { IMPORT_FILE_ACCEPT, validateSpreadsheetFiles } from "../../../vue/composables/useImportUpload.js"

function makeState(currentProjectId = "p1", currentProject = { title: "测试项目" }) {
  const listeners = []
  const state = { currentProjectId, currentProject }
  return {
    state,
    onStateChange: (listener) => {
      listeners.push(listener)
      return () => listeners.splice(listeners.indexOf(listener), 1)
    },
    emit(key, value) {
      state[key] = value
      for (const listener of listeners) listener(key, value)
    },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  globalThis.api.imports.list = vi.fn(async () => ({ items: [] }))
  globalThis.api.imports.migrations = globalThis.api.imports.migrations || {}
  globalThis.api.imports.migrations.list = vi.fn(async () => ({ items: [], total: 0 }))
})

afterEach(() => {
  resetBridgeOverrides()
})

describe("ImportDrawer 页签", () => {
  it("默认展示导入正文页签，正文 accept 不变", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    expect(IMPORT_FILE_ACCEPT).toBe(".txt,.epub,.html,.htm")
    expect(wrapper.find("#pv-import-file").attributes("accept")).toBe(IMPORT_FILE_ACCEPT)
    expect(wrapper.find('[data-action="import-tab-spreadsheets"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="sm-panel"]').exists()).toBe(false)
  })

  it("切换到导入设定表格页签后渲染迁移面板", async () => {
    const harness = makeState()
    setBridgeOverrides({ state: harness.state, onStateChange: harness.onStateChange })
    const wrapper = mount(ImportDrawer)
    await wrapper.find('[data-action="import-tab-spreadsheets"]').trigger("click")
    expect(wrapper.find('[data-testid="sm-panel"]').exists()).toBe(true)
    expect(wrapper.find("#pv-import-file").exists()).toBe(false)
  })
})

describe("validateSpreadsheetFiles", () => {
  const file = (name, size = 100) => ({ name, size })

  it("拒绝空选择、超量、错误扩展名与超大文件", () => {
    expect(validateSpreadsheetFiles([])).toContain("请先选择")
    expect(validateSpreadsheetFiles(Array.from({ length: 6 }, (_, i) => file(`t${i}.csv`)))).toContain("最多")
    expect(validateSpreadsheetFiles([file("旧表.xls")])).toContain(".xlsx")
    expect(validateSpreadsheetFiles([file("大表.xlsx", 11 * 1024 * 1024)])).toContain("10MB")
    expect(validateSpreadsheetFiles([file("人物.xlsx"), file("关系.csv")])).toBeNull()
  })
})

describe("MigrationSheetMappingStep", () => {
  function makeSession() {
    return {
      revision: 2,
      sheets: [
        {
          sheet_key: "f0s0",
          file_key: "f0",
          name: "人物",
          hidden: false,
          kind: "characters",
          kind_suggested: true,
          header_row: 0,
          row_count: 3,
          columns: [
            { column_key: "c0", header: "姓名", target: "name", target_suggested: true },
            { column_key: "c1", header: "小传", target: "author_note", target_suggested: true },
          ],
          sample_rows: [["张三", "北军斥候"]],
          warnings: [],
        },
      ],
      options: { written_chapter_policy: "reference_only", outline_head_policy: "create_if_missing" },
    }
  }

  it("渲染列映射并可改投目标", async () => {
    const wrapper = mount(MigrationSheetMappingStep, { props: { session: makeSession(), saving: false } })
    const select = wrapper.find('[data-action="sm-target-f0s0-c1"]')
    expect(select.exists()).toBe(true)
    await select.setValue("hidden_truth")
    const save = wrapper.find('[data-action="sm-save-mapping"]')
    await save.trigger("click")
    const emitted = wrapper.emitted("save")
    expect(emitted).toBeTruthy()
    expect(emitted[0][0].sheets[0].columns).toEqual({ c0: "name", c1: "hidden_truth" })
  })

  it("空表头目标列表随表类型收窄", () => {
    const wrapper = mount(MigrationSheetMappingStep, { props: { session: makeSession(), saving: false } })
    const options = wrapper.findAll('[data-action="sm-target-f0s0-c0"] option')
    const values = options.map((option) => option.attributes("value"))
    expect(values).toContain("name")
    expect(values).toContain("role")
    expect(values).not.toContain("relation_type")
  })

  it("保存映射携带默认实体类型，缺省时省略该字段", async () => {
    const withDefault = makeSession()
    withDefault.sheets[0].default_entity_type = "character"
    const wrapper = mount(MigrationSheetMappingStep, { props: { session: withDefault, saving: false } })
    await wrapper.find('[data-action="sm-save-mapping"]').trigger("click")
    let emitted = wrapper.emitted("save")
    expect(emitted[0][0].sheets[0].default_entity_type).toBe("character")

    const withoutDefault = mount(MigrationSheetMappingStep, {
      props: { session: makeSession(), saving: false },
    })
    await withoutDefault.find('[data-action="sm-save-mapping"]').trigger("click")
    emitted = withoutDefault.emitted("save")
    expect(emitted[0][0].sheets[0]).not.toHaveProperty("default_entity_type")
  })

  it("设定表选项不含人物字段，但旧会话已选的当前值保留显示", () => {
    const session = makeSession()
    session.sheets[0] = {
      ...session.sheets[0],
      name: "地点",
      kind: "world_objects",
      columns: [
        { column_key: "c0", header: "名称", target: "name", target_suggested: true },
        { column_key: "c1", header: "性格", target: "personality", target_suggested: true },
      ],
    }
    const wrapper = mount(MigrationSheetMappingStep, { props: { session, saving: false } })
    const values = wrapper
      .findAll('[data-action="sm-target-f0s0-c1"] option')
      .map((option) => option.attributes("value"))
    expect(values).not.toContain("role")
    expect(values).toContain("personality")
    expect(values.indexOf("personality")).toBeGreaterThan(values.indexOf("ignore"))
  })
})

describe("MigrationPreviewStep", () => {
  function makeSession(overrides = {}) {
    return {
      revision: 4,
      preview: {
        preview_hash: "hash-1",
        validation_policy_active: false,
        counts: { create: 2, conflict: 1, relations: 1, structures: 1 },
        world_items: [
          {
            item_key: "w1",
            label: "张三",
            type_label: "人物",
            action: "create",
            fills: ["身份"],
            conflicts: [],
            similar: [],
            decision: "auto",
            source_sheet_name: "人物",
            source_row: 1,
          },
          {
            item_key: "w2",
            label: "李四",
            type_label: "人物",
            action: "conflict",
            conflicts: [
              { field_label: "简介", current_excerpt: "已有", incoming_excerpt: "表格" },
            ],
            decision: "auto",
            source_sheet_name: "人物",
            source_row: 2,
          },
        ],
        relations: [],
        structures: [
          { item_key: "s1", kind: "chapter_plan", label: "第1章", action: "reference_only" },
        ],
        outline: null,
        ...overrides,
      },
    }
  }

  it("无预览时显示空态", () => {
    const wrapper = mount(MigrationPreviewStep, {
      props: { session: { revision: 1, preview: null }, applying: false, savingDecisions: false },
    })
    expect(wrapper.find('[data-testid="sm-preview"]').text()).toContain("预览尚未生成")
  })

  it("渲染计数、冲突页签与决策选择", async () => {
    const wrapper = mount(MigrationPreviewStep, {
      props: { session: makeSession(), applying: false, savingDecisions: false },
    })
    expect(wrapper.find('[data-testid="sm-preview-counts"]').text()).toContain("新建 2")
    await wrapper.find('[data-action="sm-tab-conflicts"]').trigger("click")
    expect(wrapper.text()).toContain("李四")
    expect(wrapper.text()).toContain("已有")
    // 冲突项可改决策
    const select = wrapper.find('[data-action="sm-decision-w2"]')
    await select.setValue("skip")
    expect(wrapper.find('[data-action="sm-save-decisions"]').exists()).toBe(true)
  })

  it("决策选项按条目类型过滤：实体五项，关系与大纲两项", async () => {
    const session = makeSession({
      relations: [
        {
          item_key: "r1",
          source_label: "张三",
          target_label: "李四",
          action: "create",
          source_sheet_name: "关系",
          source_row: 1,
        },
      ],
    })
    const wrapper = mount(MigrationPreviewStep, {
      props: { session, applying: false, savingDecisions: false },
    })
    const entityActions = wrapper
      .findAll('[data-action="sm-decision-w1"] option')
      .map((option) => option.attributes("value"))
    expect(entityActions).toEqual(["auto", "different_object", "use_existing", "append_note", "skip"])

    const relationActions = await (async () => {
      await wrapper.find('[data-action="sm-tab-relations"]').trigger("click")
      return wrapper
        .findAll('[data-action="sm-decision-r1"] option')
        .map((option) => option.attributes("value"))
    })()
    expect(relationActions).toEqual(["auto", "skip"])

    // 大纲结构条目（带 kind，无 decision_scope 的旧会话形状）同样收窄
    const structureActions = await (async () => {
      await wrapper.find('[data-action="sm-tab-structures"]').trigger("click")
      return wrapper
        .findAll('[data-action="sm-decision-s1"] option')
        .map((option) => option.attributes("value"))
    })()
    expect(structureActions).toEqual(["auto", "skip"])
  })

  it("确认采用需要勾选确认", async () => {
    const wrapper = mount(MigrationPreviewStep, {
      props: { session: makeSession(), applying: false, savingDecisions: false },
    })
    const apply = wrapper.find('[data-action="sm-apply"]')
    expect(apply.attributes("disabled")).toBeDefined()
    await wrapper.find('[data-action="sm-apply-confirm"]').setValue(true)
    expect(apply.attributes("disabled")).toBeUndefined()
    await apply.trigger("click")
    const emitted = wrapper.emitted("apply")
    expect(emitted[0][0].expected_preview_hash).toBe("hash-1")
  })
})
