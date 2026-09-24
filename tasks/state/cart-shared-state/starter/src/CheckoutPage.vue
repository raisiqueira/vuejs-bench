<script setup lang="ts">
import { useCart } from './useCart'
const { count, clear } = useCart()
</script>
<template>
  <h1>Checkout</h1>
  <output data-testid="checkout-count">{{ count }}</output>
  <button @click="clear">Clear cart</button>
</template>
