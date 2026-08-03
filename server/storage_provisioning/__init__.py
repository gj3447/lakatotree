"""Privileged, operator-run storage provisioning resources.

These resources are deliberately separate from the application migration:
the NOLOGIN object owner cannot change bootstrap-owned target-database system
routine ACLs.
"""
