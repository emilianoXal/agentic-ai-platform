# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.
- Follow `CONTRIBUTING.md` for repository conventions and local validation.
- See `ARCHITECTURE.md` for the event flow and outbound channel boundaries.

How to test each kind of hackathon change, including the WhatsApp SNS smoke (`scripts/smoke_whatsapp.py`) and simulated outbound `WOULD_SEND_REPLY`, is in `docs/oficios/tester.md`.
The live Sonnet conversation matrix runs through the manual GitLab `agent:conversations` job implemented by `scripts/conversation_matrix.py`.
Catalog categories and the short category matrix are covered in `docs/oficios/tester.md`.
Run the Python module suites in separate processes because legacy tests share the `handler` import name; follow-up tests and the post-apply citizen-response corpus are documented in `docs/oficios/tester.md`.
Citizen WhatsApp notices (notifier and «Is it fixed?») are English, use the portal folio `UB-YYYY-XXXXXX`, and are covered by `modules/*/tests/test_*avisos*.py`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
Put a long or one-situation lesson in the project's docs/ and leave a one-line pointer here.
If this file grows past ~16 KB (~4k tokens), cut or move material before adding, and report that trim in your status line.
When updating this file, preserve this bar for all agents and keep entries concise.
