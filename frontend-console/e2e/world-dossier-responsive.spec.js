import { test, expect } from "./fixtures.js"
import { createEntity } from "./helpers/api-client.js"
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
})
