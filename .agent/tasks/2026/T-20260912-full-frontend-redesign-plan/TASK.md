---
id: T-20260912-full-frontend-redesign-plan
title: 全前端视觉重设计与Luna执行
status: completed
created: 2026-09-12T18:05:23+08:00
updated: 2026-09-12T23:01:39+08:00
---

## 目标与验收
用户已从编写/评审计划推进到明确“执行计划”。按照PLAN.md和SUBAGENT-EXECUTION-LUNA.md，在独立预览完成全部前端的设计与本地交互表达，保留既有产品和WIP，真实业务完整性后接。

## 恢复快照
- 本地实现、相关测试与独立复验已完成；入口 http://localhost:8097/prototypes/redesign.html 。正式产品路由未接管。
- 工作区 /Users/tywww/Desktop/项目/ai-writing-assist，分支codex/redesign-regression。未提交、合并、推送、部署。
- 51个基础覆盖单元的设计归属见[COVERAGE.md](COVERAGE.md)；25个SFC、472个控件声明见[控件明细](CONTROL-DECLARATIONS.md)。
- 15个页面入口另含旅程准备/领域详情；浅深色、桌面/平板/手机，标题正文编辑、保存保护演示、候选版本、世界书/图谱、场景、地图、查找、作者计划、导入、AI任务、身份设置与读者流程均已接入。
- 验证总账[VALIDATION.md](VALIDATION.md)，45页面截图、两段真实动效录屏及网络/对比度记录见[evidence/README.md](evidence/README.md)。
- 下一步：由用户评阅独立预览；真实业务接回、真实移动设备/IME/屏幕阅读器验证在后续明确范围内进行。本记录不自动授权提交或业务接回。

## 关键边界与决定
- 当前只有虚构《潮汐来信》内存示例；刷新重置，无API/真实账户/作品存储/模型请求。采用、保存、恢复和任务结果始终标明演示。
- 不新增UI框架、动效库、模拟后端、通用状态引擎或测试平台；沿用Vue3/Vite、原生表单/dialog、ActionMenu、useModalDialog和既有动效。
- 主代理单写共享外壳/状态；按域独占文件分工。首批因宿主线程上限顺序执行，之后增加Luna high实施和独立浏览器评审；实际模型校准及限制见[CALIBRATION.md](CALIBRATION.md)。
- 未提交基线及文件指纹见BASELINE.json，备份`/tmp/novelcraft-full-redesign-baseline-20260912-212552.tar.gz`。前轮精简与设计成果保留，未回滚其他WIP。
- Vue KeepAlive保留页面、资料决定与本次输入；最小返回记录保留入口/section/state/滚动。来源比较绑定具体对象，源过期阻断采用，拒绝可用，决定回传同一对象。
- 输入时避免Vue回写contenteditable；正文工作稿可编辑，其余身份只读。手机章节/资料抽屉隔离背景、限制焦点并回还；原触发点移除时回到主内容。

## 审查与修复
- 计划原独立评审报告与裁决保留；其旧发现不表示仍未修复。
- ROOT-INDEPENDENT-REVIEW与WORLD-INDEPENDENT-REVIEW中的有证据问题已修；assistant不可达和强制CSS写法等未成立项已裁决，不转为门禁。
- 修复输入回写/空稿、候选CSS全局污染、只读/拒绝guard、手机0宽网格、世界条件链编译错误、资料决定丢失、候选对象/别名错配、目录内外错误不同步和焦点fallback。
- 非世界实际浏览器独立评审见BROWSER-INDEPENDENT-REVIEW.md。世界实际独立评审及最终定点复验见WORLD-BROWSER-REVIEW.md，报告发现已逐项复验通过。

## 实际验证
- 最终完整Vitest：188文件、2438测试通过，31.96秒；包含54项原型测试。日志`/tmp/full-redesign-vitest-final.log`。
- 全量lint通过；最终变更的原型/测试定向lint通过。生产build和资产校验通过，原型不进入dist。
- 15页×1280浅色/1024深色/390深色的45个窗口样本无页面级横向溢出或Vite错误；地图/设置长页签使用原生横向滚动。
- 实际面板/候选/专注录屏67帧；手机减效录屏24帧。已看中间帧，无竖排塌陷/残留。减效下所查控件与面板计算动效时长均为0，关闭焦点返回。
- 16组不透明语义文字配色最低4.73:1；记录期54请求无业务API/外部HTTP。Storage/IndexedDB/fetch由原型测试拦截验证。
- docs-check BASE_REF=origin/main与git diff --check收尾通过；这些检查不证明真实业务或用户盲评完成。

## 未验证与交付边界
真实API、持久化保存/恢复、模型与后台工作流未接回；真实IME合成、物理iPhone/iPad/软键盘、触摸和屏幕阅读器实机未测。桌面模拟不冒充实机，Apple式熟悉感不冒充Apple品牌归属或真人盲评。
