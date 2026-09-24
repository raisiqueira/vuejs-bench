<script setup lang="ts">
import { ref } from 'vue'
import CounterControl from './CounterControl.vue'
const count = ref(0)
</script>
<template>
  <output data-testid="parent-count">{{ count }}</output>
  <CounterControl :count="count" @update:count="count = $event" />
  <button data-testid="reset" @click="count = 0">Reset</button>
</template>
