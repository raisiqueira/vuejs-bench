# Select: Space on a focused item does not reliably select it

This repository is Reka UI. The library source is in `packages/core`.

## Steps to reproduce

1. Render a `Select` with several options. The problem is easiest to see with `multiple`.
2. Open the select.
3. Move focus to an option, for example with the arrow keys.
4. Press Space on the focused `SelectItem`.

## Actual behavior

Space often does not select or toggle the focused option. Enter on the same
focused option works. The problem is specific to Space.

## Expected behavior

The documented keyboard interaction says that Space on a focused item selects it.
When focus is on a `SelectItem`, Space must:

- select the item (single select) or toggle it (multiple select), the same as Enter;
- not scroll the listbox or the page.

Typeahead must keep working for labels that contain spaces. When the user has
already started a typeahead search (for example typed `new`), Space is part of
the search string, so `new j` still moves focus to "New Jersey". A Space that
extends a search must also not scroll.
