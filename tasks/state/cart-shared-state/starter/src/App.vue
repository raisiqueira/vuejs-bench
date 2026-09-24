<script setup lang="ts">
import { useCart } from './useCart'
const { count } = useCart()
</script>
<template>
  <header>
    <RouterLink to="/">Products</RouterLink>
    <RouterLink to="/cart">Cart</RouterLink>
    <RouterLink to="/checkout">Checkout</RouterLink>
    <output data-testid="cart-count">{{ count }}</output>
  </header>
  <RouterView />
</template>
