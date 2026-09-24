Searching quickly can show results for an older query after the latest request
has already completed. Fix the search composable so only the current query can
update the result. Preserve its API and its loading state.
