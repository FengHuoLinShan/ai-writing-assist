# F01-F02 结果：互动故事列表与开场准备

日期：2026-09-12。执行范围按主代理任务卡限定，仅新增 JourneyPreview.vue、JourneySetup.vue 与 journeyPreview.test.js；未修改 ExperiencePreview、根组件、正式互动故事或其他域。

## 已完成

- JourneyPreview 保留现有灯塔 hero 与发现故事卡视觉，继续旅程进入 reading，开启/发现新故事进入 journeys/setup。
- 列表补充私人旅程空态、加载失败与重试；失败提示说明已有旅程保留。
- JourneySetup 分为“直接写下世界与开场”和“选择作品资料”两种入口；直接模式提供世界、身份、开场和角色确认。
- 作品来源使用可用的虚构“潮汐来信”示例，可选章节剧情点；“演示重新整理”进入整理中，整理中明确不能开始阅读，手动完成后恢复可进入状态。
- 提供从作品导入入口、返回旅程列表、进入示例故事；进入只打开虚构 reading 示例，不调用模型或读取真实作品。
- 未新增登录方式、未搬运作者后台术语、未接真实作品/模型/API/Storage。

## 接口

- 两个组件均接收 props：state、initialSection。
- 两个组件均 emit：navigate、open。
- 关键事件：列表开启新旅程 → navigate('journeys', 'setup')；准备完成 → navigate('reading')；从作品导入 → navigate('import')。

## 验证

- npm test -- --run tests/prototypes/journeyPreview.test.js：1 个文件，3 个测试通过。
- npx eslint prototypes/redesign/JourneyPreview.vue prototypes/redesign/JourneySetup.vue tests/prototypes/journeyPreview.test.js：通过。
- git diff --check -- prototypes/redesign/JourneyPreview.vue prototypes/redesign/JourneySetup.vue tests/prototypes/journeyPreview.test.js：通过。

## 主代理待验

- 浏览器检查灯塔 hero、发现卡、空/失败列表、准备表单、整理中禁用和窄屏布局。
- 主代理接入 journeys 分支后联验 setup section、import 返回及 reading 入口。
- 阅读正文、真实旅程创建、来源整理和登录连接不在本包范围。
