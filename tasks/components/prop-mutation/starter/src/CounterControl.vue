<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ count: number }>()
defineEmits<{ 'update:count': [value: number] }>()
const localCount = ref(props.count)
</script>
<template>
  <button @click="localCount++">Count: {{ localCount }}</button>
</template>
