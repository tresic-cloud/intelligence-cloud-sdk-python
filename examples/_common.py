"""Shared by the examples: a client from the environment.

Admin examples read IC_ADMIN_EMAIL / IC_ADMIN_PASSWORD; frontline examples read IC_DATA_EMAIL /
IC_DATA_PASSWORD. Each is a dedicated integration user.
"""
import os
import sys

from intelligence_cloud import Client

PAIRS = {"admin": ("IC_ADMIN_EMAIL", "IC_ADMIN_PASSWORD"), "data": ("IC_DATA_EMAIL", "IC_DATA_PASSWORD")}


def client_from_env(kind: str = "data") -> Client:
    """kind: "admin", "data", or "any" (the first pair that is set)."""
    kinds = ["admin", "data"] if kind == "any" else [kind]
    for k in kinds:
        e, p = PAIRS[k]
        email, password = os.environ.get(e), os.environ.get(p)
        if email and password:
            return Client(email=email, password=password, user_agent="ic-examples/0.1")
    names = " or ".join(f"{PAIRS[k][0]} and {PAIRS[k][1]}" for k in kinds)
    sys.exit(f"Set {names} (a dedicated integration user).")
