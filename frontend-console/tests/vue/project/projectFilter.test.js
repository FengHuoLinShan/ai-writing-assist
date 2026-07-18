/**
 * 项目列表纯逻辑测试 — 对应原 tests/projectView.test.js 的排序/过滤/统计用例。
 */
import { describe, it, expect } from "vitest"
import {
  filterProjects,
  formatRelativeTime,
  projectActivityMs,
  projectActivityTime,
  projectCountLabel,
  projectMonogram,
  projectName,
  projectStats,
  sortedProjects,
  stageLabel,
} from "../../../vue/views/project/logic/projectFilter.js"

const base = (id, overrides = {}) => ({ id, title: `项目${id}`, ...overrides })

describe("sortedProjects", () => {
  it("当前项目置顶，其余按活跃倒序，再按名称", () => {
    const projects = [
      base("a", { updated_at: "2026-07-01T00:00:00Z" }),
      base("b", { updated_at: "2026-07-03T00:00:00Z" }),
      base("c", { updated_at: "2026-07-02T00:00:00Z" }),
    ]
    expect(sortedProjects(projects).map((p) => p.id)).toEqual(["b", "c", "a"])
    expect(sortedProjects(projects, "a").map((p) => p.id)).toEqual(["a", "b", "c"])
  })

  it("缺少时间字段不报错", () => {
    expect(() => sortedProjects([base("a"), base("b")])).not.toThrow()
  })
})

describe("filterProjects", () => {
  it("按名称包含过滤（大小写不敏感），空查询返回全部", () => {
    const projects = [base("a", { title: "星际旅人" }), base("b", { title: "古城谜案" })]
    expect(filterProjects(projects, "星际").map((p) => p.title)).toEqual(["星际旅人"])
    expect(filterProjects(projects, "  ")).toHaveLength(2)
    expect(filterProjects(projects, "不存在")).toHaveLength(0)
  })
})

describe("projectStats", () => {
  it("多字段回退与待接入文案", () => {
    expect(projectStats(base("a", { total_words: 12000, chapter_count: 3 }))).toMatchObject({
      wordCountText: "12,000",
      chapterCountText: "3",
      wordCountTitle: "总字数",
    })
    expect(projectStats(base("a", { word_count: 500 })).wordCountText).toBe("500")
    expect(projectStats(base("a", { statistics: { total_words: 800 } })).wordCountText).toBe("800")
    expect(projectStats(base("a"))).toMatchObject({
      wordCountText: "待接入",
      chapterCountText: "待接入",
      wordCountTitle: "统计接入后显示总字数",
    })
  })
})

describe("时间显示", () => {
  it("projectActivityMs 回退与非法值", () => {
    expect(projectActivityMs(base("a", { last_active_at: "2026-07-01T00:00:00Z" }))).toBeGreaterThan(0)
    expect(projectActivityMs(base("a", { last_active_at: "not-a-date" }))).toBe(0)
    expect(projectActivityMs(base("a"))).toBe(0)
  })

  it("formatRelativeTime 分段", () => {
    const now = Date.now()
    expect(formatRelativeTime(new Date(now - 30 * 1000))).toBe("刚刚活跃")
    expect(formatRelativeTime(new Date(now - 5 * 60 * 1000))).toBe("5 分钟前活跃")
    expect(formatRelativeTime(new Date(now - 3 * 3600 * 1000))).toBe("3 小时前活跃")
    expect(formatRelativeTime(new Date(now - 2 * 86400 * 1000))).toBe("2 天前活跃")
    expect(formatRelativeTime("not-a-date")).toBe("暂无活跃")
  })

  it("projectActivityTime 无数据回退", () => {
    expect(projectActivityTime(base("a"))).toEqual({ relative: "暂无活跃", full: "暂无活跃时间" })
  })
})

describe("标签与名称", () => {
  it("stageLabel 映射与回退", () => {
    expect(stageLabel("world_building")).toBe("世界构建")
    expect(stageLabel("custom-stage")).toBe("custom-stage")
  })

  it("projectCountLabel", () => {
    expect(projectCountLabel(2, 5)).toBe("显示 2 / 共 5 个项目")
  })

  it("projectName 回退", () => {
    expect(projectName({ title: "x" })).toBe("x")
    expect(projectName({ name: "y" })).toBe("y")
    expect(projectName({})).toBe("未命名项目")
  })

  it("projectMonogram 取前两个字", () => {
    expect(projectMonogram({ title: "星际旅人" })).toBe("星际")
    expect(projectMonogram({ title: " " })).toBe("新作")
  })
})
