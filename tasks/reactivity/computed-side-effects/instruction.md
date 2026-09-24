The order total is correct, but merely reading it records an audit event.
Make the total a pure derived value. Record one audit event when an order
change actually changes the total. Preserve the composable API.
