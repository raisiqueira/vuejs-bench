<script setup lang="ts">
import { ref } from 'vue'
import { useSearch } from './useSearch'
const query = ref('')
const { results, loading } = useSearch(query, async term => term ? [term] : [])
</script>
<template>
  <label>Search <input v-model="query"></label>
  <p v-if="loading">Loading</p>
  <ul><li v-for="result in results" :key="result">{{ result }}</li></ul>
</template>
