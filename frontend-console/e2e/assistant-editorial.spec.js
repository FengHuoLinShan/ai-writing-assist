/**
 * G5a 编辑闭环 E2E：真实 API / worker / SQL + 合成 provider（零模型费用）。
 *
 * 与 editorial.spec.js / editorial-revision-bridge.spec.js 的 page.route 模拟不同，
 * 本文件跑在 playwright.assistant.config.js 的 browser harness 上：
 * 保存正文 → 交给编辑 → 真实审读 worker → 意见处置 → BR-4 桥接批注修订
 * （真实 writing_comment_run + 知识治理审计）→ 采用后改后复核（真实
 * assistant_editorial_recheck）→ 正文变化后的 stale 冲突、停止/继续与离开恢复。
 *
 * 模型回复脚本见 backend/tests/support/assistant_editorial_provider.py；
 * 验收口径取画像 A：不越权、不静默覆盖正文、切页刷新不丢进度、长任务可离开。
 */
import { test, expect } from "./fixtures.js"
import { createAutosavedDraft } from "./helpers/api-client.js"
import { waitWritingReady } from "./helpers/workbench.js"

const SLOW_SENTENCE = "这一段审读会刻意放慢，方便核对停止与继续。"
const FAIL_SENTENCE = "这一段审读会失败，编辑拿不到有效结论。"
// 合成 provider 对这句只回半个对象「{」：客户端截断恢复会补全成「{}」，
// 收紧后的 schema 让空对象不合法，审读必须失败而不是“零意见完成”（G2）。
const TRUNCATED_SENTENCE = "这一段审读会返回截断输出，模型只吐出半个对象。"
const CLOSED_LOOP_BODY = "雾港的旧钟在午夜敲了十三下，码头没有人应答。\n信封上的地址指向旧港，却盖着新港的邮戳。"
const EDITORIAL_JUDGMENT = "两处地名线索互相矛盾，建议统一口径"

async function ensureAssistantOpen(page) {
  const panel = page.locator("#project-assistant-panel")
  if (!(await panel.isVisible())) await page.getByRole("button", { name: "项目助手", exact: true }).click()
  await expect(panel).toBeVisible()
  return panel
}

async function openEditorialDesk(page) {
  const panel = await ensureAssistantOpen(page)
  await panel.getByRole("button", { name: "编辑台" }).click()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  return desk
}

async function expandHistory(card) {
  const history = card.locator("details").filter({ hasText: "处理与复核历史" }).first()
  if ((await history.getAttribute("open")) === null) await history.getByText("处理与复核历史", { exact: true }).click()
}

test("编辑台首次进入与空态在桌面和 390px 下不误报进度", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "编辑台闭环 · 首次进入" })
  await openProjectWorkbench(project, "writing")
  const desk = await openEditorialDesk(page)
  await expect(desk.getByText("还没有编辑意见。没有提醒不等于全书已检查。")).toBeVisible()
  // 首次进入自动展开编辑约定（第 0 版），不强迫作者先理解后台概念
  const brief = desk.locator("details").filter({ hasText: "编辑约定" })
  await expect(brief).toHaveAttribute("open", "")
  await expect(brief).toContainText("第 0 版")
  await expect(desk.getByRole("button", { name: "保存编辑约定" })).toBeEnabled()
  await desk.locator("summary").filter({ hasText: "主动跟进" }).click()
  await expect(desk.locator("summary").filter({ hasText: "主动跟进" })).toContainText("未开启")
  await expect(desk.getByText("后台编辑当前未开放；手动审读仍可使用。")).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-empty-desktop.png"), fullPage: true })

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator("#project-assistant-panel")).toHaveAttribute("role", "dialog")
  await expect(desk.getByText("还没有编辑意见。没有提醒不等于全书已检查。")).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-empty-390px.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})

