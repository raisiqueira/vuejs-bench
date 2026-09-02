import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import { useWatchedCounter } from '../src/useWatchedCounter'

describe('watch source behavior', () => {
  it('records an event after an increment', async () => {
    const counter = useWatchedCounter()
    counter.increment()
    await nextTick()
    expect(counter.events.value).toBe(1)
  })

  it('records each subsequent increment', async () => {
    const counter = useWatchedCounter()
    counter.increment()
    await nextTick()
    counter.increment()
    await nextTick()
    expect(counter.events.value).toBe(2)
  })
})
