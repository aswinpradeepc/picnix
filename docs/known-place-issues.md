# Known Place Issues

Picnix checks this file during N3 destination validation. Add rows when a place has a reliable restriction or recurring issue that should affect future suggestions.

Use `reject` when the place should not be suggested unless live validation logic improves. Use `warn` only when the place can still be suggested but the note should be carried forward.

| Place name | Issue | Action |
|---|---|---|
| Anamudi Peak | Permit required; check the DFO office before suggesting. | reject |
| Eravikulam NP | Seasonal Feb-Mar closure for Nilgiri tahr calving; do not suggest without live confirmation. | reject |
