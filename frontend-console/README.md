# 小说结构化创作控制台 — 前端

面向中文作者的**小说结构化创作控制台**，终端深色主题、命令行风格、纯文字为主。

## 快速启动

直接打开 `index.html` 即可（无需构建工具）：

```bash
cd frontend-console
# 方式 1：直接双击 index.html
# 方式 2：使用 Python 启动本地服务器
python -m http.server 8080
# 打开 http://localhost:8080
```

## 后端连接

前端默认连接 `http://localhost:8000/api`。

如需修改后端地址，修改 `api.js` 中的 `API_BASE_URL`。

## 文件结构

```
frontend-console/
├── index.html              # 单页应用入口
├── styles.css              # 完整样式表（终端深色主题）
├── state.js                # 全局响应式状态管理
├── api.js                  # 完整 API 封装（76 个函数）
├── router.js               # Hash 路由系统
├── commands.js             # 命令系统（全中文帮助）
├── app.js                  # 应用主入口（快捷键绑定）
├── views/                  # 12 个视图
│   ├── projectView.js      # 项目
│   ├── worldView.js        # 世界对象 + 候选清洗
│   ├── geoView.js          # 地理历史
│   ├── characterView.js    # 人物档案 + 知识边界
│   ├── memoryView.js       # 长期记忆
│   ├── timelineView.js     # 时间线
│   ├── outlineView.js      # 剧情结构
│   ├── ragView.js          # RAG 检索
│   ├── contextView.js      # 上下文编译
│   ├── reviewView.js       # 结构复查
│   ├── writingView.js      # 草稿导出
│   └── generateView.js     # 生成中心
└── README.md
```

## 技术栈

- 纯原生 HTML + CSS + JavaScript
- 零外部依赖
- 所有 UI 文字为中文
- 终端深色主题（#050807）

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `?` | 打开快捷键帮助 |
| `:` | 聚焦命令栏 |
| `/` | 搜索 |
| `Esc` | 返回 / 关闭弹窗 |
| `j` / `k` | 上下移动选择行 |
| `n` | 新建 |
| `e` | 编辑 |
| `s` | 保存 |
| `g` | 生成 |
| `r` | 复查 |
| `c` | 确认 |
| `x` | 删除（二次确认） |
