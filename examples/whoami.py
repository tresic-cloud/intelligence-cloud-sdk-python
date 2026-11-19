"""Sign in and show who this integration user is."""
from _common import client_from_env

with client_from_env("any") as client:
    me = client.intelligence.whoami()
    print(f"role={me.get('role')} locations={len(me.get('location_ids') or [])} products={me.get('enabled_products')}")
