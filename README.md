Expense Tracker MCP Server
==========================

FastMCP server for adding, listing, and summarizing expense entries stored in
SQLite.

## Database location

By default the server uses `expenses.db` beside `main.py` when that directory is
writable. On read-only deployments, set one of these environment variables:

- `EXPENSE_DB_PATH`: full path to the SQLite database file.
- `EXPENSE_DATA_DIR`: writable directory where `expenses.db` should be stored.

If neither variable is set and the app directory is read-only, the server falls
back to `/tmp/expense_tracker_mcp_server/expenses.db`.
