<script setup lang="ts">
import { ref } from 'vue'
const props = defineProps<{ item: { id: number; name: string } }>()
const draft = ref(props.item.name)
</script>
<template>
  <li :data-id="item.id"><input v-model="draft" :aria-label="`Name for ${item.id}`"></li>
</template>
