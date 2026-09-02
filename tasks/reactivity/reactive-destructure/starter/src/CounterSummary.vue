<script setup lang="ts">
import { useCounter } from './useCounter'

const { count, increment } = useCounter()
</script>

<template>
  <section aria-label="counter">
    <output data-testid="count">{{ count }}</output>
    <button type="button" @click="increment">Increment</button>
  </section>
</template>
