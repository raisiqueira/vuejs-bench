<script setup lang="ts">
defineProps<{ items: string[] }>()
</script>
<template>
  <section>
    <div class="list-header"><slot name="header" /></div>
    <ul>
      <li v-for="item in items" :key="item">
        <slot name="item" :value="item">{{ item }}</slot>
      </li>
    </ul>
  </section>
</template>
