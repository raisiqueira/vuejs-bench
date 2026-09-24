import { createMemoryHistory, createRouter } from 'vue-router'
import ProductsPage from './ProductsPage.vue'
import CartPage from './CartPage.vue'
import CheckoutPage from './CheckoutPage.vue'

export function createAppRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: ProductsPage },
      { path: '/cart', component: CartPage },
      { path: '/checkout', component: CheckoutPage },
    ],
  })
}