test("保存正文交给编辑后走真实审读、处置、批注修订与改后复核闭环", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "编辑台闭环 · 全链路" })
  await createAutosavedDraft(project.id, 1, "雾港来信", CLOSED_LOOP_BODY)
  await openProjectWorkbench(project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()

  // 主路径入口：本章写完 → 交给编辑看（保存的正文交给编辑台）
  const ready = page.getByRole("button", { name: "本章写完，交给编辑看" })
  await expect(ready).toBeEnabled()
  await ready.click()
  await expect(page.getByText("这版工作稿已交编辑；可在编辑台查看或开始审读。")).toBeVisible()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  await expect(page.getByRole("button", { name: "本版已交编辑" })).toBeVisible()

  // 作者先保存编辑约定（真实版本化 brief），审读依据随后冻结
  await desk.getByLabel("希望保留的叙述声音").fill("保留迟疑的第一人称，不把地名说死")
  await desk.getByRole("button", { name: "保存编辑约定" }).click()
  await expect(desk.getByText("编辑约定已保存。旧报告仍保留原依据。")).toBeVisible()

  // 真实 worker 审读（合成 provider）：等待终态而不是依赖轮询时序
  await desk.getByRole("button", { name: "开始审读已保存正文" }).click()
  await expect(desk.getByText(/已完成 · 已查 1 章，未查 0 章/)).toBeVisible({ timeout: 30000 })
  await expect(desk.getByText("先处理以下最有影响的意见；其他问题可展开查看")).toBeVisible()

  const editorialCard = desk.locator(".editorial-issue").filter({ hasText: EDITORIAL_JUDGMENT })
  await expect(editorialCard).toBeVisible({ timeout: 10000 })
  await editorialCard.locator("summary").filter({ hasText: "依据、反证和处理方向" }).click()
  await expect(editorialCard.getByText("信封上的地址指向旧港")).toBeVisible()
  await expect(editorialCard.getByText("代价：悬念持续更久")).toBeVisible()
  const readerCard = desk.locator(".editorial-issue").filter({ hasText: "旧钟异象让读者过早期待超自然解释" })
  await expect(readerCard).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-review-completed.png"), fullPage: true })

  // 意见处置：记录作者决定（真实决定历史）
  await editorialCard.getByLabel("我的决定").selectOption("prepare")
  await editorialCard.getByLabel(/原因或备忘/).fill("下一章前统一地名口径")
  await editorialCard.getByRole("button", { name: "保存决定" }).click()
  await expect(editorialCard.locator(".editorial-issue__head")).toContainText("准备处理")
  await expandHistory(editorialCard)
  await expect(editorialCard.getByText("下一章前统一地名口径")).toBeVisible()

  // BR-4 桥接：选中意见 → 处置说明 → 真实 writing_comment_run（导演/补丁/审计全走真路径）
  await editorialCard.getByRole("checkbox", { name: /加入批注修订/ }).check()
  const revisionPanel = desk.locator(".editorial-desk__revision")
  await revisionPanel.getByLabel(/处置说明/).fill("把地址改成模糊表述，延后确认")
  await revisionPanel.getByRole("button", { name: "发起 1 条修订" }).click()
  await expect(revisionPanel.getByText("替换候选已生成")).toBeVisible({ timeout: 30000 })
  // 回执如实提示采用前置：先独立审稿，通过后才能采用（G1）
  await expect(revisionPanel.getByText("写作页会先对这份候选做一次独立审稿")).toBeVisible()
  await revisionPanel.getByRole("button", { name: "去写作页完成独立审稿并采用" }).click()
  await expect(page).toHaveURL(/writing/)
  // 候选采用的独立审稿→采用门禁属写作页既有流程，写作页会引导先「运行独立语义审查」。
  // 这里回到编辑台继续处置。

  // 作者改稿后标记“已自行修改”，对真实新版本发起改后复核（真实 assistant_editorial_recheck worker）
  await createAutosavedDraft(project.id, 1, "雾港来信", `${CLOSED_LOOP_BODY}\n作者补写了一段，但地名表述未动。`)
  await ensureAssistantOpen(page)
  await desk.getByRole("button", { name: "刷新", exact: true }).click()
  await expect(editorialCard.getByText("正文已变化，这条旧意见需要重新核对。")).toBeVisible({ timeout: 10000 })
  await editorialCard.getByLabel("我的决定").selectOption("modified")
  await editorialCard.getByLabel(/原因或备忘/).fill("已在工作稿里自行调整")
  await editorialCard.getByRole("button", { name: "保存决定" }).click()
  await editorialCard.getByRole("button", { name: "重新检查修改" }).click()
  await expandHistory(editorialCard)
  await expect(editorialCard.getByText("改后复核：问题仍在")).toBeVisible({ timeout: 30000 })
  for (const forbidden of ["问题已解决", "已核实修复"]) {
    await expect(desk.getByText(forbidden)).toHaveCount(0)
  }
  await page.screenshot({ path: testInfo.outputPath("editorial-bridge-recheck.png"), fullPage: true })

  // 处置冲突（正文已变 stale）：旧意见保留但不允许静默发起修订
  await expect(desk.getByText("依据已变化；旧意见保留供回看，请对当前正文重新审读。")).toBeVisible({ timeout: 10000 })
  await expect(editorialCard.getByRole("checkbox", { name: /加入批注修订/ })).toBeDisabled()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator("#project-assistant-panel")).toHaveAttribute("role", "dialog")
  await expect(desk.getByText("依据已变化；旧意见保留供回看，请对当前正文重新审读。")).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-stale-390px.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})

