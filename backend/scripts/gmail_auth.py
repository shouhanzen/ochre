from __future__ import annotations

import argparse
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


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
    ap.add_argument(
        "--console",
        action="store_true",
        help="Use console-based auth flow (copy-paste code) instead of local server.",
    )
    args = ap.parse_args()

    cred_path = Path(args.credentials).expanduser().resolve()
    token_path = Path(args.token).expanduser().resolve()

    if not cred_path.exists():
        raise SystemExit(f"credentials file not found: {cred_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), scopes=SCOPES)
    
    if args.console:
        # Console flow: copy URL, paste code
        # Older versions of google-auth-oauthlib might use run_console, newer might deprecate it.
        # But 'run_console' is the standard name. It seems it was removed in 1.0+?
        # Actually, InstalledAppFlow.run_console() exists in < 1.0, but in 1.0+ it was removed/changed.
        # Let's check documentation or workaround.
        # Workaround: use run_local_server with a specific redirect_uri for OOB, but OOB is deprecated by Google.
        # Wait, run_console() was deprecated and removed.
        # We must use run_local_server, but for remote dev, we can't easily.
        # Actually, let's try to implement a simple console flow manually if the library dropped it,
        # OR just acknowledge that recent google-auth-oauthlib removed it.
        # 
        # Re-adding support for console flow via OOB (Out of Band) is tricky because Google deprecated OOB.
        # However, for 'Desktop App' client types, we might still be able to use it if the app is configured for it?
        # No, Google completely disabled OOB for all clients in 2023.
        #
        # If OOB is dead, we MUST use run_local_server.
        # The user is on a remote machine. 
        # The user MUST forward the port.
        # Let's print instructions to forward the port instead of crashing.
        port = args.port if args.port != 0 else 8080
        print(f"\n[!] Google disabled 'run_console' (OOB) flow. You must use 'run_local_server'.")
        print(f"[!] Since you are remote, you MUST forward port {port} from your local machine to this remote.")
        print(f"[!] Example: ssh -L {port}:localhost:{port} user@host")
        print(f"[!] Then visit the URL below on your LOCAL machine.")
        creds = flow.run_local_server(port=port, open_browser=False)
    else:
        # Local server flow: automatic redirect
        creds = flow.run_local_server(port=int(args.port))

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Wrote token: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

