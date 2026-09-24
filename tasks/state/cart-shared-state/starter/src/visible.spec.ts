import { expect, it } from 'vitest'
import { createAppRouter } from './router'
it('defines three routes', () => {
  expect(createAppRouter().getRoutes()).toHaveLength(3)
})
