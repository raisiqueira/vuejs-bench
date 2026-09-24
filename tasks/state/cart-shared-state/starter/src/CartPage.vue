<script setup lang="ts">
import { useCart } from './useCart'
const { items, remove } = useCart()
</script>
<template>
  <h1>Cart</h1>
  <ul><li v-for="item in items" :key="item.id">{{ item.name }} <button @click="remove(item.id)">Remove</button></li></ul>
</template>
