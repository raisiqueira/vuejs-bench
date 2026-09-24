<script setup lang="ts">
import { computed, ref } from 'vue'
import DraftView from './DraftView.vue'
import OverviewView from './OverviewView.vue'
const tab = ref<'draft' | 'overview'>('draft')
const activeView = computed(() => tab.value === 'draft' ? DraftView : OverviewView)
</script>
<template>
  <button @click="tab = 'draft'">Draft</button>
  <button @click="tab = 'overview'">Overview</button>
  <component :is="activeView" />
</template>
