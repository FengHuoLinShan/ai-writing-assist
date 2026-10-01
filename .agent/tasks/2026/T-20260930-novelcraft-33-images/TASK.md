---
id: T-20260930-novelcraft-33-images
title: NovelCraft 33图修改与理法之环规则复审
status: active
created: 2026-09-30T00:00:00+09:00
updated: 2026-09-30T22:10:00+09:00
---

## 恢复快照
- 实际完成：v03已补齐IMG-10作者视角，33张当前选择完整（23张实际修改、10张按报告保留）；未再次生图。前32张沿用v02；IMG-10两次实际生成输出从原聊天恢复，最终选择表面细节加密版。
- 最新入口：output/novelcraft-33-revised-20260930/targeted-v03.html；NovelCraft-targeted-v03.zip约152.3 MiB。manifest-v03.json为当前33张选择的唯一清单，IMG-10在revised-v03/，其余32张在revised-v02/。
- 用户最新明确指示已恢复核实：环星球巨构扁平、细窄，表面复杂而远看简洁；完整结构仅供作者观看；高级大法师可用尖端手段间接推测存在某种结构，不能直接看见或还原全貌。原聊天01a0ef18-4475-73c2-b02b-ef16056d98f3最新相关轮已中断且目前idle。
- 下一步：收尾严格16:9画幅；若用户明确授权工具外像素裁切，31张镜头可无缩放中心裁切到1664×936并重新目视确认，另存版本。此前问题无回复，不假定已授权。图片改进当前交付完整，原精确画幅验收仍未满足，不关闭任务。
- 剩余与限制：参考1536×1024、镜头1672×941；未工具外裁切。独立盲读、天球投影、三维/结构/热容量及视频验收未执行。新图不描绘全食，旧报告的自然全食几何张力仍保留；不改Wiki或IMG-15。
- 验证：IMG-10最新图重新目视；33张选择及原图哈希、历史文件保留、HTML33锚点/图片替代文本/本地链接、ZIP117项无重复/CRC/内容一致通过。verify-v03.py为可复验入口；physics-check.py、git diff --check通过。未验证浏览器渲染，未重新做全33张盲读或实时Wiki语义审计。
- 既有门禁：make docs-check BASE_REF=origin/main仍因原分支architecture-decisions/architecture-governance要求审阅三篇文档失败，本任务未修改规则或架构代码。
- 工作区：/Users/tywww/Desktop/项目/ai-writing-assist，codex/docs-reorg-20260930；保留既有索引与任务记录WIP，本次仅更新本任务笔记及output本地产物。无提交、推送、CI或部署。
- 最后核实：2026-09-30T20:15:41+09:00。

## 目标与验收
- 原目标：依HTML原图/评审逐张修改2张3:2参考与31张16:9镜头；保留源文件，交付独立编号图和对照页。
- 追加目标：按本机Wiki与理法之环规则重新检查每张图的世界对应、建筑密度、规划和物理细节；交付来源、证据类型、具体修法与复验条件。
- 非目标：产品代码、视频后期、发布、正典写入。本轮不把静帧当工程测量或软件功能验收。

