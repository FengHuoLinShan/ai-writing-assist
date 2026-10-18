import { test, expect } from "./fixtures.js"
import { readFile } from "node:fs/promises"
import { API_BASE, createEntity } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectActionReachable, expectResponsiveLayout } from "./helpers/responsive.js"

test("作者可在 390/1280 宽度配置借用面向并保存秘密档案", async ({
  page,
  projectFactory,
}) => {
  const project = await projectFactory({ title: "灵兽档案响应式验收" })
  const entity = await createEntity(project.id, {
    name: "浏览器验收灵兽",
    entity_type: "spirit_beast",
    status: "canonical",
  })

  await openWorkbench(page, project, "world", "bible")
  await page.evaluate(async (entityId) => {
    await window.router.navigate(
      "world",
      "bible",
      true,
      new URLSearchParams({ entity_id: entityId }),
    )
  }, entity.id)
  const detail = page.locator(".world-entity-detail")
  await expect(detail).toBeVisible()
  const dossierPanel = detail.locator("details.world-entity-dossier")
  await detail.getByRole('tab', { name: '设定档案', exact: true }).click()
  await dossierPanel.locator("summary").click()
  const editor = dossierPanel.locator(".object-dossier-editor")
  await expect(editor.getByText("新增档案条目", { exact: true })).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await expectResponsiveLayout(page)
  const borrowed = editor.locator(".object-dossier-editor__borrowed-facings")
  const borrowedSummary = borrowed.locator("summary")
  await borrowedSummary.focus()
  await page.keyboard.press("Space")
  await expect(borrowed).toHaveAttribute("open", "")
  await editor.getByLabel("来源对象类型").selectOption("character")
  await editor.getByLabel("来源面向").selectOption("appearance")
  await borrowed.getByRole("button", { name: "添加借用", exact: true }).click()
  const saveTemplate = editor.getByRole("button", { name: "保存模板", exact: true })
  await expectActionReachable(saveTemplate)
  await saveTemplate.click()
  await expect(editor.getByRole("status")).toContainText("模板已保存为第 1 版")
  await expectResponsiveLayout(page)

  await page.setViewportSize({ width: 1280, height: 800 })
  await expectResponsiveLayout(page)
  await editor.getByLabel("档案面向").selectOption("core:borrowed:character:appearance")
  await editor.getByLabel("内容", { exact: true }).fill("只对作者可见的灵兽观察")
  await editor.getByLabel("可见范围").selectOption("secret")
  const saveEntry = editor.getByRole("button", { name: "保存档案条目", exact: true })
  await expectActionReachable(saveEntry)
  await saveEntry.click()
  await expect(editor.getByText("只对作者可见的灵兽观察", { exact: true })).toBeVisible()
  await expect(editor.locator(".object-dossier-editor__secret")).toHaveText("作者秘密")

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1280, height: 800 },
  ]) {
    await page.setViewportSize(viewport)
    await expectResponsiveLayout(page)
    await expectActionReachable(editor.getByRole("button", { name: "重新读取", exact: true }))
  }

  const downloadPromise = page.waitForEvent("download")
  await editor.getByRole("button", { name: "下载档案清单 JSON" }).click()
  const download = await downloadPromise
  const manifestBytes = await readFile(await download.path())
  const target = await createEntity(project.id, {
    name: "浏览器验收灵兽副本",
    entity_type: "spirit_beast",
    status: "canonical",
  })
  await page.evaluate(async (entityId) => {
    await window.router.navigate("world", "bible", true, new URLSearchParams({ entity_id: entityId }))
  }, target.id)
  await detail.getByRole('tab', { name: '设定档案', exact: true }).click()
  await detail.locator("details.world-entity-dossier summary").click()
  const importer = detail.locator(".manifest-import")
  await expect(importer).toBeVisible()
  await importer.locator('input[type="file"]').setInputFiles({
    name: "world-dossier.json", mimeType: "application/json", buffer: manifestBytes,
  }, { timeout: 5000 })
  await expect(importer.getByText("只对作者可见的灵兽观察")).toBeVisible()
  await importer.getByLabel("已核对目标模板").check()
  await page.setViewportSize({ width: 390, height: 844 })
  await importer.scrollIntoViewIfNeeded()
  await expectResponsiveLayout(page)
  await page.screenshot({ path: "/tmp/c0-dossier-import-390.png", fullPage: true })
  await importer.getByRole("button", { name: "预览导入" }).click()
  await expect(importer.getByText("将新增 1 条")).toBeVisible()
  await importer.getByLabel("我已核对内容、秘密可见范围和冲突处理").check()
  await importer.getByRole("button", { name: "确认采用档案清单" }).click()
  await expect(importer).toContainText("已采用 1 条档案")
  await page.setViewportSize({ width: 1280, height: 800 })
  await expectResponsiveLayout(page)
  await page.screenshot({ path: "/tmp/c0-dossier-import-1280.png", fullPage: true })
})

