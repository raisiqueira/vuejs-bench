<script setup lang="ts">
import { onMounted, ref } from 'vue'
const open = ref(false)
const editor = ref<HTMLInputElement | null>(null)
onMounted(() => editor.value?.focus())
</script>
<template>
  <button @click="open = !open">{{ open ? 'Close' : 'Open' }}</button>
  <input v-if="open" ref="editor" aria-label="Editor">
</template>
