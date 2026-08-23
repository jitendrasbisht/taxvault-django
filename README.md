# TaxVault

A document collection & tracking platform for Chartered Accountant firms. TaxVault doesn't file ITRs — its job ends the moment a client's paperwork is complete.

Point it at a folder of mixed client documents (or have staff upload them straight from the browser), and it reads, matches, classifies, and files each one automatically — flagging anything it can't confidently place for a quick manual check. At any moment, a firm knows exactly who's **Ready for ITR** and who's still missing what.

> The full product spec — every locked decision and every approved deviation from it — lives in [`CLAUDE.md`](CLAUDE.md). This README is a practical "what is this and how do I run it" guide; that file is the source of truth for scope.

---

## What it does

- **Client onboarding** — bulk import (CSV/Excel) or manual add, tagged with categories (Salaried, Stock/Equity Investor, Rental Income, etc.) that determine which documents each client needs
- **Document intake** — point at a local folder, or upload files straight from any browser (no server filesystem access needed). Accepts PDF, JPG, PNG, Excel, and CSV
- **Identity matching** — PAN → Aadhar → Bank Account Number → Phone, in that priority order, with no name/fuzzy matching (false positives get routed to a Review Queue, never guessed)
- **Keyword-based classification** — a configurable DocCode table maps documents to types (Form 16, AIS, 26AS, Capital Gains Statement, etc.) per firm
- **Review Queue** — anything unmatched or unclassified lands here for a human to resolve or discard
- **Reminders** — two-stage, manually-triggered email requests listing each client's outstanding documents
- **Dashboard** — firm-wide KPIs, a completion heatmap, a filing-deadline countdown, and a reminder funnel
- **Multi-tenant from the start** — every table is scoped by firm; one firm can never see another's data

## Tech stack

- **Backend**: Django 6
- **Database**: PostgreSQL
- **Background jobs**: Django-Q + Redis (batch document processing runs async)
- **File storage**: local filesystem today (`vault_storage/`), designed to swap to Cloudflare R2 without touching the pipeline
- **Frontend**: server-rendered Django templates + Tailwind (via CDN) — no separate JS framework

## Running it locally

**Requirements**: Python 3.11+, Docker Desktop (for Postgres + Redis)

```bash
git clone https://github.com/jitendrasbisht/taxvault-django.git
cd taxvault-django
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env         # fill in a real SECRET_KEY before any real deployment

docker compose up -d           # Postgres + Redis

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then in a second terminal, start the background worker (required for document intake to actually process):

```bash
python manage.py qcluster
```

### One-click startup (Windows)

If Docker, the server, and the worker are all stopped, double-click **`start_demo.bat`** — it brings up Postgres/Redis, the Django server, and the background worker, skipping anything already running. If you also want a public URL to share (e.g. for a remote demo), it starts a [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) too and copies the URL to your clipboard.

> **Note**: the background worker doesn't hot-reload. If you edit `documents/pipeline.py`, `documents/models.py`, or `documents/extraction.py`, restart `qcluster` (or re-run `start_demo.bat`) for the change to take effect.

## Project layout

```
clients/     Client Master, categories, DocCode config, firm/staff management
documents/   Intake pipeline, identity matching, classification, Review Queue
portal/      The staff-facing UI — dashboard, clients, intake, reminders, settings
taxvault/    Project settings, Assessment Year logic, vault naming conventions
```

## Sample data

`sample_data/sample_clients.xlsx` is a ready-to-use bulk-import file for trying out onboarding.

---

*Everything in this README describes what's actually built and working — for what's deliberately out of scope for now (audit logs, client self-service login, ML-based classification, and more), see Section 16 of [`CLAUDE.md`](CLAUDE.md).*
