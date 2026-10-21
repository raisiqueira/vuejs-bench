# Autocomplete: clicking AutocompleteCancel on an unfocused input does not refresh the items

This repository is Reka UI. The library source is in `packages/core`.

## Reproduction

```vue
<script setup>
import { ref } from 'vue'
import {
  AutocompleteAnchor,
  AutocompleteCancel,
  AutocompleteContent,
  AutocompleteInput,
  AutocompleteItem,
  AutocompletePortal,
  AutocompleteRoot,
  AutocompleteViewport,
} from 'reka-ui'

const options = ['Apple', 'Banana', 'Cherry']
const model = ref('')
</script>

<template>
  <AutocompleteRoot v-model="model" :open-on-click="true" :open-on-focus="true">
    <AutocompleteAnchor>
      <AutocompleteInput placeholder="Search..." />
      <AutocompleteCancel>X</AutocompleteCancel>
    </AutocompleteAnchor>

    <AutocompletePortal>
      <AutocompleteContent>
        <AutocompleteViewport>
          <AutocompleteItem v-for="option in options" :key="option" :value="option">
            {{ option }}
          </AutocompleteItem>
        </AutocompleteViewport>
      </AutocompleteContent>
    </AutocompletePortal>
  </AutocompleteRoot>
</template>
```

## Steps to reproduce

1. Click the input to open the dropdown.
2. Select an item, or type some text and click elsewhere so the input loses focus.
3. With the dropdown closed, click the X (`AutocompleteCancel`) button.

## Actual behavior

The input becomes empty, but the items in the dropdown are still filtered by the
previous input text.

## Expected behavior

After the cancel button clears the input, the input has focus and the dropdown
shows all items again. This must work with and without `v-model` on
`AutocompleteRoot`.
