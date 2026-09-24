<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ query: string }>()
const local = ref(props.query)
</script>
<template>
  <input aria-label="Query" v-model="local">
</template>
