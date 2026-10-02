/**
 * 表格迁移浏览器 e2e（ADR-0030）— 上传 → 映射 → 采用 → 徽标 → 撤销。
 * 由 L8 集成阶段在专用 PG 环境运行（make test-e2e 通道）；
 * 夹具 xlsx 由测试在页面上传前用 openpyxl 生成（见 backend/tests/fixtures/spreadsheets/）。
 */
import { expect, test } from "@playwright/test"

test.describe("表格迁移", () => {
  test("上传 xlsx 后完成映射、采用、出现表格迁移徽标并可撤销", async ({ page }) => {
    await page.goto("/project")
    // 1. 打开导入抽屉 → 切到「导入设定表格」
    await page.getByRole("tab", { name: "导入设定表格" }).click()
    await expect(page.getByTestId("sm-panel")).toBeVisible()

    // 2. 上传夹具（L8 集成时接 e2e 夹具路径）
    await page.setInputFiles('[data-testid="sm-file-input"]', [
      { name: "人物表.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", buffer: Buffer.alloc(0) },
    ])
    await page.getByRole("button", { name: "上传并识别表格" }).click()

    // 3. 核对映射
    await expect(page.getByTestId("sm-mapping")).toBeVisible()
    await page.getByRole("button", { name: "保存映射并生成预览" }).click()

    // 4. 跳过 AI → 预览确认
    await page.getByRole("button", { name: "跳过 AI，直接用规则导入" }).click()
    await page.locator('[data-action="sm-apply-confirm"]').check()
    await page.getByRole("button", { name: "确认采用" }).click()
    await expect(page.getByTestId("sm-done")).toBeVisible()

    // 5. 世界库出现「表格迁移」徽标
    await page.locator('[data-action="sm-goto-world"]').click()
    await expect(page.getByText("表格迁移").first()).toBeVisible()

    // 6. 撤销本次迁移
    await page.goto("/project")
    await page.getByRole("tab", { name: "导入设定表格" }).click()
    await page.locator('[data-action="sm-records-rollback"]').first().click()
    await expect(page.getByText(/已撤销/).first()).toBeVisible()
  })
})
