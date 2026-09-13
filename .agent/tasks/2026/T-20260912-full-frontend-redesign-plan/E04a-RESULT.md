# E04a 结果：导入整理范围与质量授权

日期：2026-09-12。执行范围仅修改 ImportPreview.vue 与其测试。

- 修正外壳为 rd-page-scroll > rd-page-inner > rd-import-preview，避免在 topbar 下嵌套 main，并沿用 page-inner 的顶部间距。
- chapters/prepare 初始入口自动视为已选择《潮汐来信.txt》示例；state=error 可观察地进入解析失败。
- 准备资料页补充人物地点、关系规则、剧情线范围；质量偏好支持平衡/谨慎/完整；持续整理后续章节为单独的演示授权。
- 明确先生成候选资料，低置信和冲突留待决定，不自动写入正式设定。
- 未接 API、Storage、真实文件或模型。

验证：importPreview.test.js 4 项通过；定向 ESLint 与 diff-check 通过。