## 来源与边界
- /Users/tywww/Downloads/NovelCraft_33图逐张审查.html
- /Users/tywww/Downloads/理法之环 × NovelCraft 宣传片｜分镜与图片提示词.md
- 分享URL此前要求登录，未读取；sources/*.jpg是HTML内嵌预览，不是原始PNG。
- 实时Vault：/Users/tywww/Library/Mobile Documents/iCloud~md~obsidian/Documents；正典在wiki/。已读根CLAUDE.md；只向根log.md/hot.md补查询记录，未改Wiki正典或_raw。
- 生图使用内置imagegen，无外部付费API、无子代理。全部revised PNG本轮哈希与旧manifest一致。

## 交付路径
全部位于 output/novelcraft-33-revised-20260930/：
- sources/、revised/：33项原预览与33张生成PNG。
- index.html、manifest.json、prompts.json、review.json：上一轮对照和实际生成记录。
- NovelCraft-33-revised.zip：上一轮完整图包，未加入本轮审查报告，未冒称含新修正图。
- canon-audit-v01.html：33图最新带图复审；canon-audit-v01.json：逐项结论、17个来源哈希与物理输入/结果；physics-check.py：冻结参数的可复算断言。

## 关键发现与决定
- 双月约60°角距、自然相位错开约5.05日；01/02/05/12/16/17自然双满月错误，08月面应进入放大框，31应分清图标与天空。角色道具具体黄铜形状只是连续性选择，不是全世界强制规范。
- 七塔是七个自主塔权；06同谷七塔与24连贯地域模型缺正典依据，需用独立地区/分页表达。不能断言正典绝对禁止任何共址。
- IMG-10：当前近圆等边基准下银月地表最大角径0.453879° < 恒星保守下界0.532878°；与星锻环第41行日全食例句存在待裁定张力。仪器遮光、环食改叙事、改参数均只是候选；不得自动采纳。
- IMG-14海底直线向月上行与物理介质表达冲突；15功率线容易读成直射Tellus；16印在旧条目上不符追加审计且泄露人物知识边界；26日志/封存的工具映射不准。
- 城市无比例尺、人口、用地边界，不虚构精确密度/承重值。千阶城四门台地与白堤浅海三角洲不可套用到任意匿名城镇；候选代谢框架不整体当已采用正典。
- 20–25多为作者/产品隐喻，可在明确说明层后保留；不创造外部宇宙主机或系统人格。

## 验证与限制
- 33/33已由主Agent重新逐张目视；没有独立盲读、三维白模、结构承载计算或长期N体积分。所有图spatially_verified=false。
- 33编号完整、PNG哈希未变、所有图/预览/HTML锚点和17个本机来源链接存在、来源哈希无漂移；physics-check.py通过。
- worldcheck_status复核：300 checkpoint sources，changes/stale/unresolved/issues均空，head=checkpoint sha256:b57bccdbbb9ff4e1992a3faff92c4c3750b497b9781b032f63f9f8d3e087b3fb。不是图片语义通过，不是接受凭证。
- HTML通过结构/链接检查，已请求open_in_codex打开（返回queued）；此前浏览器file URL被策略拒绝，未用本地HTTP绕过，不声称浏览器渲染验收。
- 原参考1536×1024，场景1671/1672×940/941，严格16:9尚未规整。工具外像素处理的异步问题未获回复，不能假定授权。若获准无缩放裁切，可到1664×936，宽损7–8像素、高损4–5像素；不要沿用早先1–2像素的错误估计。
- 仓库make docs-check BASE_REF=origin/main此前未通过：当前分支architecture-decisions/architecture-governance变更要求审阅development-guide.md、testing-guide.md、documentation-maintenance.md，非图片任务新引入。未为过检改治理规则。最终重跑仍为同一既有门禁错误（exit 2），没有新增图片相关失败。

## 历史交付状态（v02）
v01复审完成；v02定点修改阶段已交付32张当前选择与1张单列待定。原revised/、来源报告及Wiki正典未改。IMG-10裁定、精确画幅及视频/真实产品验收未完成；无提交、推送、CI或部署。

## 历史定点修改 v02 交付检查点
用户已要求依据报告修改图片。所有新图保存 revised-v02/，逐次实际提示词与检查写 targeted-edits-v02.json；原 revised/ 和审查报告保留。IMG-10已异步询问环食/仪器遮光/保留，未回复前不代裁；其余图继续。不重画仅需编辑层说明的图，交付时列明。

- 已修改：REF-01；IMG-01/02/03/05/06/07/08/09/11/12/13/14/15/16/17/18/22/23/24/26/31，共22。
- 原样保留：REF-02；IMG-04/19/20/21/25/27/28/29/30，共10；后期使用条件逐项写入manifest-v02.json及对照页。
- pending-v02/IMG-10.png只保留原图参考；revised-v02/实际有32张。
- 失败修正已完成并保留记录：05小苍月两次生成仍比例/相位错误，最终去掉苍月、留单月；REF-01握柄错到三个人物自由端，已局部修回；15上/下方设施遮阳朝向未修准，最终移除两个错误图标、保留分布设施示意取样；26误连对应箭头已去掉，按四象限对应。
- IMG-15不声称精确受热/轨道/容量验证，示意功率束避开Tellus并落在月面接收区。IMG-12仍是未点灯的请求阶段，剪在02之后要明确回看；IMG-24村落缩入各塔底板，六层叙事仍需后期说明。
- 验证：22个新图哈希改变且已目视检查；10保留图哈希不变；33原revised图与17Wiki来源哈希不变。33项完整、32选图+1待定、55对照图与链接、ZIP CRC及无重名条目通过。git diff --check通过。
- make docs-check BASE_REF=origin/main最新仍为既有architecture-decisions/architecture-governance文档审阅要求失败；未改规则追认通过。
- HTML未宣称浏览器渲染验收；继续使用本地文件面板打开，不绕过先前file URL策略拒绝。

## IMG-10 作者视角裁定
用户指定环星球巨构带，扁平、细窄，表面极复杂而远看简洁；地面即使日全食也不可见，只给作者视角。按围绕Tellus理解制作IMG-10-v03，不写Wiki，不修改IMG-15恒星星锻设施。既有待选环食问题被此新方向替代。

## 接手续交付 v03
- 原任务中IMG-10两个内置imagegen调用均已完成；第二张为细节加密版，生成后整理中断。已核对原聊天用户消息与文件存在性，恢复实际提示词与生成路径到targeted-edits-v03.json，复制最终PNG到revised-v03/IMG-10.png，未追加生图调用。
- 最终PNG：1672×941，sha256:508327f1085ef4fbdb783820bc15f479436d9683a27caee43cf50c5d12a56c3e。环带细窄、平面，近弧细节复杂、远弧简洁，地面/日冕/全食已移除。编辑有轻微星球纹理漂移，未宣称像素完全不变。
- v03新增manifest、完整对照页、README、实际提示词记录、verification与可运行verify-v03.py；旧v02文件/ZIP、33张revised原图及sources预览保留。完整ZIP117项约152.3 MiB；当前选择23改+10留。旧版报告和待定图以历史材料保留，不作为最新状态。
- 完成当前IMG-10及33图包续交付；严格16:9、作者最终采用与后期验收仍未完成。任务保留active，不把交付图包等同原全部验收完成。

## 视频制作 v01（用户追加：脚本做成 720p60 视频）
- 工程：~/Documents/ad-video-workflow/projects/novelcraft-lifa-trailer-720p60（build.py 生成 index.html + compositions/film.html；make_score.py 生成本地合成配乐）。BRIEF.md 记录全部偏离与理由，claims.csv 记录卖点证据。
- 关键决定：S10 不用 IMG-10（环行星巨构与星锻环正典冲突且仅供作者观看），改原创速写页；字幕去“日全食”；S25 只保留可复核的约300页；S26 按图改四组；S28/S29/S30 按 README 证据改写并标示意。
- 验证与状态见该工程 QA.md；成片复制到 output/novelcraft-trailer-20260930/。未提交、未推送、未上传。
- 成片已交付：output/novelcraft-trailer-20260930/NovelCraft-理法之环-trailer-720p60.mp4（1280×720/60fps/128s，verify 通过，256 帧底部扫描 + 关键帧目检通过）。
- 渲染坑：HyperFrames 0.8.60 在 macOS 会裁掉底部约 88px（窗口可见区 633），须用工程内 chrome-tall-window.sh 作 HYPERFRAMES_BROWSER_PATH；直接 `ad_video.py render` 会复现。
- 剩余：配乐未经人耳试听；需用户观看确认。下一步：按用户观看意见调整后重渲。
