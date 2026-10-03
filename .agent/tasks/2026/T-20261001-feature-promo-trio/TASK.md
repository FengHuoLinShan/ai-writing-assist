---
id: T-20261001-feature-promo-trio
title: NovelCraft 三支功能宣传片（主动式助手 / 地图 / 作品对接互动故事）
status: completed
created: 2026-10-01T20:00:00+09:00
updated: 2026-10-02T02:45:00+09:00
---

## 恢复快照
- 状态：已完成。三支成片在 output/feature-promos-20261001/：NovelCraft-主动式助手-1080p60.mp4（84s）、NovelCraft-地图-1080p60.mp4（86s）、NovelCraft-作品走进互动故事-1080p60.mp4（84s）；QA 与上屏说法来源见该目录 QA.md。
- 服务：backend 8131 / Vite 8132 已停止（端口确认无监听）。
- 遗留可清理：build/*/video.mkv 无损母版各约 10 GB（可删，重渲约 5 分钟/片）；复制库 ai_novel_promo_features_20261001 可删除（需用户决定）。
- 重做：改 src/scenes_X.js → python3 render.py --film X --start 0 --end <dur> → python3 make_cues.py X && python3 score.py --film X && python3 master.py X → ./finish.sh X。

## 目标与验收
- 用户要求：针对“主动式助手能力”“地图能力”“作者侧作品快速对接 RP 侧”各做一支宣传片，风格类似最初的项目总体宣传片（不强求）。
- 风格基准：output/novelcraft-intro-1080p60-20261001（暖纸面、海军蓝/香槟金、Canvas 动效 + 真实界面窗口 + 左侧说明栏 + 本地合成配乐，1920×1080/60fps）。
- 验收：每支 ffprobe 规格；关键帧目检；上屏功能描述可回溯到代码/README/ADR；默认关闭或实验能力如实标注；UI 画面来自当前代码真实运行。

## 来源与边界
- 专用复制库 `ai_novel_promo_features_20261001`（alembic head 20260929_world_object_image_candidates），可事后删除；原库 ai_novel_acceptance_guimi 未改。
- 用户授权“少量真实调用”：仅复制库、仅《诡秘之主》演示项目第 60 章；一次“下一步”+ 一次单章编辑审读。实际：forecast run 15022020（2 次请求）+ editorial task 30ceef22（2 次请求），共 4 次，未超范围。
- 进程级 env 覆盖（不改 backend/.env）：DATABASE_URL→复制库；MAP_ATLAS/WORLD_OBJECT S3→本地 MinIO dev；ASSISTANT_FORECAST(_SEMANTIC)/EDITORIAL_ENABLED=true；LLM_PROXY_URL=""（.env 指向的 127.0.0.1:1082 代理未运行）。
- 复制库内写入：城市节点 b948a787 新地图修订 e87ed282（补 reader_from_chapter 使读者预览渐进）；编辑约定第 1 版；上述 forecast/editorial 结果。

## 交付路径
- output/feature-promos-20261001/（gitignored）：steps.py（界面步骤截图器，支持 init/waitjs/elshot/top）、scout/（侦察截图与 JSON 步骤）、src/scenes_{assist,map,rp}.js、make_cues.py、score.py、master.py、finish.sh。
- 成片名：NovelCraft-主动式助手-1080p60.mp4（84s）、NovelCraft-地图-1080p60.mp4（86s）、NovelCraft-作品走进互动故事-1080p60.mp4（84s）。

## 关键决定与发现
- “下一步”卡片有效性绑定 explicit_instruction 与 cursor_offset：重截时需用 init 脚本预置 localStorage `novel_forecast_v1:local:<pid>` 的 instruction（scout/fc_init.js），且首次加载即截，不做 hash 二次跳转。
- 编辑台单章 = reader + editorial 两步，预算上限 4 次请求；对已发布章可用（“本章写完，交给编辑看”按钮仅草稿态出现）。
- RP：无字面“一键”；快捷路径 = 开局目录“从这里开始” + 4 步向导；旅程冻结资料版本，不写回原作；只能向后推进/升级。
- 地图：读者预览按章渐进（ch2:0 → ch5:2 → ch40:12）；图片为示意非正式设定；不宣称 RP 读取地图、不宣称比例/距离。
- 助手：功能默认关闭/实验标注；不自动改正文（“意见由你决定如何处理”）。编辑台“主动跟进”在本环境显示“后台编辑当前未开放”，片中如实标注。
- 地图读者可见章节（复制库演示设置，片中标“演示设置”）：ch5 水仙花街/市政广场；ch15 韦尔奇住所；ch18 红月亮街；ch24 银冠餐厅；ch27 佐特兰街/黑荆棘/圣赛琳娜/射击俱乐部；ch38 铁十字街两段/莫雷蒂旧公寓；至 ch60 共 12 处，作者视图 16 处。
- 地图口径（docs/modules/15_map.md、ADR-0012）：阅读预览仅 owner 端按章首；尚无公开读者或 RP 地图入口；不回写世界正史；不按比例；手动制图无需模型。

## 验证
- 三片 ffprobe：h264 High@4.2 / yuv420p / BT.709 / 60fps，AAC 320k 48kHz；时长 84/86/84 s。
- 响度：-14.0 / -13.9 / -14.0 LUFS，真峰值 -1.5 / -1.7 / -1.7 dBTP；成片音轨与母带互相关偏移均为 0 样本。
- 成片抽帧联系表目检（每片 15–16 帧）正常。未验证：配乐未经人耳试听，未在实际播放器/发布平台测试。
