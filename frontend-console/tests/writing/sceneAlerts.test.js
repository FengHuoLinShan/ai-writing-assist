import { describe, expect, it } from "vitest"

import {
  buildSceneAlerts,
  sceneTextForChapter,
  summarizeSceneAlerts,
} from "../../views/writing/sceneAlerts.js"

const completeScene = {
  id: "s1",
  title: "旧港追逐",
  goal: "带走账本",
  core_conflict: "守卫封锁出口",
  emotional_beat: "紧张升级",
  pov_character_id: "c1",
  chapter_ids: ["12"],
}

describe("sceneAlerts", () => {
  it("只在当前 Scene 正文范围内做 must/must_not 字面提示", () => {
    const scene = {
      ...completeScene,
      must_happen: "拿到账本；离开码头",
      must_not_happen: "主角死亡",
      scene_chunks: [{ chapter_index: 12, start_pos: 4, end_pos: 15 }],
    }
    const alerts = buildSceneAlerts({
      scene,
      chapterIndex: 12,
      content: "前文无关拿到账本，主角死亡后文无关",
      latestCheck: { id: "check-1", draft_id: "d1", version_number: 3, items: [] },
      draftId: "d1",
      versionNumber: 3,
    })

    expect(alerts).toEqual(expect.arrayContaining([
      expect.objectContaining({ severity: "medium", message: "未检测到必须发生项「离开码头」" }),
      expect.objectContaining({ severity: "high", message: "检测到禁止发生项「主角死亡」" }),
    ]))
    expect(alerts.some((item) => item.message.includes("拿到账本"))).toBe(false)
  })

  it("组合 Scene 健康提示，但不做主观质量判断", () => {
    const alerts = buildSceneAlerts({
      scene: {
        id: "s1",
        chapter_ids: ["1"],
        needs_review: true,
        needs_organize: true,
      },
      chapterIndex: 1,
    })

    expect(alerts).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "结构", message: "场景尚未完成人工复核" }),
      expect.objectContaining({ source: "结构", message: "场景已标记为待整理" }),
    ]))
    expect(alerts.some((item) => /张力|更好|自然/.test(item.message))).toBe(false)
  })

  it("读取真实 Scene 响应中 structure_meta 的复核与整理状态", () => {
    const alerts = buildSceneAlerts({
      scene: {
        ...completeScene,
        structure_meta: { needs_review: true, needs_organize: true },
      },
      chapterIndex: 12,
      checkLoading: true,
    })

    expect(alerts).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: "structure-review" }),
      expect.objectContaining({ id: "structure-organize" }),
    ]))
  })

  it("正文未保存或检查身份不一致时明确标记最近校验过期", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      latestCheck: {
        id: "check-1",
        draft_id: "d1",
        version_number: 2,
        items: [{ severity: "high", status: "open" }],
      },
      draftId: "d1",
      versionNumber: 3,
      isDirty: true,
    })

    expect(alerts).toContainEqual(expect.objectContaining({
      stale: true,
      message: "正文已有未保存修改，最近校验已过期",
    }))
    expect(summarizeSceneAlerts(alerts)).toMatchObject({
      highestSeverity: "high",
      hasStaleCheck: true,
    })
  })

  it("正文保存后仍通过检查快照识别内容变化", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      content: "已保存的新正文",
      latestCheck: {
        id: "check-1",
        draft_id: "d1",
        version_number: 3,
        scope: { content_char_count: 4, content_excerpt: "旧正文" },
        items: [],
      },
      draftId: "d1",
      versionNumber: 3,
      isDirty: false,
    })

    expect(alerts).toContainEqual(expect.objectContaining({
      stale: true,
      message: "当前正文长度已变化，最近校验已过期",
    }))
  })

  it("按后端 Unicode 字符语义比较快照，不会把 emoji 误判为长度变化", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      content: "A😀B",
      latestCheck: {
        id: "check-unicode",
        draft_id: "d1",
        version_number: 3,
        scope: { content_char_count: 3, content_excerpt: "A😀B" },
        items: [],
      },
      draftId: "d1",
      versionNumber: 3,
    })

    expect(alerts.some((item) => item.stale)).toBe(false)
    expect(alerts).toContainEqual(expect.objectContaining({ id: "check-clear" }))
  })

  it("可从旧响应的 scope 读取工作稿身份", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      content: "正文",
      latestCheck: {
        id: "check-scoped",
        scope: {
          draft_id: "d1",
          version_number: 3,
          content_char_count: 2,
          content_excerpt: "正文",
        },
        items: [],
      },
      draftId: "d1",
      versionNumber: 3,
    })

    expect(alerts.some((item) => item.stale)).toBe(false)
  })

  it("当前版本明确时，不接受只记录 draft 而缺少 version 的检查", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      content: "正文",
      latestCheck: {
        id: "check-no-version",
        draft_id: "d1",
        scope: { content_char_count: 2, content_excerpt: "正文" },
        items: [],
      },
      draftId: "d1",
      versionNumber: 3,
    })

    expect(alerts).toContainEqual(expect.objectContaining({
      stale: true,
      message: "最近校验未记录正文版本，建议重新运行规则检查",
    }))
  })

  it("缺少版本身份的旧检查不会被误认为当前结果", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      latestCheck: { id: "legacy", items: [] },
      draftId: "d1",
      versionNumber: 3,
    })

    expect(alerts).toContainEqual(expect.objectContaining({
      stale: true,
      message: "最近校验未记录正文版本，建议重新运行规则检查",
    }))
  })

  it("最近校验来源失败时显示警报，不伪装为无问题", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      checkError: "最近校验暂不可用",
    })

    expect(alerts).toContainEqual(expect.objectContaining({
      severity: "low",
      source: "最近校验",
      message: "最近校验暂不可用",
    }))
    expect(summarizeSceneAlerts(alerts).actionableCount).toBe(1)
  })

  it("使用合法 chunk 范围，并在范围缺失时退回整章", () => {
    const scene = { scene_chunks: [{ chapter_index: 1, start_pos: 2, end_pos: 5 }] }
    expect(sceneTextForChapter(scene, 1, "0123456789")).toBe("234")
    expect(sceneTextForChapter({ chapter_ids: ["1"] }, 1, "整章正文")).toBe("整章正文")
  })

  it("有 Scene chunk 但范围失效时跳过字面判定，不扫描其他 Scene 正文", () => {
    const scene = {
      ...completeScene,
      must_happen: "拿到账本",
      must_not_happen: "主角死亡",
      scene_chunks: [{ chapter_index: 12, start_pos: 100, end_pos: 120 }],
    }
    const alerts = buildSceneAlerts({
      scene,
      chapterIndex: 12,
      content: "其他 Scene 中主角死亡",
      checkLoading: true,
    })

    expect(sceneTextForChapter(scene, 12, "短正文")).toBe("")
    expect(alerts).toContainEqual(expect.objectContaining({ id: "prose-scope-unavailable" }))
    expect(alerts.some((item) => item.id.startsWith("prose-required-"))).toBe(false)
    expect(alerts.some((item) => item.id.startsWith("prose-forbidden-"))).toBe(false)
  })

  it("最近校验加载中不会提前声称无检查记录", () => {
    const alerts = buildSceneAlerts({
      scene: completeScene,
      chapterIndex: 12,
      checkLoading: true,
    })

    expect(alerts.some((item) => item.id === "check-missing")).toBe(false)
  })

  it("没有 Scene 时不制造警报", () => {
    expect(buildSceneAlerts({ scene: null, content: "正文" })).toEqual([])
  })
})
