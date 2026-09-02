import { describe, expect, it } from 'vitest'
import { useWatchedCounter } from './useWatchedCounter'

describe('useWatchedCounter', () => {
  it('starts with no recorded events', () => {
    expect(useWatchedCounter().events.value).toBe(0)
  })
})