test("审读失败落到未完成终态：坏输出按失败处理，作者语言提示且诊断收进次级入口", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "编辑台闭环 · 审读失败" })
  await createAutosavedDraft(project.id, 1, "失败样章", FAIL_SENTENCE)
  await openProjectWorkbench(project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await page.getByRole("button", { name: "本章写完，交给编辑看" }).click()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  await desk.getByRole("button", { name: "开始审读已保存正文" }).click()
  await expect(desk.getByText(/未完成 · 已查 0 章，未查 1 章/)).toBeVisible({ timeout: 30000 })
  // 失败提示是作者语言，不直接透出英文内部诊断（G3）
  await expect(desk.locator(".editorial-desk__error").first()).toHaveText(
    "这次审读没有完成，已保存的分段仍保留，可点“继续未完成部分”重试。"
  )
  // 技术诊断只出现在折叠的次级入口里，展开后可见
  const failureDetail = desk.locator(".editorial-desk__error-detail")
  await expect(failureDetail).toHaveCount(1)
  await expect(failureDetail).not.toHaveAttribute("open", "")
  await failureDetail.locator("summary").click()
  await expect(failureDetail.getByText(/attempts failed/)).toBeVisible()
  // 失败是终态：明确下一步是继续未完成部分，而不是永远“审读中”
  await expect(desk.getByRole("button", { name: "停止本次审读" })).toHaveCount(0)
  await expect(desk.getByRole("button", { name: "继续未完成部分" })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-failed.png"), fullPage: true })

  // 截断输出被客户端恢复成空对象后不得算作“零意见完成”（G2）：
  // 空对象违反收紧后的 ReviewPass schema，同样落到未完成终态。
  await createAutosavedDraft(project.id, 2, "截断样章", TRUNCATED_SENTENCE)
  await desk.getByLabel("起始章").fill("2")
  const submission = page.waitForResponse(response => response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/assistant/editorial/reviews")
  await desk.getByRole("button", { name: "开始审读已保存正文" }).click()
  const receipt = await submission
  expect(receipt.ok()).toBe(true)
  const truncatedReview = await receipt.json()
  // 绑定本次回执，避免相同失败文案误匹配上一份意见书。
  await expect(desk.getByLabel("选择审稿记录")).toHaveValue(truncatedReview.id)
  await expect(desk.getByText(/未完成 · 已查 0 章，未查 1 章/)).toBeVisible({ timeout: 30000 })
  await expect(desk.getByText("尚未检查：2 章。")).toBeVisible()
  await expect(desk.locator(".editorial-desk__error").first()).toHaveText(
    "这次审读没有完成，已保存的分段仍保留，可点“继续未完成部分”重试。"
  )
  await expect(desk.getByText("所查范围内暂无值得打断作者的主要问题")).toHaveCount(0)
  await expect(desk.getByText("先处理以下最有影响的意见；其他问题可展开查看")).toHaveCount(0)
  await expect(desk.getByRole("button", { name: "继续未完成部分" })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-truncated-failed.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})

test("审读可停止，刷新离开不丢进度，停止后可继续到完成", async ({ page, projectFactory, openProjectWorkbench, browserErrors }, testInfo) => {
  const project = await projectFactory({ title: "编辑台闭环 · 停止与恢复" })
  await createAutosavedDraft(project.id, 1, "慢速样章", `${SLOW_SENTENCE}\n${CLOSED_LOOP_BODY}`)
  await openProjectWorkbench(project, "writing")
  await waitWritingReady(page, { chapter: 1 })
  await page.getByRole("button", { name: /^打开第 1 章/ }).click()
  await page.getByRole("button", { name: "本章写完，交给编辑看" }).click()
  const desk = page.getByLabel("编辑台", { exact: true })
  await expect(desk).toBeVisible()
  await desk.getByRole("button", { name: "开始审读已保存正文" }).click()
  await expect(desk.locator(".editorial-desk__status").filter({ hasText: /等待审读|审读中/ })).toBeVisible({ timeout: 10000 })

  // 长任务可离开：作者主动停止，分段与回执保留
  await desk.getByRole("button", { name: "停止本次审读" }).click()
  await expect(desk.getByText(/已停止 · 已查 0 章，未查 1 章/)).toBeVisible({ timeout: 15000 })
  await expect(desk.getByText("作者已停止；已完成的分段仍保留")).toBeVisible()

  // 刷新（切页/换设备等价）后进度不丢：服务端记录仍在，可从停点继续
  await page.reload()
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  const restored = await openEditorialDesk(page)
  await expect(restored.getByText(/已停止 · 已查 0 章，未查 1 章/)).toBeVisible({ timeout: 10000 })
  await restored.getByRole("button", { name: "继续未完成部分" }).click()
  await expect(restored.getByText(/已完成 · 已查 1 章，未查 0 章/)).toBeVisible({ timeout: 30000 })
  await expect(restored.locator(".editorial-issue").filter({ hasText: EDITORIAL_JUDGMENT })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("editorial-resumed.png"), fullPage: true })
  expect(browserErrors).toEqual([])
})
