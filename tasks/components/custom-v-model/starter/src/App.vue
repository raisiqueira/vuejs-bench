<script setup lang="ts">
import { ref } from 'vue'
import TextField from './TextField.vue'
const name = ref('Ada')
</script>
<template>
  <TextField v-model="name" />
  <output data-testid="name">{{ name }}</output>
  <button @click="name = 'Grace'">Reset</button>
</template>
