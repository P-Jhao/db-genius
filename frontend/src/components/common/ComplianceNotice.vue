<script setup lang="ts">
// 合规提示条：与「开源版 / 正式版」无关，任何部署形态都会展示，
// 固定在页面第一行（位于开源版提示条之上）。
</script>

<template>
  <div class="compliance-notice" role="note">
    <p class="compliance-notice__text">{{ $t('comps.notice.text') }}</p>
  </div>
</template>

<style scoped lang="scss">
.compliance-notice {
  padding: 10px 16px;
  background: var(--color-fill-2);
  border-bottom: 1px solid var(--color-border-2);
  text-align: center;
}

.compliance-notice__text {
  margin: 0;
  /* 与全站无衬线字体区分，使用衬线字族 */
  font-family: Georgia, 'Songti SC', 'STSong', 'SimSun', 'Noto Serif SC', 'Noto Serif CJK SC', serif;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.2px;
  line-height: 1.6;
  color: var(--color-text-1);
}
</style>
