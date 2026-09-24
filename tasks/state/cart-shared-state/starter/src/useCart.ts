import { computed, ref } from 'vue'

export interface CartItem { id: number; name: string }

export function useCart() {
  const items = ref<CartItem[]>([])
  const count = computed(() => items.value.length)
  function add(item: CartItem) { items.value.push(item) }
  function remove(id: number) { items.value = items.value.filter(item => item.id !== id) }
  function clear() { items.value = [] }
  return { items, count, add, remove, clear }
}
