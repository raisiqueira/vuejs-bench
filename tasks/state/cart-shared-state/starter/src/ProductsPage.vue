<script setup lang="ts">
import { useCart } from './useCart'
const { add } = useCart()
</script>
<template>
  <h1>Products</h1>
  <button @click="add({ id: 1, name: 'Notebook' })">Add Notebook</button>
</template>
