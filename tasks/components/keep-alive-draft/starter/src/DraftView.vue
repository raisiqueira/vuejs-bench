<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { readAnnouncement } from './announcement'
const draft = ref('')
const announcement = ref('')
onMounted(() => { announcement.value = readAnnouncement() })
</script>
<template>
  <label>Draft <input v-model="draft"></label>
  <output data-testid="announcement">{{ announcement }}</output>
</template>
