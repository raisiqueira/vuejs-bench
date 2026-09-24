<script setup lang="ts">
import { ref } from 'vue'
import RowEditor from './RowEditor.vue'
const items = ref([{ id: 1, name: 'Alpha' }, { id: 2, name: 'Beta' }])
function reverse() { items.value.reverse() }
</script>
<template>
  <button @click="reverse">Reverse</button>
  <ul><RowEditor v-for="(item, index) in items" :key="index" :item="item" /></ul>
</template>
