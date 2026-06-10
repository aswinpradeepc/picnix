# This file is region-agnostic. Add durable place-level issues for any destination here.

Picnix checks this file during N3 destination validation. Add rows when a place has a reliable restriction or recurring issue that should affect future suggestions.

Use `reject` when the place should not be suggested unless live validation logic improves. Use `warn` only when the place can still be suggested but the note should be carried forward.

| Place name | Issue | Action |
|---|---|---|
