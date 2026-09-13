# 稳定版本视觉与动效证据

- 15页×桌面1280浅色、平板1024深色、手机390深色，共45张首屏截图，逐页结果见[page-checks.json](page-checks.json)。
- [桌面面板→候选→专注快速切换](panels-candidate-focus.mp4)：67个真实screencast帧，按原始时间戳生成，约1.97秒，包含中途关闭与反向操作。
- [手机减少动态效果](mobile-reduced-motion.mp4)：24个真实帧，约1.17秒，章节抽屉/AI面板开关及焦点返回。
- 动画中间帧：motion-middle-0015.jpg、0035.jpg、0050.jpg；未观察到竖排塌陷或退出残留。
- [减少运动检查](reduced-check.json)：系统减效=true，所查控件/面板的计算动效时长均为0，关闭后焦点为写作伙伴。临时媒体模拟已恢复。
- [语义色对比](semantic-contrast.json)：16组前景/背景文字对比均≥4.5，最低4.73。仅检验列出的不透明语义色对，不等于完整屏幕阅读器/WCAG认证。
- [网络记录](network-check.json)：记录期54个请求，无业务API或外部HTTP请求，无事件截断；自动测试另外拦截fetch、Storage和IndexedDB访问。
- [目录重扫恢复](world-import-recovered.png)：内外层失败提示均清除，当前只显示演示成功反馈。

手机地图/设置的部分页签位于横向滚动条内，可滚动或键盘访问；这不是页面横向溢出。页面级几何检查均未发现溢出或Vite错误遮罩。
截图用于人工设计判断，不是像素门禁。原始帧保留在`/tmp/novelcraft-full-redesign-motion-frames`和`/tmp/novelcraft-full-redesign-reduced-frames`，避免把大体积原始材料默认纳入Git。
