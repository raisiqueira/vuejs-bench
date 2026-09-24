<script setup lang="ts">
import { useProducts } from './useProducts'
const { products, count, total, add } = useProducts()
</script>
<template>
  <section>
    <output data-testid="count">{{ count }}</output>
    <output data-testid="total">{{ total }}</output>
    <button @click="add({ id: products.length + 1, price: 5, quantity: 3 })">Add</button>
  </section>
</template>
