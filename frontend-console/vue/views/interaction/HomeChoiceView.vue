<script setup>
import { getRouter } from "../../bridge/index.js"

function enterAuthor() {
  getRouter().navigate("project")
}

function enterRp() {
  getRouter().navigate("journeys")
}
</script>

<template>
  <main class="entry-choice">
    <div class="entry-choice__heading">
      <span class="entry-choice__brand"><i aria-hidden="true">◆</i> NovelCraft</span>
      <h1>今天想怎样进入故事？</h1>
      <p>创作一部小说，或直接走进熟悉的幻想世界。</p>
    </div>
    <div class="entry-choice__grid" aria-label="选择使用方式">
      <button class="entry-card entry-card--author" type="button" data-entry="author" @click="enterAuthor">
        <span class="entry-card__eyebrow">WRITE</span>
        <strong>我是作家</strong>
        <span>整理世界、大纲与正文，继续现有创作项目。</span>
        <i aria-hidden="true">进入创作 →</i>
      </button>
      <button class="entry-card entry-card--rp" type="button" data-entry="rp" @click="enterRp">
        <span class="entry-card__eyebrow">ROLE PLAY</span>
        <strong>我是 RP（角色扮演）用户</strong>
        <span>告诉模型你想进入哪个世界，从一个身份和起点开始游玩。</span>
        <i aria-hidden="true">尽情游玩吧 →</i>
      </button>
    </div>
  </main>
</template>
