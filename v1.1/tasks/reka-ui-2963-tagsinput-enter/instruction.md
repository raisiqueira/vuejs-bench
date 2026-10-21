# TagsInputInput: Enter submits a form before its draft is committed

This repository is Reka UI. The library source is in `packages/core`.

## Reproduction

Put a `TagsInputInput` inside a native form, type a non-empty draft and press Enter:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import { TagsInputInput, TagsInputRoot } from 'reka-ui'

const values = ref<string[]>([])
const submissions = ref(0)
</script>

<template>
  <form @submit.prevent="submissions++">
    <TagsInputRoot v-model="values">
      <TagsInputInput />
    </TagsInputRoot>
    <button type="submit">Submit</button>
  </form>

  <output>tags: {{ values }}, submissions: {{ submissions }}</output>
</template>
```

## Actual behavior

The form's submit handler runs before the tag is added. Without `@submit.prevent`,
the browser can navigate or submit the form.

A consumer cannot work around this by calling `preventDefault()` on the Enter
keydown: when they do that, `TagsInputInput` does not add the draft at all.

## Expected behavior

- For a non-empty draft, Enter adds the tag, clears the input and prevents the
  form's implicit submission. The keydown event must already be
  `defaultPrevented` when its dispatch returns, because the browser submits the
  form right after the dispatch.
- For an empty draft, Enter does not call `preventDefault()`, so normal form
  submission still works.
- A consumer can still opt out of Enter-to-add: if their own keydown listener on
  the input calls `preventDefault()` (for example `@keydown.enter.prevent`),
  the draft is not added and stays in the input. This must work even when the
  consumer's listener runs after the component's own listener.
