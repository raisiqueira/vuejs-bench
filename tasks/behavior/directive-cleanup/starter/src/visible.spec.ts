import { expect, it } from 'vitest'
import { vClickOutside } from './clickOutside'
it('exports a mounted directive', () => {
  expect(vClickOutside).toHaveProperty('mounted')
})
