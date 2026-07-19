<template>
  <div id="help-overlay" :class="{ hidden: !open }" @click.self="$emit('close')">
    <div id="help-modal" role="dialog" aria-modal="true" aria-labelledby="shell-help-title">
      <div id="help-header"><h2 id="shell-help-title">快捷键帮助</h2><button id="help-close" type="button" aria-label="关闭快捷键帮助" @click="$emit('close')">×</button></div>
      <div id="help-body"><table class="help-table"><tbody>
        <tr v-for="item in shortcuts" :key="item.keys"><td><kbd>{{ item.keys }}</kbd></td><td>{{ item.label }}</td></tr>
      </tbody></table></div>
    </div>
  </div>
</template>

<script setup>
defineProps({ open: Boolean })
defineEmits(["close"])
const shortcuts = [
  { keys: "?", label: "显示快捷键帮助面板" }, { keys: ":", label: "聚焦命令栏（命令模式）" }, { keys: "/", label: "聚焦命令栏（搜索模式）" },
  { keys: "Esc", label: "返回上级 / 关闭弹窗 / 退出命令栏" }, { keys: "j / k", label: "列表上下移动" }, { keys: "h / l", label: "左右切换区域" },
  { keys: "Enter", label: "打开 / 选中" }, { keys: "n", label: "新建" }, { keys: "e", label: "编辑" }, { keys: "Ctrl/Cmd+S", label: "保存当前章节" },
  { keys: "Ctrl/Cmd+Shift+O", label: "打开 / 关闭大纲浮窗" }, { keys: "s", label: "保存" }, { keys: "g", label: "生成" }, { keys: "x", label: "删除（需二次确认）" },
]
</script>
