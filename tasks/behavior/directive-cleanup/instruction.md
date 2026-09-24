The click-outside directive keeps listening after its element is unmounted.
Preserve its current callback behavior while mounted, and release its document
listener when the directive is removed. Mounting it again must not accumulate
old listeners.
