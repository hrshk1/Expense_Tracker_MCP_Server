# Authorization and RBAC in the Expense Tracker MCP Server

This file explains how login and role based access control are implemented in
simple language, then explains the important code pieces and common interview
questions.

## What Was Added

The server now has authentication and authorization for HTTP MCP clients.

Authentication means checking who is trying to connect. In this project, the
server shows a local login page and accepts only email addresses ending with
`@yulu.bike`.

Authorization means checking what that logged-in user is allowed to do. This is
handled with two roles:

- `reader`: can list expenses and summarize expenses.
- `writer`: can list expenses, summarize expenses, and add expenses.

All valid Yulu Bike emails become readers by default. To make someone a writer,
add their email to the `WRITER_EMAILS` environment variable.

Example:

```powershell
$env:WRITER_EMAILS = "alice@yulu.bike,bob@yulu.bike"
$env:MCP_BASE_URL = "http://localhost:8000"
.\.venv\Scripts\python.exe main.py
```

## Important Security Note

This is a local demo login. It checks that the email has the correct
`@yulu.bike` format, but it does not prove that the person really owns that
email account.

For real production security, the same RBAC idea should be connected to a real
identity provider such as Google Workspace, Microsoft Entra ID, Auth0, or the
company's own SSO system. Then the provider proves the user owns the email.

## Files Changed

### `auth.py`

This file contains the local OAuth provider and RBAC helpers.

Important constants:

```python
READ_SCOPE = "expenses:read"
WRITE_SCOPE = "expenses:write"
```

These scopes are permission labels. The server uses them to decide which tools
are visible and callable.

Important helper functions:

```python
is_yulu_bike_email(email)
```

This checks that the email has exactly one `@`, has a non-empty local part, and
uses the `yulu.bike` domain.

```python
parse_writer_emails()
```

This reads `WRITER_EMAILS` from the environment. Invalid emails are ignored.

```python
get_role_for_email(email)
```

This returns `writer` if the email is in `WRITER_EMAILS`; otherwise it returns
`reader`.

```python
get_scopes_for_role(role)
```

This maps roles to permissions:

- `reader` gets `expenses:read`.
- `writer` gets `expenses:read` and `expenses:write`.

### `YuluBikeOAuthProvider`

`YuluBikeOAuthProvider` extends FastMCP's in-memory OAuth provider. It keeps the
standard FastMCP OAuth routes such as `/authorize`, `/token`, and `/register`,
and adds one local route:

```text
/login
```

The login flow works like this:

1. A client connects without a token.
2. FastMCP returns an authentication challenge.
3. The client starts the OAuth flow by opening `/authorize`.
4. The provider creates a temporary pending login request.
5. The browser is redirected to `/login`.
6. The user enters a Yulu Bike email.
7. If the email is valid, the server creates an authorization code.
8. The client exchanges that code at `/token`.
9. The server returns an access token and refresh token.
10. Future MCP requests include the access token.

The access token stores:

- email in the token subject and claims.
- role in token claims.
- scopes such as `expenses:read` and `expenses:write`.

### `main.py`

The FastMCP server is now created with auth enabled:

```python
mcp = FastMCP(
    "Expense Tracker MCP Server",
    version="1.0.0",
    auth=create_auth_provider(),
)
```

Tools are protected with scope checks:

```python
@mcp.tool(auth=require_writer)
async def add_expense(...):
```

Only users with `expenses:write` can add expenses.

```python
@mcp.tool(auth=require_reader)
async def list_expenses(...):
```

Only users with `expenses:read` can list expenses.

```python
@mcp.tool(auth=require_reader)
async def summarize_expenses_by_category(...):
```

Only users with `expenses:read` can summarize expenses.

## Environment Variables

### `MCP_BASE_URL`

This tells the OAuth provider the public URL of the server. Locally it defaults
to:

```text
http://localhost:8000
```

Set it when the server is hosted somewhere else.

### `WRITER_EMAILS`

This controls who has writer access. It is a comma-separated list.

Example:

```powershell
$env:WRITER_EMAILS = "alice@yulu.bike,bob@yulu.bike"
```

Anyone with a valid `@yulu.bike` email that is not in this list becomes a
reader.

### `EXPENSE_DB_PATH` and `EXPENSE_DATA_DIR`

These existing variables still work. They control where the SQLite database is
stored.

## RBAC in Simple Words

RBAC means "Role Based Access Control".

Instead of checking every email manually in every tool, the server gives each
user a role. The role decides the permissions.

In this project:

```text
email -> role -> scopes -> allowed tools
```

Example:

```text
harsh@yulu.bike
  -> reader
  -> expenses:read
  -> list_expenses and summarize_expenses_by_category
```

Example:

```text
alice@yulu.bike
  -> writer
  -> expenses:read and expenses:write
  -> list_expenses, summarize_expenses_by_category, and add_expense
```

## OAuth Flow in Simple Words

OAuth is a way for the MCP client to get a token instead of sending login
details with every request.

The token is like a temporary pass. After login, the client sends this pass with
future requests. The server checks the pass and sees which scopes it has.

The important parts are:

- Authorization code: a short-lived code created after login.
- Access token: the token used to call MCP tools.
- Refresh token: a token used to get a new access token later.
- Scope: a permission string like `expenses:read`.

## Interview Questions and Answers

### What is authentication?

Authentication checks who the user is. Here, the user enters an email on the
login page, and the server accepts only emails ending in `@yulu.bike`.

### What is authorization?

Authorization checks what the authenticated user can do. Here, the server uses
reader and writer roles.

### What is RBAC?

RBAC means Role Based Access Control. Users are assigned roles, and roles are
mapped to permissions. It is cleaner than writing separate email checks inside
every function.

### Why use scopes?

Scopes are small permission strings. FastMCP already understands scope checks,
so tools can be protected with `require_scopes(...)`.

### What can a reader do?

A reader can call:

- `list_expenses`
- `summarize_expenses_by_category`

### What can a writer do?

A writer can call:

- `add_expense`
- `list_expenses`
- `summarize_expenses_by_category`

### How does the server know who is a writer?

The server reads the `WRITER_EMAILS` environment variable. If the logged-in
email is in that list, the user becomes a writer. Otherwise, the user becomes a
reader.

### Why is this called local demo auth?

Because the login form only checks the email text. It does not verify ownership
of the mailbox. A production system should use a real identity provider.

### What happens if someone uses `person@gmail.com`?

The login page rejects it because it does not end with `@yulu.bike`.

### What happens if a reader calls `add_expense`?

The reader token does not contain `expenses:write`, so FastMCP does not allow
that tool call.

### Where are tokens stored?

Tokens are stored in memory in the running Python process. If the server
restarts, users must log in again.

### Is the SQLite database auth-related?

No. The database still stores expenses. Auth controls who can call the tools
that read or write that database.

### Why not check roles directly inside `add_expense`?

FastMCP already supports tool-level authorization. Using `auth=require_writer`
keeps security rules close to tool registration and avoids mixing business
logic with access-control logic.

## Quick Manual Checks

Check helper behavior:

```powershell
.\.venv\Scripts\python.exe -c "from auth import is_yulu_bike_email; print(is_yulu_bike_email('person@yulu.bike')); print(is_yulu_bike_email('person@gmail.com'))"
```

Check syntax:

```powershell
.\.venv\Scripts\python.exe -m py_compile main.py auth.py
```

Run locally:

```powershell
$env:WRITER_EMAILS = "alice@yulu.bike"
$env:MCP_BASE_URL = "http://localhost:8000"
.\.venv\Scripts\python.exe main.py
```
