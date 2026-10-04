import { afterEach, describe, expect, it, vi } from "vitest"

import {
  ENTITY_REVISION_FIELD_LABELS,
  PAGE_REVISION_FIELD_LABELS,
  REVISION_REASON_LABELS,
  formatChangedFields,
  formatFullTime,
  formatRelativeTime,
  formatWritingProgress,
  revisionReasonLabel,
} from "../../shared/revisionHistory.js"

describe("revisionHistory 原因词典", () => {
  it("§6.5 词条完整且映射到作者语言", () => {
    expect(REVISION_REASON_LABELS).toMatchObject({
      manual_update: "手动编辑",
      manual_promote: "采用为正式设定",
      focused_completion: "采用了 AI 补全",
      focused_completion_rollback: "撤销了 AI 补全",
      rollback: "恢复到旧版本",
      manual_delete: "移除了这个设定",
      redundant_alias_resolution: "整理了重复别名",
      spreadsheet_migration_rollback: "撤销了表格导入",
      ai_import: "导入时记录",
      manual_publish: "发布了这一版",
      legacy_create: "最初版本",
      legacy_update: "早期更新",
      create: "新建模板",
      update: "修改模板",
      restore: "恢复旧版模板",
    })
  })

  it("未知或缺失原因显示其他改动，不暴露内部枚举", () => {
    expect(revisionReasonLabel("something_new")).toBe("其他改动")
    expect(revisionReasonLabel("")).toBe("其他改动")
    expect(revisionReasonLabel(null)).toBe("其他改动")
    expect(revisionReasonLabel(undefined)).toBe("其他改动")
  })
})

describe("revisionHistory 时间与写作进度", () => {
  afterEach(() => vi.useRealTimers())

  it("相对时间与 formatBatchTime 语义一致（刚刚/分钟/小时/昨天/日期）", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-10-04T15:00:00"))
    expect(formatRelativeTime("2026-10-04T15:00:00")).toBe("刚刚")
    expect(formatRelativeTime("2026-10-04T14:30:00")).toBe("30 分钟前")
    expect(formatRelativeTime("2026-10-04T12:00:00")).toBe("3 小时前")
    expect(formatRelativeTime("2026-10-03T15:00:00")).toBe("昨天 15:00")
    expect(formatRelativeTime("2026-09-20T10:00:00")).toBe("09-20 10:00")
    expect(formatRelativeTime("2024-05-01T10:00:00")).toBe("2024-05-01 10:00")
  })

  it("无效与空时间原样返回空串或原值", () => {
    expect(formatRelativeTime("")).toBe("")
    expect(formatFullTime("")).toBe("")
    expect(formatRelativeTime("not-a-date")).toBe("not-a-date")
  })

  it("绝对时间格式为 YYYY-MM-DD HH:MM", () => {
    expect(formatFullTime("2026-10-04T09:05:00")).toBe("2026-10-04 09:05")
  })

  it("写作进度：NULL 不显示、0 动笔前、N 写到第 N 章时", () => {
    expect(formatWritingProgress(null)).toBe("")
    expect(formatWritingProgress(undefined)).toBe("")
    expect(formatWritingProgress(0)).toBe("动笔前")
    expect(formatWritingProgress(7)).toBe("写到第 7 章时")
  })
})

describe("revisionHistory 改动字段", () => {
  it("实体字段用现有界面叫法并去重", () => {
    expect(ENTITY_REVISION_FIELD_LABELS.hidden_truth).toBe("作者秘密")
    expect(ENTITY_REVISION_FIELD_LABELS.summary).toBe("概要")
    expect(formatChangedFields(["summary", "hidden_truth", "summary"])).toBe("概要、作者秘密")
  })

  it("空或缺失字段返回 null，界面不显示该行", () => {
    expect(formatChangedFields(null)).toBeNull()
    expect(formatChangedFields([])).toBeNull()
    expect(formatChangedFields(undefined)).toBeNull()
  })

  it("未收录的键合并为兜底标签，不暴露内部键名", () => {
    expect(formatChangedFields(["name", "mystery_field"], { labels: PAGE_REVISION_FIELD_LABELS })).toBe("其他内容")
    expect(formatChangedFields(["free_text", "mystery_field"], { labels: PAGE_REVISION_FIELD_LABELS })).toBe("正文、其他内容")
    expect(formatChangedFields(["unknown_only"])).toBe("其他内容")
  })
})
