<script setup lang="ts">
import { ref } from 'vue'
import SearchField from './SearchField.vue'
const query = ref('alpha')
</script>
<template>
  <SearchField v-model:query.trim="query" />
  <output data-testid="query">{{ query }}</output>
  <button @click="query = 'reset'">Reset</button>
</template>
