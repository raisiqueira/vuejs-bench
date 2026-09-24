import { ref, watch, type Ref } from 'vue'

export function useSearch(query: Ref<string>, lookup: (term: string) => Promise<string[]>) {
  const results = ref<string[]>([])
  const loading = ref(false)
  watch(query, async term => {
    loading.value = true
    results.value = await lookup(term)
    loading.value = false
  }, { immediate: true })
  return { results, loading }
}
