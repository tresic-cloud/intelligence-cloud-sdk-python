# Changelog

## 0.1.0: Base Intelligence Seat manager lines (2026-11-18)

- On the Base Intelligence Seat a manager's own phone line is not captured. `add_manager(customer, user, *, activate_alerts=True)` no longer takes `own_extension` (`activate_alerts` is keyword-only, so an extension passed positionally raises `TypeError`): a manager is mapped to exactly the end-user lines at the location, and their own extension is never mapped, nor added to First Alert or Insights Hub.
- `sync_numbers` sets every manager's mapping to exactly the lines (as for integration users); a number on a manager that is not a line is removed.

## 0.1.0: review changes (2026-11-17)

- Licence: the Intelligence Cloud SDK Licence (Copyright (c) 2026 Creo Solutions, Inc. d/b/a Tresic), the same text in every SDK: partners, their customers and contractors may use, copy, modify and distribute the SDK solely to access Intelligence Cloud; provided as is.
- **Python 3.10 or later, `httpx` 0.27 or later.** The package ships `py.typed`.
- `provision_seat_customer` never adopts a company by its name alone. Pass `SeatCustomerSpec.company_id` (store it from the first run). Without it, a same-named company is used only when its primary contact email is `admin_email`; otherwise `ConflictError` (code `company_name_conflict`) is raised before anything is written. New helper `companies.find_companies`.
- Integration users: `add_integration_user` (password sign-in, tagged `department: "integration"`, all products, both groups, alert email off, every line) and `list_integration_users`. Integration users are never counted as seats or managers and get every new line. A manager now needs all three products.
- `remove_user` releases only an end user's line, and only when no other end user holds it. Removing a manager, an integration user or anyone holding several lines never takes a line off anyone else. `sync_numbers` counts as lines only end users holding exactly one number.
- `SeatCustomer.exclude_user_ids` / `exclude_emails`: users every workflow ignores.
- `offboard_customer`: pause the After Call webhook, clear the First Alert webhook, stop the connector, deactivate integration users, deactivate the company.
- Connectors are matched on their phone-system domain. A re-run updates a connector in `error`, stopped or changed with the settings passed (including a new key) and restarts it; it never creates a second one.
- `parse_after_call_event` returns `UnknownEvent` for event types it doesn't handle, and takes `max_bytes` (256 KB, `MAX_EVENT_BYTES`; `PayloadTooLargeError` above it).
- Token stores may implement `lock()` for sharing tokens across processes; new `FileTokenStore`. A 429 on renewal retries the same refresh token instead of signing in.
- `Retry-After` is honoured up to 60 seconds; a longer one raises `RateLimitError` at once. `Client(login_rate_limit_wait=60)` makes the sign-in wait configurable.
- `Client(keep_unknown_fields=True)` keeps response fields the reference doesn't list yet on customer-lifecycle reads (never sign-in links; conversation-data reads always keep only documented fields).
- `base_url` must be https (http only for localhost). A `datetime` without a time zone is refused. Alert `numbers` send North American numbers as their last 10 digits.
- Exception text carries only the status, code and request id (plus text the SDK wrote); the server's text stays on `.message`.
- Examples: receivers read their path token from the environment and refuse one shorter than 32 characters; the After Call receiver caps bodies at 256 KB, stores each call id in a persistent queue before answering and reads the call before using it. `examples/after-call-sample.json` for local tests.
- `tools/generate.py` takes the spec path (required) and `--check`.

## 0.1.0 (2026-11-16)

First release.

- Client with email and password sign-in for a dedicated integration user, automatic token renewal (single-use refresh tokens, renewal serialised across threads) and a pluggable token store.
- One method per API operation, grouped by reference section, with `iter_*` paging.
- Filters checked before sending: unknown filters, date-only values, enum values, up to 25 numbers and 50 location ids.
- Responses carry only the fields in the published reference.
- Read-merge-write helpers for every full-replacement write.
- User create with an idempotency key and recovery when a refused create left the user behind.
- Connector create, reactivate and deactivate wait for the final status, checking every 10 seconds for up to 10 minutes (`timeout=`, `ConnectorsAPI.check_interval`).
- Base Intelligence Seat workflows: provision a customer, add managers and end users, change an extension, remove a user, list users by type, sync numbers.
- Workflows email each user's invitation last, after their lines are mapped. Alert rules are created switched off and come on with the first manager (`activate_seat_alerts`).
- Conversation intelligence: calls, transcripts, recording links, alerts, tasks, insights.
- After Call and First Alert webhook configuration, After Call event parsing and de-duplication.
- New calls and alerts reach you on the After Call and First Alert webhooks (2026-11-17). `examples/alert_webhook_receiver.py` is a First Alert receiver: it reads only the alert id, answers at once and fetches the alert and its call with `get_alert(alert_id, with_call=True)`. The README covers a one-off catch-up after an outage.
