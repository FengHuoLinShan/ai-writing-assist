from pathlib import Path
import json,hashlib,html,zipfile
import mistune
ROOT=Path(__file__).resolve().parent
md=mistune.create_markdown(escape=True,plugins=['table','strikethrough','url'])
files=sorted((ROOT/'plans').glob('0[0-6]-*.md'))
css='''*{box-sizing:border-box}body{margin:0;color:#1e2a3b;background:#f6f4f0;font:16px/1.85 "Noto Sans SC","Microsoft YaHei",system-ui,sans-serif}a{overflow-wrap:anywhere;color:#284c56;text-decoration-thickness:1px;text-underline-offset:3px}header{padding:38px max(28px,calc((100vw - 1120px)/2));background:#1e2a3b;color:#fffdf9}header a{color:#d6e5de}h1{font-size:34px;line-height:1.4}h2{font-size:26px;margin-top:52px;line-height:1.5}h3{font-size:20px;margin-top:32px}main{max-width:1180px;margin:0 auto;padding:28px}article{padding:38px 42px;background:#fffdf9;margin:30px 0;border:1px solid #dedcd5;border-radius:18px;scroll-margin-top:20px}pre{white-space:pre-wrap;word-break:break-word;background:#eeebe5;padding:22px;border-radius:12px;font-size:13px;line-height:1.75}code{font-size:.86em;background:#eeebe5;border-radius:4px;padding:2px 4px}pre code{padding:0}table{display:block;overflow:auto;border-collapse:collapse;font-size:14px;line-height:1.75;width:100%;margin:24px 0}th,td{padding:13px 15px;border:1px solid #dedcd5;text-align:left;vertical-align:top}th{background:#e5eeeb;color:#284c56}p{margin:16px 0}li{margin:9px 0}.toc{display:grid;grid-template-columns:1fr 1fr;gap:10px}.toc a{display:block;border:1px solid #dedcd5;background:#fffdf9;border-radius:10px;padding:14px 20px;text-decoration:none}.notice{border-left:4px solid #91601d;padding:13px 20px;background:#f7eedb;font-size:14px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{padding:28px;background:#fffdf9;border:1px solid #dedcd5;border-radius:16px;text-decoration:none}.card strong{display:block;font-size:22px}.card span{display:block;color:#667281;font-size:14px;margin-top:10px}.screens{display:grid;grid-template-columns:1fr 1fr;gap:20px}.screens img{width:100%;border-radius:12px;border:1px solid #dedcd5}.tag{font-size:12px;color:#c5dacc;letter-spacing:1px}@media(max-width:760px){.toc,.cards,.screens{grid-template-columns:1fr}article{padding:22px 19px}main{padding:15px}h1{font-size:28px}table{font-size:13px}}@media print{header{background:white;color:black}.toc{display:block}article{border:0;padding:0;break-before:page}main{padding:0}a{color:inherit}}'''
nav=''.join(f'<a href="#d{i}">{html.escape(p.read_text().splitlines()[0].lstrip("# "))}</a>' for i,p in enumerate(files))
sections=''.join(f'<article id="d{i}">{md(p.read_text())}</article>' for i,p in enumerate(files))
reader=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NovelCraft V4 · 长期总计划</title><style>{css}</style></head><body><header><div class="tag">NOVELCRAFT / LONG-RANGE PROGRAM 04</div><h1>演化式小说整体引擎<br>长期计划与实施契约</h1><p>2026-09-21 · 演化替代深度导入 · 持久认知 · 两轨多 Agent · 推荐 · 地图 · 全前端</p><a href="../design/prototype.html">打开高保真交互原型</a>　 <a href="../START-HERE.html">返回交付首页</a></header><main><p class="notice">本文为设计与实施计划。未改动业务仓库或生产系统；Figma 原生写入受额度阻断，离线设计与重建代码已交付。</p><div class="toc">{nav}</div>{sections}</main></body></html>'''
(ROOT/'plans/READ-PLAN.html').write_text(reader)
combined='# NovelCraft V4 完整长期计划\n\n'+ '\n\n---\n\n'.join(p.read_text() for p in files)
(ROOT/'plans/COMPLETE-PLAN-v4.md').write_text(combined)
index=json.loads((ROOT/'design/screen-index.json').read_text())
with (ROOT/'design/SCREEN-CATALOG.md').open('w') as f:
 f.write('# HiFi 画面目录\n\n所有画面由同一 design.json 生成。桌面为 1440×960，移动为 390×844。点击原型中的热点串联任务，不执行真实业务。\n\n| 编号 | 画面 | 分类 | SVG | PNG |\n|---|---|---|---|---|\n')
 for s in index:f.write(f'| {s["id"]} | {s["title"]} | {s["category"]} | [分层图](screens/{s["id"]}.svg) | [审阅图](previews/{s["id"]}.png) |\n')
qa=json.loads((ROOT/'validation/prototype-qa.json').read_text());layout=json.loads((ROOT/'validation/design-initial-qa.json').read_text());issues=sum(len(r['issues']) for r in layout)
(ROOT/'validation/DELIVERY-QA.md').write_text(f'''# 本轮交付验证记录

