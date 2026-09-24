import { computed, ref } from 'vue'

export function useOrder(recordAudit: (total: number) => void) {
  const quantity = ref(1)
  const price = ref(10)
  const total = computed(() => {
    const value = quantity.value * price.value
    recordAudit(value)
    return value
  })
  return { quantity, price, total }
}