test("结构化档案在窄屏新增字符串、清空重加并保存无名称键的资源数组", async ({ page, projectFactory }) => {
  const project = await projectFactory({ title: "结构化档案编辑回归" })
  const entity = await createEntity(project.id, { name: "盐铁商会", entity_type: "faction", status: "canonical" })
  const profileUrl = `${API_BASE}/world/profiles/${entity.id}?novel_id=${project.id}`
  const saved = await page.request.put(profileUrl, {
    headers: { "X-Requested-With": "XMLHttpRequest" },
    data: { status: "canonical", leader_entity_ids_json: ["leader-a"], resources_json: [{ resource: "盐铁", amount: 3 }] },
  })
  expect(saved.ok()).toBeTruthy()
  await openWorkbench(page, project, "world", "bible")
  await page.evaluate(async (entityId) => {
    await window.router.navigate("world", "bible", true, new URLSearchParams({ entity_id: entityId }))
  }, entity.id)
  const panel = page.locator("details.world-entity-dossier")
  await page.getByRole('tab', { name: '设定档案', exact: true }).click()
  await panel.locator("summary").click()
  const editor = panel.locator(".object-dossier-editor")
  await page.setViewportSize({ width: 390, height: 844 })
  const leaders = editor.locator(".object-dossier-editor__entry", { hasText: "leader-a" })
  await leaders.getByRole("button", { name: "编辑", exact: true }).click()
  await leaders.getByRole("button", { name: "添加一项", exact: true }).click()
  await expect(leaders.locator("fieldset input")).toHaveCount(2)
  await expect(leaders.locator("fieldset input").first()).toHaveValue("leader-a")
  await leaders.getByRole("button", { name: "移除此项", exact: true }).first().click()
  await leaders.getByRole("button", { name: "移除此项", exact: true }).click()
  await leaders.getByRole("button", { name: "添加一项", exact: true }).click()
  await leaders.locator("fieldset input").fill("leader-b")
  await expectResponsiveLayout(page)
  await leaders.getByRole("button", { name: "保存新修订", exact: true }).click()
  await expect(editor.getByRole("status")).toContainText("档案新修订已保存")
  const afterLeaders = await page.request.get(profileUrl)
  expect((await afterLeaders.json()).fields.leader_entity_ids_json).toEqual(["leader-b"])

  await page.setViewportSize({ width: 1280, height: 800 })
  const resources = editor.locator(".object-dossier-editor__entry", { hasText: "resource：盐铁" })
  await resources.getByRole("button", { name: "编辑", exact: true }).click()
  await expect(resources.locator("fieldset")).not.toContainText("resource")
  await resources.locator("fieldset input").fill("盐矿")
  await expectResponsiveLayout(page)
  await resources.getByRole("button", { name: "保存新修订", exact: true }).click()
  await expect(editor.getByRole("status")).toContainText("档案新修订已保存")
  const afterResources = await page.request.get(profileUrl)
  expect((await afterResources.json()).fields.resources_json).toEqual([{ resource: "盐矿", amount: 3 }])
  await editor.getByRole("button", { name: "重新读取", exact: true }).click()
  await expect(editor.locator(".object-dossier-editor__entry", { hasText: "resource：盐矿；amount：3" })).toBeVisible()
})
