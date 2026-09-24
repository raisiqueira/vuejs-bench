The child counter changes its own display but the parent total stays stale.
Restore one-way data flow: the parent owns the count, and the child reports
increment requests. Keep the existing parent and child public APIs.
