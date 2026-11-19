"""Provision a Base Intelligence Seat customer, then add an end user and a manager. Admin login.

Dry run by default: prints what it would create. Pass --apply to make the changes.
Customer Threat phrases are provided by your Tresic contact: put them one per line in the file
named by IC_THREAT_PHRASES_FILE.
"""
import os
import sys

from _common import client_from_env
from intelligence_cloud import ConnectorSpec, LocationSpec, SeatCustomerSpec, UserSpec

phrases_file = os.environ.get("IC_THREAT_PHRASES_FILE")
phrases = [l.strip() for l in open(phrases_file) if l.strip()] if phrases_file else None

spec = SeatCustomerSpec(
    company_id=os.environ.get("IC_COMPANY_ID") or None,  # store customer.company_id after the first run
    company_name="Riverbend Auto Group",
    admin_name="Pat Lee", admin_email="pat.lee@example.com", admin_phone="+15555550100",
    location=LocationSpec(name="Riverbend - Main", street="1 River Rd", city="Springfield", state="IL",
                          country="US", zipcode="62701", vertical=os.environ.get("IC_VERTICAL", "csps-msps")),
    threat_phrases=phrases,
    mfa_off=True,
    connector=ConnectorSpec(api_url=os.environ.get("IC_PBX_API_URL", "https://pbx.example.com/ns-api/v2"),
                            domain=os.environ.get("IC_PBX_DOMAIN", "riverbend.example.com"),
                            api_key=os.environ.get("IC_PBX_API_KEY", "")),
)
# Invitations are emailed only after each user's lines are mapped. send_invitation=False holds them back.
manager = UserSpec("dana.cho@example.com", "Dana", "Cho", send_invitation=False)
agent = UserSpec("sam.ortiz@example.com", "Sam", "Ortiz", send_invitation=False)

if "--apply" not in sys.argv:
    print(f"Would provision {spec.company_name!r} with location {spec.location.name!r},")
    print("groups 'Manager Alerts' and 'Insights Hub Access', alerts 'Upset Customer' and 'Customer Threat',")
    print(f"then add end user {agent.email} on extension 2101 and manager {manager.email},")
    print("which switches both alerts on.")
    print("Customer Threat phrases:", f"{len(phrases)} loaded" if phrases else "missing (set IC_THREAT_PHRASES_FILE)")
    print("Run with --apply to make the changes.")
    sys.exit(0)

with client_from_env("admin") as admin:
    customer = admin.workflows.provision_seat_customer(spec)
    print("company", customer.company_id, "location", customer.location_id,
          "connector", customer.connector_status, customer.connector_state_reason or "")
    admin.workflows.add_frontline_user(customer, agent, "2101")
    mgr = admin.workflows.add_manager(customer, manager)   # switches both alerts on
    print("alerts switched on:", len(mgr.alerts_activated))
    print("done")
