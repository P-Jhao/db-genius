<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{
  content: string
}>()

const rendered = computed(() => {
  return DOMPurify.sanitize(marked.parse(props.content, { async: false, breaks: true }))
})
</script>

<template>
  <div class="markdown-body" v-html="rendered" />
</template>

<style scoped lang="scss">
.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text-1);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin: 16px 0 8px;
    font-weight: 600;
    line-height: 1.4;
    color: var(--color-text-1);
  }

  :deep(h1) { font-size: 20px; }
  :deep(h2) { font-size: 18px; }
  :deep(h3) { font-size: 16px; }
  :deep(h4) { font-size: 15px; }

  :deep(p) {
    margin: 8px 0;
  }

  :deep(ul),
  :deep(ol) {
    margin: 8px 0;
    padding-left: 20px;
  }

  :deep(li) {
    margin: 4px 0;
  }

  :deep(table) {
    width: max-content;
    min-width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 13px;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid var(--color-border-2);
    padding: 8px 12px;
    white-space: nowrap;
    text-align: left;
  }

  :deep(th) {
    background: var(--color-fill-2);
    font-weight: 600;
  }

  :deep(tr:nth-child(even)) {
    background: var(--color-fill-1);
  }

  :deep(pre) {
    background: var(--color-fill-2);
    border: 1px solid var(--color-border-2);
    border-radius: 6px;
    padding: 12px;
    margin: 12px 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  :deep(code) {
    font-family: 'SF Mono', Monaco, Menlo, Consolas, monospace;
    font-size: 13px;
  }

  :deep(pre > code) {
    display: block;
    white-space: pre;
    word-wrap: normal;
  }

  :deep(:not(pre) > code) {
    background: var(--color-fill-2);
    padding: 2px 6px;
    border-radius: 4px;
    color: rgb(var(--danger-6));
  }

  :deep(blockquote) {
    margin: 12px 0;
    padding: 8px 12px;
    border-left: 4px solid rgb(var(--primary-6));
    background: var(--color-fill-1);
    color: var(--color-text-2);
  }

  :deep(hr) {
    border: none;
    border-top: 1px solid var(--color-border-2);
    margin: 16px 0;
  }
}
</style>
