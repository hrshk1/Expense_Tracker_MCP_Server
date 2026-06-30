import html
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from fastmcp.server.auth import require_scopes
from fastmcp.server.auth.auth import ClientRegistrationOptions
from fastmcp.server.auth.providers.in_memory import (
    DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
    DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
    DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS,
    InMemoryOAuthProvider,
)
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

YULU_EMAIL_DOMAIN = "@yulu.bike"
READ_SCOPE = "expenses:read"
WRITE_SCOPE = "expenses:write"
ALL_SCOPES = [READ_SCOPE, WRITE_SCOPE]

require_reader = require_scopes(READ_SCOPE)
require_writer = require_scopes(WRITE_SCOPE)


@dataclass
class PendingAuthorization:
    client_id: str
    params: AuthorizationParams
    scopes: list[str]
    expires_at: float


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_yulu_bike_email(email: str) -> bool:
    normalized = normalize_email(email)
    if normalized.count("@") != 1:
        return False

    local_part, domain = normalized.split("@", 1)
    if not local_part:
        return False

    return f"@{domain}" == YULU_EMAIL_DOMAIN


def parse_writer_emails(value: str | None = None) -> set[str]:
    raw_value = os.getenv("WRITER_EMAILS", "") if value is None else value
    emails = {normalize_email(item) for item in raw_value.split(",")}
    return {email for email in emails if is_yulu_bike_email(email)}


def get_role_for_email(email: str, writer_emails: set[str] | None = None) -> str:
    writers = parse_writer_emails() if writer_emails is None else writer_emails
    return "writer" if normalize_email(email) in writers else "reader"


def get_scopes_for_role(role: str) -> list[str]:
    if role == "writer":
        return [READ_SCOPE, WRITE_SCOPE]
    return [READ_SCOPE]


def create_auth_provider() -> "YuluBikeOAuthProvider":
    base_url = (os.getenv("MCP_BASE_URL") or "http://localhost:8000").rstrip("/")
    return YuluBikeOAuthProvider(
        base_url=base_url,
        resource_base_url=base_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=ALL_SCOPES,
            default_scopes=ALL_SCOPES,
        ),
    )