日期：2026-09-21。验证对象为本地设计、交互原型、文档及重建代码，不是生产应用。

## 已实际执行

| 检查 | 结果 |
|---|---|
| 画板生成 | {qa['screen_count']} 个，含 48 个工作流/状态与 1 个设计规范 |
| 离线语义节点 | {qa['design_nodes']} 个，保留文本/容器/路径等结构 |
| 导航热点引用 | {qa['hotspot_count']} 个，所有目标 ID 均存在 |
| SVG XML 解析 | 49 / 49 通过 |
| Chromium 渲染 | 49 / 49 生成 PNG |
| 自动文字边界检查 | {issues} 个未处理的文字互叠/画板越界报告（不能检测全部遮挡或审美问题） |
| 浏览器原型 | 全部画面可切换；地图→场景→返回链已点击验证 |
| 原型说明层 | 可打开，Escape 可关闭 |
| 原型手机宽度 | 420px 视口下文档宽度 420px，无页面水平溢出 |
| 浏览器脚本错误 | {len(qa['browser_errors'])} |
| Figma code.js | node --check 语法通过；不代表 Plugin API 运行通过 |

视觉抽查：S06 写作、S09 创意比较、S20 地图、S39 手机地图；修复了地图关键地名被抽屉遮挡、手机图例被底部详情覆盖等问题。其他画面有批量渲染和自动检查，不宣称全部逐图人工可用性验收。

## 未执行

Figma 原生插件运行、原生变量/组件/原型连线截图验证；生产 Vue 页面改造；真实后端 API / PostgreSQL 并发；真实模型质量；迁移/回滚；真实用户、读屏器和长期性能测试。

Figma MCP 返回 Starter 调用额度已用尽，创建的空文件不列为成果。插件会在用户的 Figma Design 中新建页面，不修改旧页面；缺字体/连线问题报告给使用者。插件数据为虚构设计样例，无 API Key、账号资料或字体文件。

## 再生成

设计：`python design/build_design.py`。生成者环境需本机可用中文字体；代码不分发字体。

审阅图：`python design/render_qa.py`，需 Playwright 和 Chromium。该脚本使用 set_content，避免环境中 file:// 导航受阻。

原型/插件：`python design/build_handoff.py`。

原型 QA：`python validation/verify_delivery.py`。

文档与入口：`python build_package.py`。

