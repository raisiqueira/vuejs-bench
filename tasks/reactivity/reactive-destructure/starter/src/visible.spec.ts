import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CounterSummary from './CounterSummary.vue'

describe('CounterSummary', () => {
  it('starts at zero and exposes an increment control', () => {
    const wrapper = mount(CounterSummary)
    expect(wrapper.get('[data-testid="count"]').text()).toBe('0')
    expect(wrapper.get('button').text()).toBe('Increment')
  })
})
