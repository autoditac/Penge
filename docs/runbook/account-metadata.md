# Correct bank account metadata

An Enable Banking consent has one default owner, but its accounts may belong to different people.
The bank's account name and type may also be incomplete.
Use the authenticated Overview to identify the account by provider, currency and current balance, then read `GET /accounts` to obtain its `account_id` and the intended owner's `entity_id`.
**Do not use the changing balance as an API identifier, and do not put account IDs or real household data in source control.**
Confirm the selected account ID matches the intended account using `GET /net-worth/daily?group=account&account_id=<id>` before writing.

The operator can send `PATCH /accounts/<id>/metadata` with JSON fields `entity_id` (an existing person UUID) and/or `kind` (`checking` or `savings`) through an authenticated session.
The route requires the bank-connections feature to be enabled.
An invalid owner, kind or ID is rejected; it does not create entities or accept unrecognized fields.
Each changed field becomes an explicit override on that account.
Repeat the same request to verify idempotency.
These overrides survive automatic and manual bank syncs; they do not change other accounts on the same consent.

The response returns the effective `account_id`, `entity_id` and `kind`, never an IBAN.
The canonical `/accounts` list reflects the correction immediately.
An analytics refresh is marked pending; run the guarded **Refresh analytics** action and verify household allocation and account history after refresh.
The next scheduled refresh also picks up the pending change.
