# 主题包接口与制作指南

主题保存在当前浏览器，作者与互动故事共用；清除网站数据后需要重新导入。它不包含作品、账号连接或其他业务内容，不提供账号云端同步。

## 包结构

```text
my-theme.nctheme.zip
├── theme.json
├── LICENSE.txt          # 可选；随包提供资源许可证
└── assets/
    ├── reading.woff2
    ├── background.webp
    └── empty.png
```

压缩时直接选择上述内容，不要再套一层目录。只支持 ZIP 的 stored/deflate 压缩方法。机器规范为 [ThemePackageV1 Schema](../../../frontend-console/themes/theme-package.schema.json)，可直接使用的示例为 [静阅资源包](../../../frontend-console/themes/quiet-library.nctheme.zip)。

```json
{
  "schemaVersion": 1,
  "id": "my-theme",
  "name": "我的阅读空间",
  "version": "1.0.0",
  "author": "主题作者",
  "variants": {
    "light": {
      "colors": { "accent": "#4F46E5", "onAccent": "#FFFFFF" },
      "radius": 12,
      "density": "comfortable",
      "shadow": "soft",
      "bodyFont": "reading",
      "emptyState": "empty"
    },
    "dark": {}
  },
  "assets": {
    "reading": { "kind": "font", "path": "assets/reading.woff2", "weight": 400 },
    "empty": { "kind": "image", "path": "assets/empty.png" }
  }
}
```

至少声明 light 或 dark 中一种，未声明模式和变量使用对应现代简约默认值。主题 ID 与资源 ID 使用小写字母开头、字母／数字／连字符，最多 64 字符；`modern` 为内置主题保留。不要使用 constructor 或 prototype 作为资源名。

## 可定制变量

| 项目 | 允许值 |
|---|---|
| colors | background、surface、muted、text、body、secondary、accent、onAccent、primary、onPrimary、border、controlBorder、success、warning、danger；均为六位十六进制色值 |
| radius | 0–16 的整数，作为组件圆角基准 |
| density | comfortable / compact；手机仍保留至少 44px 命中区 |
| shadow | soft / none，控制浮层投影 |
| uiFont / bodyFont | 包内 font 资源 ID；没有对应字形时回退系统字体，已有作者显式字体偏好仍有效 |
| background / texture / emptyState | 包内 image 资源 ID，对应工作区背景、正文纹理、空态插画 |

字体只接受 WOFF2；weight 为 100–900 整数，style 为 normal / italic。图片接受真实 PNG、JPEG、WebP；不接受 SVG、任意 CSS／HTML／脚本、远程 URL 或路径逃逸。主题不能重排布局、改动业务字段、遮挡交互或改变断点。

颜色校验覆盖必要文字对 background/surface/muted 至少 4.5:1，控件边界至少 3:1，以及主按钮和强调色按钮文字对比度。背景与纹理须克制，预览时自行检查实际图像不会影响阅读；不要用主题图片承载说明文字。

## 限额与失败行为

压缩包不超过 30MiB，实际解压总量不超过 64MiB，最多 128 个 ZIP 条目；theme.json 与许可证分别不超过 128KiB，单图不超过 6MiB、边长不超过 4096px，单字体不超过 24MiB。解压超时或主动取消会终止线程。

未知字段和不支持的 schemaVersion 会拒绝；缺失／重复资源、类型错误、损坏字体、非法配色和超限包不会改变当前外观。同 ID 重新导入时明确确认替换；删除当前主题时恢复默认。只有本地存储提交成功后才提示已导入；无法持久化的应用选择明确标为本次会话有效。

预览未声明的字体和图片使用内置默认值，不继承正在使用的主题资源；取消预览后现用主题保持不变。

## 示例资源与许可

`themes/sample/` 保存解压后的可编辑示例，ZIP 同步交付。Noto Sans SC 样本是示例文案字形子集，经 Google Fonts 提供，依 SIL Open Font License 1.1 分发；许可证在包内 LICENSE.txt。几何书本和点状纹理为项目生成的示例素材。实际制作时需提供自己使用资源的授权说明，字体缺字会回退系统字体。

导入、预览与资源加载均不上传文件或访问外部字体／图片地址。外观设置的“制作自己的主题”提供示例与 Schema 下载，技术说明不占普通创作流程。
