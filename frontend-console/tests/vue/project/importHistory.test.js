import { describe, expect, it } from "vitest"
import {
  IMPORT_FAILURE_FALLBACK,
  IMPORT_FAILURE_MESSAGE_MAX_LENGTH,
  importFailureMessage,
} from "../../../vue/views/project/logic/importHistory.js"

describe("importFailureMessage", () => {
  it("保留有用的作者失败原因并规整空白", () => {
    expect(importFailureMessage({
      status: "failed",
      error_message: " 文件中未检测到有效章节\n请检查内容 ",
    })).toBe("文件中未检测到有效章节 请检查内容")
  })

  it("只为失败记录生成原因", () => {
    expect(importFailureMessage({ status: "done", error_message: "不应显示" })).toBeNull()
    expect(importFailureMessage({ status: "processing", error_message: "不应显示" })).toBeNull()
    expect(importFailureMessage({ status: "pending", error_message: "不应显示" })).toBeNull()
  })

  it("空白或技术诊断收敛为导入回退", () => {
    expect(importFailureMessage({ status: "failed", error_message: "  " })).toBe(IMPORT_FAILURE_FALLBACK)
    expect(importFailureMessage({
      status: "failed",
      error_message: "traceback: sqlalchemy asyncpg failed [sql: UPDATE async_tasks]",
    })).toBe(IMPORT_FAILURE_FALLBACK)
  })

  it("将过长原因截断在作者可读上限内", () => {
    const result = importFailureMessage({ status: "failed", error_message: "甲".repeat(350) })
    expect(Array.from(result)).toHaveLength(IMPORT_FAILURE_MESSAGE_MAX_LENGTH)
    expect(result).toMatch(/…$/)
  })

  it("在 emoji 边界按 code point 截断，不留下半个代理项", () => {
    const result = importFailureMessage({
      status: "failed",
      error_message: `${"甲".repeat(298)}😀尾巴`,
    })

    expect(result).toBe(`${"甲".repeat(298)}😀…`)
    expect(Array.from(result)).toHaveLength(IMPORT_FAILURE_MESSAGE_MAX_LENGTH)
  })
})
