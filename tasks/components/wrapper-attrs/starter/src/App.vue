<script setup lang="ts">
import { ref } from 'vue'
import BaseButton from './BaseButton.vue'
const clicks = ref(0)
</script>
<template>
  <BaseButton aria-label="Save changes" disabled @click="clicks++">Save</BaseButton>
  <output>{{ clicks }}</output>
</template>
