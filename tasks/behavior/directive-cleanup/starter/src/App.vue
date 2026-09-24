<script setup lang="ts">
import { ref } from 'vue'
import { vClickOutside } from './clickOutside'
const count = ref(0)
</script>
<template>
  <div v-click-outside="() => count++">Panel</div>
  <output>{{ count }}</output>
</template>