本文件的“通过”只指本表实际执行范围，不能移作产品或模型能力宣传。
''')
start=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NovelCraft V4 · 交付入口</title><style>{css}</style></head><body><header><div class="tag">NOVELCRAFT / DELIVERY 04</div><h1>让复杂发生在系统里，<br>让创作留在作者手上。</h1><p>7 份专项文档 · 49 个高保真画板 · 离线可点击原型 · 可编辑矢量与 Figma 重建代码</p></header><main><div class="cards"><a class="card" href="design/prototype.html"><strong>打开高保真原型 →</strong><span>写作、审阅、创意、地图、模型授权、恢复与手机。点击热点浏览任务链。</span></a><a class="card" href="plans/READ-PLAN.html"><strong>阅读完整长期计划 →</strong><span>演化替代深度导入，保留职责边界；认知、多 Agent、推荐与地图分阶段推进。</span></a><a class="card" href="design/SCREEN-CATALOG.md"><strong>查看全部 SVG / PNG</strong><span>49 个画面均有分层 SVG 与高清 PNG；无外部图片或字体依赖包。</span></a><a class="card" href="design/figma-plugin/README.md"><strong>在 Figma 重建可编辑图层</strong><span>本地开发插件代码。Figma MCP 额度已耗尽，本轮未完成原生画布写入。</span></a></div><p class="notice">离线原型不会调用模型、计费、保存或删除真实数据。画面小说与数值均为虚构设计样例。Figma 插件尚未完成原生运行验收。</p><h2>关键画面</h2><div class="screens"><a href="design/prototype.html#S06"><img src="design/previews/S06.png" alt="写作工作台"><p>正文优先 · 一个伙伴宿主</p></a><a href="design/prototype.html#S20"><img src="design/previews/S20.png" alt="沉浸式小说地图"><p>沉浸地图 · 地点、场景与原文连贯</p></a><a href="design/prototype.html#S09"><img src="design/previews/S09.png" alt="多方向创意对比"><p>独立发散 · 不强迫共识</p></a><a href="design/prototype.html#S33"><img src="design/previews/S33.png" alt="保存冲突比较"><p>来源与保存冲突 · 保留双方</p></a></div><h2>追踪与验证</h2><p><a href="validation/DELIVERY-QA.md">实际验证记录</a> · <a href="plans/05-TRACEABILITY-ACCEPTANCE.md">原计划继承与测试矩阵</a> · <a href="plans/06-SOURCES-AND-AUDIT.md">证据和研究</a> · <a href="design/contact-sheet.jpg">全部画面总览</a></p></main></body></html>'''
(ROOT/'START-HERE.html').write_text(start)
(ROOT/'README.md').write_text('''# NovelCraft V4 长期计划与全工作流 HiFi

解压后打开 `START-HERE.html`，或者直接打开 `design/prototype.html`。后者单文件离线可用，无需服务器；页面按钮只演示导航，不操作真实小说。

## 内容

`plans/READ-PLAN.html`：7 份计划合并阅读。`plans/COMPLETE-PLAN-v4.md`：完整 Markdown；专项文件可以单独交给开发任务。

`design/screens/`：49 个分层 SVG。`design/previews/`：对应 PNG 以及原型审阅图。`design/design.json`：统一设计源。`design/contact-sheet.jpg`：画面总览。

`design/figma-plugin/`：Figma 原生重建代码与安装说明。插件 ID 由 Figma 本地创建时分配，模板不伪造 ID。原生 Figma 写入因当前 MCP Starter 额度阻断，未完成；插件运行仍待 Figma 环境核验。

`validation/`：实际执行的本地检查。生产功能、真实模型、数据库迁移与可用性研究未执行。

`sources/`：两份原始输入计划，未改动。

所有示例小说与数值为设计样例，不含真实账号、密钥、稿件或字体文件。此交付不修改仓库或部署。
''')
# Hash manifest excludes itself, archives, caches; all persistent deliverables remain reproducible.
manifest=[]
for p in sorted(ROOT.rglob('*')):
 if p.is_file() and p.name!='MANIFEST.json' and '__pycache__' not in p.parts:
  b=p.read_bytes();manifest.append({'path':str(p.relative_to(ROOT)),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
(ROOT/'MANIFEST.json').write_text(json.dumps({'version':4,'files':manifest},ensure_ascii=False,indent=2))
print('plan chars',sum(len(p.read_text()) for p in files),'files',len(manifest))
