import type { ObjectDirective } from 'vue'

export const vClickOutside: ObjectDirective<HTMLElement, () => void> = {
  mounted(element, binding) {
    document.addEventListener('click', event => {
      if (!element.contains(event.target as Node)) binding.value()
    })
  },
}
