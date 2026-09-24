import { ref, watch } from 'vue'

export interface Product { id: number; price: number; quantity: number }

export function useProducts() {
  const products = ref<Product[]>([{ id: 1, price: 10, quantity: 2 }])
  const count = ref(2)
  const total = ref(20)

  watch(products, () => {
    count.value = products.value.length
    total.value = products.value.reduce((sum, product) => sum + product.price, 0)
  })

  function add(product: Product) { products.value.push(product) }
  function update(id: number, price: number, quantity: number) {
    const product = products.value.find(item => item.id === id)
    if (product) { product.price = price; product.quantity = quantity }
  }
  function remove(id: number) { products.value = products.value.filter(item => item.id !== id) }

  return { products, count, total, add, update, remove }
}
