<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ modelValue: string }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
const local = ref(props.modelValue)
</script>
<template>
  <input aria-label="Name" :value="local" @input="local = ($event.target as HTMLInputElement).value">
</template>
