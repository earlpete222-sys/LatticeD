# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in LatticeD, please report it
**privately** via email to:

**earlpete222@gmail.com**

Please include:
- A clear description of the vulnerability
- Steps to reproduce
- The affected version or commit hash
- Any suggested mitigation (optional)

You can expect an initial response within 7 days. Please do not disclose the
issue publicly until it has been addressed.

---

## Secrets and API Keys

LatticeD does **not** ship with any production secrets. The following must
be supplied as environment variables before running the system:

| Variable | Purpose | Required |
|---|---|---|
| `LATTICED_SECRET` | API authentication key for the LatticeD HTTP endpoint | Yes for any non-local deployment |
| `TAVILY_API_KEY` | Web grounding via Tavily Search API | Required for research path |
| `OLLAMA_HOST` | Ollama inference endpoint | Defaults to `http://localhost:11434` |

The default `LATTICED_SECRET` value (`local_dev_secret_123`) is intentionally
public and **must be changed** before exposing the service to any network
beyond localhost. The application logs a warning when the default secret is
still active.

---

## Threat Model

LatticeD is designed as a **single-user, locally-deployed** system. The
default threat model assumes:

- The user trusts the machine the framework is running on
- The HTTP endpoint is bound to `127.0.0.1` (localhost only)
- No untrusted parties have shell access to the host

Production deployments that expose the API beyond localhost must:
1. Set a strong `LATTICED_SECRET` value
2. Place the service behind a reverse proxy with TLS
3. Restrict access via firewall rules or VPN
4. Review the shell execution capabilities in the agency loop and disable
   if not needed for the use case

---

## Known Limitations

See Section 5D of the LatticeD Case Study for a full list of known
architectural limitations relevant to security and reliability.
