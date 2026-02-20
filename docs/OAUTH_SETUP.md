# OpenAI OAuth Setup (OpenClaw-style)

Required env vars:

- `QA_OPENAI_OAUTH_CLIENT_ID`
- `QA_OPENAI_OAUTH_REDIRECT_URI`
- optional: `QA_OPENAI_OAUTH_AUTH_URL` (default `https://auth.openai.com/oauth/authorize`)
- optional: `QA_OPENAI_OAUTH_TOKEN_URL` (default `https://auth.openai.com/oauth/token`)
- optional: `QA_OPENAI_OAUTH_CLIENT_SECRET`

## Flow

1. FE calls `POST /api/llm/oauth/start`
2. Open returned `authUrl`
3. After login/consent, provider redirects to `QA_OPENAI_OAUTH_REDIRECT_URI`
4. Callback endpoint `GET /api/llm/oauth/callback` exchanges code for token
5. Token is saved in `out/auth-profiles.json`
6. `GET /api/llm/oauth/status?provider=openai` shows connection status

## Notes

- Without `CLIENT_ID` + `REDIRECT_URI`, `/api/llm/oauth/start` returns error.
- Saved OAuth token is used automatically for LLM calls when provider chain includes `openai`.
