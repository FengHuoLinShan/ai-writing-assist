import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { describe, expect, it } from "vitest"

describe("资料库 390px 触控目标", () => {
  it("保持任务行、来源链接、对象返回和别名折叠至少 44px", () => {
    const styles = readFileSync(resolve(import.meta.dirname, "../../../styles.css"), "utf8")
    const detail = readFileSync(resolve(import.meta.dirname, "../../../vue/views/world/library/WorldEntityDetail.vue"), "utf8")

    expect(styles).toMatch(/@media \(max-width: 390px\)[\s\S]*\.author-task-row,[\s\S]*button\.author-task-source\s*\{[^}]*min-height:\s*44px/s)
    expect(detail).toMatch(/@media \(max-width: 390px\)[\s\S]*\.world-entity-detail__back,\s*\.world-entity-detail__aliases summary\s*\{[^}]*min-height:\s*44px/s)
  })
})