class YuluBikeOAuthProvider(InMemoryOAuthProvider):
    """Local OAuth provider that accepts only Yulu Bike email addresses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, required_scopes=[READ_SCOPE], **kwargs)
        self.pending_authorizations: dict[str, PendingAuthorization] = {}

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        routes.append(
            Route("/login", endpoint=self.handle_login, methods=["GET", "POST"])
        )
        return routes

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if client.client_id not in self.clients:
            raise AuthorizeError(
                error="unauthorized_client",
                error_description=f"Client '{client.client_id}' not registered.",
            )
        if client.client_id is None:
            raise AuthorizeError(
                error="invalid_request", error_description="Client ID is required."
            )

        requested_scopes = params.scopes or ALL_SCOPES
        allowed_scopes = set(client.scope.split()) if client.scope else set(ALL_SCOPES)
        scopes = [scope for scope in requested_scopes if scope in allowed_scopes]
        if not scopes:
            scopes = [READ_SCOPE]

        request_id = secrets.token_urlsafe(32)
        self.pending_authorizations[request_id] = PendingAuthorization(
            client_id=client.client_id,
            params=params,
            scopes=scopes,
            expires_at=time.time() + DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
        )

        return self._absolute_login_url(request_id)

    async def handle_login(self, request: Request) -> Response:
        if request.method == "GET":
            request_id = request.query_params.get("request_id", "")
            return self._render_login_form(request_id)

        form = await request.form()
        request_id = str(form.get("request_id", ""))
        email = normalize_email(str(form.get("email", "")))
        pending = self._get_pending_authorization(request_id)

        if pending is None:
            return self._render_login_form(
                request_id, "This login request is invalid or expired."
            )
        if not is_yulu_bike_email(email):
            return self._render_login_form(
                request_id, "Please use a valid Yulu Bike email, like name@yulu.bike."
            )

        role = get_role_for_email(email)
        role_scopes = set(get_scopes_for_role(role))
        granted_scopes = [scope for scope in pending.scopes if scope in role_scopes]
        if not granted_scopes:
            granted_scopes = [READ_SCOPE]

        auth_code_value = f"yulu_auth_code_{secrets.token_hex(16)}"
        self.auth_codes[auth_code_value] = AuthorizationCode(
            code=auth_code_value,
            client_id=pending.client_id,
            redirect_uri=pending.params.redirect_uri,
            redirect_uri_provided_explicitly=pending.params.redirect_uri_provided_explicitly,
            scopes=granted_scopes,
            expires_at=time.time() + DEFAULT_AUTH_CODE_EXPIRY_SECONDS,
            code_challenge=pending.params.code_challenge,
            resource=pending.params.resource,
            subject=email,
        )
        del self.pending_authorizations[request_id]

        redirect_url = construct_redirect_uri(
            str(pending.params.redirect_uri),
            code=auth_code_value,
            state=pending.params.state,
        )
        return RedirectResponse(
            url=redirect_url, status_code=302, headers={"Cache-Control": "no-store"}
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if authorization_code.code not in self.auth_codes:
            raise TokenError(
                "invalid_grant", "Authorization code not found or already used."
            )

        del self.auth_codes[authorization_code.code]

        email = authorization_code.subject or ""
        role = get_role_for_email(email)
        claims = {"email": email, "role": role}
        access_token_value = f"yulu_access_token_{secrets.token_hex(32)}"
        refresh_token_value = f"yulu_refresh_token_{secrets.token_hex(32)}"
        access_token_expires_at = int(time.time() + DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS)
        refresh_token_expires_at = None

        if DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS is not None:
            refresh_token_expires_at = int(
                time.time() + DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS
            )

        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        self.access_tokens[access_token_value] = AccessToken(
            token=access_token_value,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=access_token_expires_at,
            resource=authorization_code.resource,
            subject=email,
            claims=claims,
        )
        self.refresh_tokens[refresh_token_value] = RefreshToken(
            token=refresh_token_value,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=refresh_token_expires_at,
            subject=email,
        )
        self._access_to_refresh_map[access_token_value] = refresh_token_value
        self._refresh_to_access_map[refresh_token_value] = access_token_value

        return OAuthToken(
            access_token=access_token_value,
            token_type="Bearer",
            expires_in=DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
            refresh_token=refresh_token_value,
            scope=" ".join(authorization_code.scopes),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        original_scopes = set(refresh_token.scopes)
        requested_scopes = set(scopes or refresh_token.scopes)
        if not requested_scopes.issubset(original_scopes):
            raise TokenError(
                "invalid_scope",
                "Requested scopes exceed those authorized by the refresh token.",
            )

        self._revoke_internal(refresh_token_str=refresh_token.token)

        email = refresh_token.subject or ""
        role = get_role_for_email(email)
        claims = {"email": email, "role": role}
        new_access_token_value = f"yulu_access_token_{secrets.token_hex(32)}"
        new_refresh_token_value = f"yulu_refresh_token_{secrets.token_hex(32)}"
        access_token_expires_at = int(time.time() + DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS)
        refresh_token_expires_at = None

        if DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS is not None:
            refresh_token_expires_at = int(
                time.time() + DEFAULT_REFRESH_TOKEN_EXPIRY_SECONDS
            )

        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        scope_list = [
            scope for scope in refresh_token.scopes if scope in requested_scopes
        ]
        self.access_tokens[new_access_token_value] = AccessToken(
            token=new_access_token_value,
            client_id=client.client_id,
            scopes=scope_list,
            expires_at=access_token_expires_at,
            subject=email,
            claims=claims,
        )
        self.refresh_tokens[new_refresh_token_value] = RefreshToken(
            token=new_refresh_token_value,
            client_id=client.client_id,
            scopes=scope_list,
            expires_at=refresh_token_expires_at,
            subject=email,
        )
        self._access_to_refresh_map[new_access_token_value] = new_refresh_token_value
        self._refresh_to_access_map[new_refresh_token_value] = new_access_token_value

        return OAuthToken(
            access_token=new_access_token_value,
            token_type="Bearer",
            expires_in=DEFAULT_ACCESS_TOKEN_EXPIRY_SECONDS,
            refresh_token=new_refresh_token_value,
            scope=" ".join(scope_list),
        )

    def _absolute_login_url(self, request_id: str) -> str:
        query = urlencode({"request_id": request_id})
        return f"{str(self.base_url).rstrip('/')}/login?{query}"

    def _get_pending_authorization(
        self, request_id: str
    ) -> PendingAuthorization | None:
        pending = self.pending_authorizations.get(request_id)
        if pending is None:
            return None
        if pending.expires_at < time.time():
            del self.pending_authorizations[request_id]
            return None
        return pending

    def _render_login_form(
        self, request_id: str, error_message: str | None = None
    ) -> HTMLResponse:
        safe_request_id = html.escape(request_id, quote=True)
        error_html = ""
        if error_message:
            safe_error = html.escape(error_message)
            error_html = f'<p class="error">{safe_error}</p>'

        return HTMLResponse(
            f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Yulu Bike Login</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Arial, sans-serif;
      background: #f4f7fb;
      color: #162033;
    }}
    main {{
      width: min(92vw, 420px);
      padding: 28px;
      background: #ffffff;
      border: 1px solid #d9e2ef;
      border-radius: 8px;
      box-shadow: 0 14px 34px rgba(22, 32, 51, 0.12);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 700;
    }}
    p {{
      margin: 0 0 20px;
      color: #526074;
      line-height: 1.5;
    }}
    label {{
      display: block;
      margin-bottom: 8px;
      font-weight: 700;
    }}
    input {{
      box-sizing: border-box;
      width: 100%;
      height: 44px;
      padding: 0 12px;
      border: 1px solid #a9b7c9;
      border-radius: 6px;
      font-size: 16px;
    }}
    button {{
      width: 100%;
      height: 44px;
      margin-top: 16px;
      border: 0;
      border-radius: 6px;
      background: #135dd8;
      color: #ffffff;
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
    }}
    .error {{
      padding: 10px 12px;
      border-radius: 6px;
      background: #fff0f0;
      color: #b42318;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Expense Tracker Login</h1>
    <p>Sign in with your Yulu Bike email address to connect to the MCP server.</p>
    {error_html}
    <form method="post" action="/login">
      <input type="hidden" name="request_id" value="{safe_request_id}">
      <label for="email">Yulu Bike email</label>
      <input id="email" name="email" type="email" placeholder="name@yulu.bike" required autofocus>
      <button type="submit">Sign in</button>
    </form>
  </main>
</body>
</html>""",
            headers={"Cache-Control": "no-store"},
        )
