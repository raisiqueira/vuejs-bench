<script setup lang="ts">
import { ref } from 'vue'
import SaveControl from './SaveControl.vue'
const saves = ref(0)
</script>
<template>
  <SaveControl @activate="saves++" />
  <output>{{ saves }}</output>
</template>
