# Intelligence Cloud Python SDK

Python client for the Intelligence Cloud partner API. It covers both jobs:

- **Customer lifecycle** with admin credentials (a reseller admin login): companies, locations, users, products, connectors, First Alert, Insights Hub, and the Base Intelligence Seat workflows.
- **Conversation intelligence** with frontline credentials (a frontline user login): calls, transcripts, recordings, alerts, tasks, insights, and the After Call webhook.

Version 0.1.0. Python 3.10 or later. One dependency: `httpx` (0.27 or later).

The API reference is at https://docs.intelligence.cloud/reference.html, built from https://docs.intelligence.cloud/openapi.yaml.

## Install

```bash
pip install intelligence-cloud          # or: uv add intelligence-cloud
```

The import name is `intelligence_cloud`.

Alternative, from the source download:

```bash
unzip python.zip && cd python
pip install .            # or: uv pip install .
```

To run the examples without installing: `uv run --with httpx --with-editable . python examples/whoami.py`.

## Credentials

Today every integration signs in with the email and password of a **dedicated integration user**. Turn MFA off for that user's company (`mfa_off=True` in `provision_seat_customer`, or `PATCH /companies/{id}` with `mfa_enforced: false`). **API keys arrive in December 2026.**

Use one client per credential:

| Credential | Role | Use it for |
|---|---|---|
| Admin | `reseller_admin` | `client.companies`, `client.users`, ... and `client.workflows` |
| Frontline | `frontline_user` | `client.intelligence` (calls, alerts, tasks, insights) |

Admin logins get empty lists from the conversation-data endpoints by design. `client.intelligence` checks the role once and raises `FrontlineRequiredError` instead of returning empty data.

Keep credentials out of source code. Read them from your secret store or environment. Send secrets to Tresic only through **security@tresic.cloud**, and report security issues there too.

```python
import os
from intelligence_cloud import Client

admin = Client(email=os.environ["IC_ADMIN_EMAIL"], password=os.environ["IC_ADMIN_PASSWORD"])
data = Client(email=os.environ["IC_DATA_EMAIL"], password=os.environ["IC_DATA_PASSWORD"])
```

