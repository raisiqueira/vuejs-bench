The search field shows the initial query, but edits do not update the parent
and parent resets leave the field stale. Fix the synchronization while
preserving the current parent usage. Trim surrounding whitespace from edits
before they reach the parent.
