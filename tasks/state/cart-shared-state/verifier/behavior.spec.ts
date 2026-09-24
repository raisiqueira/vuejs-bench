import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, it } from 'vitest'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'

it('shares cart items and actions across three routes', async () => {
  const router = createAppRouter()
  await router.push('/')
  await router.isReady()
  const wrapper = mount(App, { global: { plugins: [router] } })
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('[data-testid="cart-count"]').text()).toBe('1')
  await router.push('/cart')
  await nextTick()
  expect(wrapper.get('li').text()).toContain('Notebook')
  await router.push('/checkout')
  await nextTick()
  expect(wrapper.get('[data-testid="checkout-count"]').text()).toBe('1')
  await wrapper.get('button').trigger('click')
  expect(wrapper.get('[data-testid="cart-count"]').text()).toBe('0')
  await router.push('/cart')
  await nextTick()
  expect(wrapper.findAll('li')).toHaveLength(0)
  wrapper.unmount()
})