`Client(base_url="https://app.intelligence.cloud/api/v1", email, password, token_store=None, timeout=30)`; also `user_agent=` (prefixed to the SDK's own), `max_retries=3`, `login_rate_limit_wait=60` (seconds; `0` raises `RateLimitError` at once, better inside a web request) and `keep_unknown_fields=False` (see "Rules the SDK applies for you"). `base_url` must be `https://` (`http://` only for `localhost`). If you pass your own `transport=`, keep certificate verification on.

### Sign-in, tokens and sign-out

- The client signs in on first use and keeps the access and refresh tokens in memory.
- Sign-in is limited to 5 per minute per IP. Sign in once per job and reuse the client. On a 429 at sign-in the client waits `login_rate_limit_wait` seconds (60) once.
- On a 401 the client renews the token once and retries. Refresh tokens are single-use: the new pair is stored before it is used and an old refresh token is never sent again. Renewal is serialised with a lock, so threads sharing a client renew once. A 429 on renewal is waited out and the same refresh token is sent again; it never turns into a sign-in.
- To keep tokens across runs, pass a `token_store` with `get()` and `set(tokens)`. Store tokens like passwords.
- **Several processes, one integration user** (workers, serverless, a cron job next to a web app): use one shared store that also has `lock()`, a context manager holding a lock across processes. The client signs in and renews inside it and re-reads the store first, so two processes never send the same refresh token (a replayed refresh token ends the session everywhere). `FileTokenStore(path)` does this for processes on one machine (file mode 0600, lock file beside it). Never create a client per request.
- `client.close()` closes connections. It does **not** sign out.
- `client.logout()` signs out and **ends every session of that user, including the web app**. The SDK never calls it by itself.
- Sign-in returning `mfa_required` raises `MfaRequiredError`: "Integration users need MFA off for their company. API keys arrive in December 2026."

## Quick start: customer lifecycle (admin)

Provision a Base Intelligence Seat customer: one location, After Call for end users, First Alert and Insights Hub for managers, the "Upset Customer" and "Customer Threat" alerts routed to "Manager Alerts", and an "Insights Hub Access" group.

```python
from intelligence_cloud import Client, SeatCustomerSpec, LocationSpec, ConnectorSpec, UserSpec

admin = Client(email=..., password=...)

customer = admin.workflows.provision_seat_customer(SeatCustomerSpec(
    company_id=saved_company_id,              # None the first time; store customer.company_id and pass it on re-runs
    company_name="Riverbend Auto Group",
    admin_name="Pat Lee", admin_email="pat.lee@example.com", admin_phone="+15555550100",
    location=LocationSpec(name="Riverbend - Main", street="1 River Rd", city="Springfield",
                          state="IL", country="US", zipcode="62701", vertical="<vertical id or key>"),
    threat_phrases=customer_threat_phrases,   # from your Tresic contact
    mfa_off=True,                             # the company has an integration user
    connector=ConnectorSpec(api_url="https://pbx.example.com/ns-api/v2",
                            domain="riverbend.example.com", api_key=phone_system_key),
    sso_domain="riverbend.example.com",       # optional: returns the DNS TXT record to publish
))

# End users first: each line is mapped, then the invitation is emailed.
admin.workflows.add_frontline_user(customer, UserSpec("sam.ortiz@example.com", "Sam", "Ortiz"), "2101")
# The first manager switches the two alerts on, then gets the invitation.
admin.workflows.add_manager(customer, UserSpec("dana.cho@example.com", "Dana", "Cho"))
```

- **Customer Threat phrases are provided by your Tresic contact.** Pass them as `threat_phrases`. Creating the Customer Threat alert without them raises `InvalidRequestError`.
- The primary contact (`admin_email`) is always invited as customer admin by email.
- Every workflow can be run again. **Store `customer.company_id` and pass it as `company_id` on every re-run.** Without it, a company with the same name is used only when its primary contact email is `admin_email`; any other company with that name raises `ConflictError` (code `company_name_conflict`) before anything is written. The location, groups and rules are found by name, users by email, and the connector by its phone-system domain. A company or location found inactive raises unless `reactivate=True`.
- Both alert rules are created **switched off**. `add_manager` switches them on once the manager is set up (`activate_alerts=True`, the default). To switch them on yourself, pass `activate_alerts=False` and call `activate_seat_alerts(customer)` when you are ready. Re-running `provision_seat_customer` never switches a rule off.
- Users are created **without** an invitation. The workflow maps their lines and sets their products and groups, and only then emails the invitation. If a mapping is refused, `ExtensionMappingError` is raised and no invitation has been sent. Pass `UserSpec(..., send_invitation=False)` to invite later with `admin.users.resend_invitation(company_id, user_id)`.
- The connector connects in the background. The workflow checks it every 10 seconds, for up to 10 minutes (`ConnectorSpec(timeout=...)`), until it is `active` or `error`, and records `connector_status` and `connector_state_reason` on the result. A key that cannot create call subscriptions ends in `error` / `invalid_permissions`: use a read/write key. Re-run the workflow with the corrected key: a connector found in `error`, stopped, or with changed settings is updated with the settings you pass and restarted, never duplicated.
- Get the customer object back later with `admin.workflows.get_seat_customer(company_id)`.

### Seat workflows

| Method | Does |
|---|---|
| `provision_seat_customer(spec)` | Company, MFA off (optional), products, location, groups, both rules (switched off), connector (optional), Insights Hub access, SSO domain claim (optional). Returns `SeatCustomer` with every id. |
| `get_seat_customer(company_id)` | Rebuilds `SeatCustomer` from what is configured. |
| `add_frontline_user(customer, user, extension)` | Creates an end user (no invitation yet) with After Call on their own line and alert email off, maps the line, adds it to every manager, First Alert and Insights Hub, then emails the invitation. |
| `add_manager(customer, user, *, activate_alerts=True)` | Creates a manager (no invitation yet) with all three products, both groups and alert email on, maps all end-user lines at the location, switches both alerts on, then emails the invitation. The manager's own phone line is not captured on the Seat: it is never mapped, nor added to First Alert or Insights Hub. |
| `activate_seat_alerts(customer)` | Switches on the Upset Customer and Customer Threat rules. Returns the ids it switched on. |
| `change_user_extension(customer, user_id, old, new)` | Moves an end user's line: their mapping, every manager, First Alert, Insights Hub. |
| `add_integration_user(customer, user)` | Creates the customer's integration (data-reading) user: password sign-in, tagged `department: "integration"`, all three products, both groups, alert email off, every line. Never counted as a seat or manager; later end users' lines are added to it. Invitation last. |
| `remove_user(customer, user_id, keep_extensions=False)` | Removes the user from groups, clears their numbers, then deactivates. Only an end user's line is released, and only when no other end user holds it: it comes off managers, integration users, First Alert and Insights Hub (unless kept). Removing a manager, an integration user or anyone holding several lines never takes a line off anyone else. |
| `list_frontline_users(customer)` / `list_managers(customer)` / `list_integration_users(customer)` | The location's users, classified: end users have After Call only; managers have all three products; integration users are tagged `department: "integration"`. |
| `sync_numbers(customer, dry_run=False)` | Recomputes the location's lines (each end user's single extension) and pushes them to managers, integration users, First Alert and Insights Hub. Managers and integration users end up with exactly the lines; any other number on their mapping is removed. `dry_run=True` returns the changes only. |
| `offboard_customer(customer, deactivate_company=True)` | A customer leaves: pauses the After Call webhook, clears the First Alert webhook, stops the connector, deactivates the integration users, then deactivates the company. Safe to run again. |

