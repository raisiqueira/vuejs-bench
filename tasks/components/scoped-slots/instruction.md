The reusable list renders its default items, but custom item slots do not
receive the documented item prop. It also leaves an empty header wrapper when
no header slot is provided. Fix both without changing its public slot names.
