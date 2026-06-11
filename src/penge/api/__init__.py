"""Read-only HTTP API over the analytics marts (issue #202, ADR-0035).

The FastAPI application in this package is the typed data backend for
the React WebUI in ``apps/web``. It exposes the dbt marts
(``analytics_marts.mart_net_worth_daily``,
``analytics_marts.mart_cashflow_daily``) and the account dimension as
JSON, with IBAN masking applied server-side and EUR/DKK always
reported in parallel.

The API is strictly read-only: it connects with the same credentials
as the Streamlit dashboard and never issues DML. Write paths (staged
imports, issue #207) land as a separate router with their own ADR.
"""