To keep a user out of every workflow (for example a person you manage by hand), list them in `customer.exclude_user_ids` or `customer.exclude_emails`.

Number mappings need an **active** connector. When a mapping is refused, the workflow raises `ExtensionMappingError` with `user_id` set: the user exists but has not been invited, and you run the workflow again once the connector is active. The re-run finds the user, finishes the setup and emails the invitation. A re-run also re-sends the invitation to any user who has not accepted one yet. An extension can belong to one location only: a conflict raises `ConflictError` with the message "Extension is already monitored at another location." and the clashing numbers in `.extensions`.

## Quick start: conversation intelligence (frontline)

```python
from datetime import datetime, timedelta, timezone
from intelligence_cloud import Client

data = Client(email=..., password=...)
since = datetime.now(timezone.utc) - timedelta(days=1)

for call in data.intelligence.iter_calls(date_from=since, sentiment="negative"):
    detail = data.intelligence.get_call(call["id"])
    transcript = data.intelligence.get_transcript(call["id"])

for alert in data.intelligence.iter_alerts(alert_name="Upset Customer", date_from=since):
    print(alert["id"], alert["call_id"])
```

- `phone` and `text` both search the one search field (names, numbers, summary and transcript text). Pass one or the other.
- Without `date_from`, calls and alerts start at 00:00 UTC seven days ago.
- Dates accept time-zone-aware `datetime` objects or full RFC 3339 strings and are sent in UTC. A date alone (`2026-11-01`) and a `datetime` without a time zone are refused: use `2026-11-01T00:00:00Z` or `datetime.now(timezone.utc)`.
- `alert_name` is the exact, case-sensitive rule name.
- Calls and alerts as they happen arrive on the After Call and First Alert [webhooks](#webhooks). Don't poll the API for new data: read it when a person asks for something or when a webhook tells you to fetch details, and run scheduled jobs (exports, digests) at most once a day over a bounded date window.

### Recordings

```python
link = data.intelligence.get_recording_url(call_id)
if link:
    audio = httpx.get(link.url)   # WAV; no Authorization header; Range requests work
```

The link is signed and valid for 120 minutes (`link.expires_at`). Anyone with the link can download the audio: treat it as a secret, never log it, and fetch a new one when it expires. Returns `None` when the call has no recording.

## Method list

Every API operation is a method named after its `operationId` in snake case, grouped by reference section. Path ids are positional; filters are keyword arguments; request bodies are a `dict` with the field names from the reference.

- List methods return a `Page` (`items`, `next_cursor`, `has_more`, `total`, `raw`). `items` holds the records with the `type`/`attributes` wrapper removed.
- Each list method has an `iter_*` twin that follows cursors 100 at a time.
- Single reads and writes return the response body as documented (`intelligence_cloud.unwrap(body)` returns the record inside).

| Namespace | Methods |
|---|---|
| `client.resellers` | `get_reseller_branding`, `update_reseller_branding`, `get_reseller_smtp_settings`, `save_reseller_smtp_settings`, `delete_reseller_smtp_settings` |
| `client.companies` | `list_companies` / `iter_companies`, `create_company`, `get_companies_mfa_summary`, `get_company`, `update_company`, `deactivate_company`, `reactivate_company`, `get_company_branding`, `update_company_branding`; helpers `add_products`, `remove_products`, `find_company`, `find_companies` |
| `client.sso` | `list_company_domains`, `claim_company_domain`, `remove_company_domain`, `list_domain_verifications`, `verify_domain`, `get_identity_provider`, `connect_identity_provider`, `disconnect_identity_provider`, `test_identity_provider` |
| `client.products` | `list_products`, `list_company_products`, `list_user_products`, `enable_user_product`, `disable_user_product` |
| `client.locations` | `list_verticals`, `list_company_locations` / `iter_company_locations`, `create_location`, `get_location`, `update_location`, `deactivate_location`, `reactivate_location`; helpers `add_products`, `remove_products`, `find_location` |
| `client.groups` | `list_user_groups` / `iter_user_groups`, `create_user_group`, `get_user_group`, `update_user_group`, `delete_user_group`, `get_user_group_membership`, `set_user_group_membership`; helpers `add_members`, `remove_members`, `add_user_to_groups`, `remove_user_from_groups`, `user_group_ids`, `find_group` |
| `client.connectors` | `list_connector_types`, `test_connector`, `list_location_connectors` / `iter_location_connectors`, `create_connector`, `get_connector`, `update_connector`, `deactivate_connector`, `reactivate_connector`, `list_company_connectors` / `iter_company_connectors`; helpers `wait_for_status`, `find_connector` |
| `client.first_alert` | `list_alert_rules` / `iter_alert_rules`, `create_alert_rule`, `get_alert_rule`, `update_alert_rule`, `delete_alert_rule`, `duplicate_alert_rule`, `get_first_alert_config`, `save_first_alert_config`, `test_first_alert_webhook`, `get_alert_notification_preferences`, `set_alert_email_preferences`, `set_alert_digest_preferences`; helpers `add_monitored_numbers`, `remove_monitored_numbers`, `set_monitored_numbers`, `add_rule_groups`, `remove_rule_groups`, `find_rule` |
| `client.insights_hub` | `get_insights_hub_setup`, `save_insights_hub_setup`, `update_insights_hub_setup`, `get_insights_hub_config`, `update_insights_hub_config`, `get_user_insights_hub_access`; helpers `add_numbers`, `remove_numbers`, `set_numbers`, `add_groups`, `remove_groups` |
| `client.users` | `list_company_users` / `iter_company_users`, `create_company_user`, `get_company_user`, `update_company_user`, `deactivate_company_user`, `reactivate_company_user`, `resend_invitation`, `reset_password`, `get_user_number_mappings`, `set_user_number_mappings`, `list_location_users` / `iter_location_users`, `get_location_user`; helpers `find_user_by_email`, `add_locations`, `remove_locations`, `user_numbers`, `add_numbers`, `remove_numbers`, `set_numbers` |
| `client.after_call_settings` | `get_user_after_call_settings`, `update_user_after_call_settings` |
| `client.account` | `get_me`, `list_visible_locations` / `iter_visible_locations` |
| `client.calls` | `list_calls` / `iter_calls`, `get_call`, `get_call_transcript` |
| `client.alerts` | `list_alerts` / `iter_alerts`, `get_alerts_dashboard` |
| `client.tasks` | `list_tasks` / `iter_tasks` |
| `client.insights` | `get_insights_dashboard`, `list_topic_calls` / `iter_topic_calls` |
| `client.webhooks` | `get_after_call_webhook`, `save_after_call_webhook`, `test_after_call_webhook` |
| `client.intelligence` | `whoami`, `require_frontline`, `search_calls` / `iter_calls`, `get_call`, `get_transcript`, `get_recording_url`, `search_alerts` / `iter_alerts`, `get_alert(alert_id, with_call=False)`, `get_alerts_dashboard`, `list_tasks` / `iter_tasks`, `get_insights_dashboard`, `list_topic_calls` / `iter_topic_calls`, `get_after_call_webhook`, `set_after_call_webhook`, `test_after_call_webhook`, `get_first_alert_webhook`, `set_first_alert_webhook`, `test_first_alert_webhook` |
| `client.workflows` | see "Seat workflows" |
| `client` | `login`, `logout`, `close` |

Module level: `parse_after_call_event`, `UnknownEvent`, `MAX_EVENT_BYTES`, `Deduplicator`, `FileTokenStore`, `unwrap`, `Page`, the error classes and the spec dataclasses.

### Rules the SDK applies for you

- **Filters:** list methods accept only the filters the API supports. The API ignores unknown parameters silently, so the SDK refuses them before sending (`TypeError` for an unknown keyword, `InvalidRequestError` for a bad value). Enums are checked; `numbers` takes up to 25 entries and strips `+`, `-`, spaces and brackets, and sends a North American number as its last 10 digits (`+1 555-555-0142` becomes `5555550142`, which also matches records stored without the 1); `location_id` lists take up to 50 ids.
- **Full-replacement writes** (group members, a user's groups, number mappings, First Alert monitored numbers, Insights Hub numbers and groups, company and location products, rule groups) have `add_*` / `remove_*` helpers that read, merge and write. The First Alert helpers always resend the webhook URL so it is not cleared.
- **User create** always sends an `Idempotency-Key` (reused on retries). If the create returns 422 but left the user behind, the SDK finds the user by email and applies `location_ids`.
- **Connectors:** `create_connector`, `reactivate_connector` and `deactivate_connector` wait for the final status, checking every 10 seconds for up to 10 minutes (`timeout=` in seconds; `wait=False` to return at once). An `error` raises `ConnectorError` with `state_reason`; no final status in time raises `ConnectorTimeoutError`.
- **Responses** carry only the fields in the published reference. Anything else is dropped. With `Client(keep_unknown_fields=True)` new fields the reference does not list yet are kept on the customer-lifecycle (admin) reads; `get_me`, sign-in and every conversation-data read (calls, transcripts, alerts, tasks, insights) always keep only the documented fields. Either way, the one-time sign-in link a user create can return is never passed through or logged.
- **Test endpoints** (connector dry run, webhook tests) report only success and the HTTP status.
- **Retries:** 429 and 5xx are retried up to 3 times with backoff and jitter, honouring `Retry-After` up to 60 seconds. A longer `Retry-After` is not waited out: `RateLimitError` is raised at once with `.retry_after`. 5xx is retried only for reads, updates, deletes and user create, never for other creates.

## Error handling

```python
from intelligence_cloud import ApiError, NotFoundError, ConflictError, ValidationError

try:
    admin.companies.get_company(company_id)
except NotFoundError:
    ...  # also returned for records outside this login's scope
except ApiError as e:
    log.warning("Intelligence Cloud error %s %s request_id=%s", e.status, e.code, e.request_id)
```

Log `status`, `code` and `request_id`, not exception text or response bodies. `str(error)` carries only the status, code and request id, plus text the SDK wrote itself (such as "Extension is already monitored at another location."). The server's own text is on `e.message`: it can echo numbers or names from the request, so keep it out of logs.

| Error | When |
|---|---|
| `ApiError` | Any API error: `status`, `code`, `message`, `request_id` |
| `AuthError` (401), `PasswordExpiredError` | Sign-in failed, or the token could not be renewed |
| `NotFoundError` (404) | Not found, or outside what this login can see |
| `ConflictError` (409) | Duplicate name or email, already active or inactive, extension already monitored (`.extensions`) |
| `ValidationError` (400, 422) | Malformed request or refused value |
| `RateLimitError` (429) | Still rate limited after retries (`.retry_after`) |
| `InvalidRequestError` | Refused by the SDK before sending |
| `MfaRequiredError` | The integration user's company has MFA on |
| `FrontlineRequiredError` | Conversation data asked for with an admin login |
| `ConnectorError`, `ConnectorTimeoutError` | A connector ended in `error`, or did not finish in time |
| `ExtensionMappingError` | A workflow could not map numbers (`.user_id`, `.cause`) |
| `WebhookPayloadError` | A webhook body is not JSON, or is a malformed After Call event (answer 400) |
| `PayloadTooLargeError` | A webhook body is over `max_bytes` (256 KB; answer 413) |

All derive from `IntelligenceCloudError`.

## Webhooks

Webhooks are how your integration hears about new calls and alerts: the After Call webhook for every call, the First Alert webhook for each alert as it fires. Subscribe to them; don't poll the API for new data.

### Configure (admin)

```python
admin.intelligence.set_after_call_webhook(location_id, f"https://hooks.example.com/ic/after-call/{path_token}")
admin.intelligence.test_after_call_webhook(location_id)      # WebhookTestResult(success, http_status)

admin.intelligence.set_first_alert_webhook(location_id, f"https://hooks.example.com/ic/alerts/{alert_path_token}")
admin.intelligence.test_first_alert_webhook(location_id)
```

- The After Call webhook sends **every call at the location**. One URL per location. Pause it with `enabled=False`; there is no delete.
- The First Alert location webhook is set in the location's First Alert configuration. `set_first_alert_webhook` keeps the monitored numbers.

### Receive

- Use HTTPS and put a token of at least 32 random characters in the path, one per location, read from your secret store: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Compare it in constant time (`hmac.compare_digest` on bytes). Requests are not signed: treat the URL as a secret and keep it out of proxy, load balancer and APM logs.
- Answer 2xx within 2 seconds and do the work afterwards. Redirects count as failures. Delivery is tried 3 times, then dropped.
- `parse_after_call_event` refuses bodies over 256 KB (`PayloadTooLargeError`: answer 413) and returns `UnknownEvent` for event types it doesn't handle: answer 2xx and ignore them. Answer 400 only for a body that isn't JSON or a malformed After Call event, and 404 for a wrong token.
- Treat an event as a notification. Before you write anything from it into another system, read the call with `get_call(event.call.id)` using your frontline integration user; a `NotFoundError` means drop the event.
- Expect repeats of the same `call.id` (retries, and calls with several legs); a later one can carry newer data. Store events durably before acknowledging, and upsert on `call.id`.
- To test locally, post the sample event: `curl -X POST http://localhost:8080/ic/after-call/$IC_WEBHOOK_TOKEN -H 'Content-Type: application/json' -d @examples/after-call-sample.json`, or run `python examples/webhook_receiver.py --self-test`.

FastAPI:

```python
import hmac
import os

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from intelligence_cloud import (AfterCallEvent, Deduplicator, PayloadTooLargeError, WebhookPayloadError,
                                parse_after_call_event)

app = FastAPI()
dedup = Deduplicator()
PATH_TOKEN = os.environ["IC_WEBHOOK_TOKEN"]  # from your secret store
if len(PATH_TOKEN) < 32:
    raise SystemExit("IC_WEBHOOK_TOKEN must be at least 32 characters")

@app.post("/ic/after-call/{token}")
async def after_call(token: str, request: Request, background: BackgroundTasks):
    if not hmac.compare_digest(token.encode(), PATH_TOKEN.encode()):
        raise HTTPException(status_code=404)
    try:
        event = parse_after_call_event(await request.body())
    except PayloadTooLargeError:
        raise HTTPException(status_code=413)
    except WebhookPayloadError:
        raise HTTPException(status_code=400)
    if isinstance(event, AfterCallEvent) and not event.is_test and not dedup.is_duplicate(event):
        background.add_task(handle, event.call.id)   # read the call with get_call, then upsert on its id
    return {"ok": True}
```

Flask:

```python
import hmac

from flask import Flask, abort, request
from intelligence_cloud import AfterCallEvent, PayloadTooLargeError, WebhookPayloadError, parse_after_call_event

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 262_144

@app.post("/ic/after-call/<token>")
def after_call(token):
    if not hmac.compare_digest(token.encode(), PATH_TOKEN.encode()):
        abort(404)
    try:
        event = parse_after_call_event(request.get_data())
    except PayloadTooLargeError:
        abort(413)
    except WebhookPayloadError:
        abort(400)
    if isinstance(event, AfterCallEvent) and not event.is_test:
        durable_queue.put_once(event.call.id)   # a persistent queue keyed on call.id; process outside the request
    return {"ok": True}
```

`Deduplicator.is_duplicate(...)` returns True for a repeat (the same name and meaning in all three SDKs: `isDuplicate` in PHP and TypeScript). It keeps the last 10,000 call ids in memory. With several workers, pass a shared `store` whose `add(key)` returns True only for a new key (for example a shared cache's set-if-absent with an expiry). Use it to skip repeat work, not to drop updates: when you keep a copy of the call, upsert on `call.id`.

### Receive First Alert

The First Alert webhook posts the alert that fired: the alert id, the rule, the location, the call and the time. Read only the alert id, answer 2xx at once, then fetch the alert and its call with a frontline integration user in Manager Alerts:

```python
@app.post("/ic/alerts/{token}")
async def first_alert(token: str, request: Request, background: BackgroundTasks):
    if not hmac.compare_digest(token.encode(), ALERT_TOKEN.encode()):   # IC_ALERT_WEBHOOK_TOKEN, 32+ characters
        raise HTTPException(status_code=404)
    alert_id = alert_id_from(await request.body())     # see examples/alert_webhook_receiver.py
    if alert_id is None:
        raise HTTPException(status_code=400)
    if not alert_dedup.is_duplicate(alert_id):          # a second Deduplicator, keyed on the alert id
        background.add_task(handle_alert, alert_id)
    return {"ok": True}

def handle_alert(alert_id: str):
    alert = data.intelligence.get_alert(alert_id, with_call=True)   # None when this login can't see it
    if alert:
        page_on_call_manager(alert["id"], alert["call_id"])          # ids only; never log the summary
```

If your receiver was unavailable, read the window you missed once and skip alerts you have already handled:

```python
for alert in data.intelligence.iter_alerts(date_from=went_down - timedelta(minutes=30), date_to=came_back):
    if not alert_dedup.is_duplicate(alert["id"]):
        handle_alert(alert["id"])
```

Alerts are dated by their call, so start the window 30 minutes before the receiver went down.

## Examples

| File | Shows | Credential |
|---|---|---|
| `examples/whoami.py` | Sign in and print the role | any |
| `examples/export_calls.py` | Export yesterday's calls to CSV (ids, dates, sentiment, duration) | frontline |
| `examples/provision_seat.py` | Provision a Seat customer and add an end user and a manager (dry run unless `--apply`; phrases from the file in `IC_THREAT_PHRASES_FILE`) | admin |
| `examples/webhook_receiver.py` | A dependency-free After Call webhook receiver: 256 KB cap, a persistent queue keyed on `call.id`, a worker that reads each call (`--self-test` to try it offline) | frontline (worker) |
| `examples/after-call-sample.json` | A sample After Call event for local tests | none |
| `examples/alert_webhook_receiver.py` | A dependency-free First Alert webhook receiver that fetches each alert and its call (`--self-test` to try it offline) | frontline |

The admin examples read `IC_ADMIN_EMAIL` and `IC_ADMIN_PASSWORD`; the frontline examples read `IC_DATA_EMAIL` and `IC_DATA_PASSWORD`. `whoami.py` uses whichever pair is set.

## Regenerating from the spec

`src/intelligence_cloud/_generated.py` and `data/spec.json` are generated from `openapi.yaml` (download it from https://docs.intelligence.cloud/openapi.yaml):

```bash
uv run --with pyyaml python tools/generate.py openapi.yaml          # rewrite both files
uv run --with pyyaml python tools/generate.py openapi.yaml --check  # exit 1 if either is out of date
```

## License

Intelligence Cloud SDK Licence. Copyright (c) 2026 Creo Solutions, Inc. d/b/a Tresic. Partners, their customers and contractors working for either may use, copy, modify and distribute the SDK solely to access Intelligence Cloud. Use of the API is governed by the Intelligence Cloud API and SDK Terms (https://docs.intelligence.cloud/terms/api) and your agreement with Tresic or your provider. Provided as is. See `LICENSE`.
