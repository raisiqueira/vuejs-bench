import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CounterSummary from '../src/CounterSummary.vue'

describe('reactive destructuring behavior', () => {
  it('updates the rendered count after state changes', async () => {
    const wrapper = mount(CounterSummary)
    await wrapper.get('button').trigger('click')
    expect(wrapper.get('[data-testid="count"]').text()).toBe('1')
  })
})
