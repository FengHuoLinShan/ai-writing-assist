# 共享基础 S01/S02 v1

当前执行：2026-09-12，隔离预览，不接真实业务。

- Vue入口和现有三种外壳保留；页面名在data.js。URL可用page/state/section/theme指定初始样板，刷新恢复该初始示例；编辑状态不写URL/Storage。
- RedesignApp使用Vue KeepAlive保留各页面本次输入及局部选择，滚动位置由主壳按页面记忆。页面emit navigate(target, section)；open(title, kind, drawer)沿用现有非模态/模态对话框。
- 共享文件RedesignApp、data、main、redesign.css、motion、PreviewDialog/Notice/Icon均由主代理单写。子页面可新增局部样式并从自己的SFC导入，根选择器必须限制#redesign-root。
- 文稿/候选/正式身份不同；候选采用只呈现演示结果，不覆盖实际示例正文。跨入口候选状态由主壳提供同一会话对象；其他局部状态先留本组件，不创建通用状态引擎。
- 颜色、材质与动效直接复用redesign.css和motion.css；按钮内rd-button-content、稳定命中区、vReveal仅对低频对象/页签切换，不能对输入逐字播放。
- 共享PreviewDialog既有焦点来源、非模态侧栏、快速反向关闭规则保留。桌面正文为稳定纸面，移动按任务收纳；共享CSS不冻结像素。
- 用户任务：作者安心继续写并查看资料；读者低摩擦继续旅程。舒适度和喜欢程度仍为设计假设，以实际操作、中文长内容、浅深色、键盘和减少运动评审。
- 主代理持有浏览器操作权。子代理可读既有截图或交付新截图请求；无浏览器检查不得标验收通过。
