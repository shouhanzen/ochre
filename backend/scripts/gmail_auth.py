from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Create/refresh a Gmail OAuth token for Ochre (read-only).")
    ap.add_argument("--credentials", required=True, help="Path to Google OAuth client JSON (Desktop app).")
    ap.add_argument("--token", required=True, help="Path to write the authorized user token JSON.")
    ap.add_argument(
        "--port",
        type=int,
        default=0,
        help="Local server port for OAuth redirect (0 = auto).",
    )
    args = ap.parse_args()

    cred_path = Path(args.credentials).expanduser().resolve()
    token_path = Path(args.token).expanduser().resolve()

    if not cred_path.exists():
        raise SystemExit(f"credentials file not found: {cred_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes=SCOPES)
    creds = flow.run_local_server(port=int(args.port))

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Wrote token: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

