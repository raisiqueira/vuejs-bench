import { reactive, ref, watch } from 'vue'

export function useWatchedCounter() {
  const state = reactive({ count: 0 })
  const events = ref(0)

  watch(state.count as unknown as () => number, () => {
    events.value += 1
  })

  function increment() {
    state.count += 1
  }

  return { state, events, increment }
}
