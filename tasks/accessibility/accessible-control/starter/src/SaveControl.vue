<script setup lang="ts">
const emit = defineEmits<{ activate: [] }>()
</script>
<template>
  <div class="save-control" @click="emit('activate')">Save</div>
</template>
