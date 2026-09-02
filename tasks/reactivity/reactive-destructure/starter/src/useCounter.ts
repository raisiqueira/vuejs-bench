import { reactive } from 'vue'

export function useCounter() {
  const state = reactive({ count: 0 })
  const { count } = state

  function increment() {
    state.count += 1
  }

  return { count, increment }
}
