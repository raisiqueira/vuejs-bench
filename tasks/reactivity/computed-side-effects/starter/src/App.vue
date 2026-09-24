<script setup lang="ts">
import { useOrder } from './useOrder'
const { quantity, total } = useOrder(() => {})
</script>
<template>
  <output>{{ total }}</output>
  <button @click="quantity++">Add one</button>
</template>
