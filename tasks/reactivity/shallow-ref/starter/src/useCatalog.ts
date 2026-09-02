import { ref } from 'vue'

export interface CatalogItem {
  id: string
  label: string
  details: { owner: string; tags: string[] }
}

export interface Catalog {
  version: number
  items: CatalogItem[]
}

const initialCatalog: Catalog = {
  version: 1,
  items: [
    { id: 'vue', label: 'Vue', details: { owner: 'core', tags: ['ui', 'reactivity'] } },
  ],
}

export function useCatalog() {
  const catalog = ref<Catalog>(initialCatalog)

  function replaceCatalog(next: Catalog) {
    catalog.value = next
  }

  return { catalog, replaceCatalog }
}
