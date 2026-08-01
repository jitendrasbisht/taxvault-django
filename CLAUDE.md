# TaxVault — MVP1 Requirements (LOCKED SPEC)

## ⚠️ INSTRUCTIONS TO THE MODEL — READ FIRST, FOLLOW STRICTLY

You are building **exactly** what is specified below. This document represents finalized, locked decisions made after extensive discussion. Your job is implementation, not design.

**Rules you must follow without exception:**

1. **Do not add features, screens, tables, fields, or logic that are not explicitly listed below.** If something seems "missing" or you think an additional feature "would help," do NOT add it. Instead, flag it to me as a question and wait for my explicit approval before building it.
2. **Do not restructure, rename, or "improve" the naming conventions, DocCode table, folder structure, or logic flow described below.** Implement them exactly as written, even if you believe a different approach is technically better. If you have a genuine technical concern (not a preference), raise it as a question — do not silently change it.
3. **Do not introduce new tools, libraries, architecture patterns, or dependencies beyond what's specified**, unless something specified is genuinely technically impossible — in which case, stop and ask me before substituting anything.
4. **Do not build ahead of scope.** If a feature is marked "NOT in MVP1 / deferred," do not build any part of it, including "just in case" scaffolding, placeholder screens, or unused fields for it.
5. **If any requirement below is ambiguous or underspecified, ask me a direct question. Do not fill the gap with your own assumption.**
6. **At the start of any work session, re-read this document in full before writing code**, to avoid drift from earlier context.
7. **When you complete a piece of work, summarize exactly what you built against exactly what was asked — do not describe extra things you added as if they were part of the ask.**

If you (the model) ever catch yourself about to add something not listed here — stop, and ask instead.

---

## 1. Product Summary

TaxVault MVP1 is a document collection & tracking platform for Chartered Accountants (CAs). It does **not** file ITRs. Its job ends when a client's required documents are complete ("Ready for ITR").

Primary users: CA (Firm Admin), Office Staff.

---

## 2. Client Onboarding

- **Bulk import** (Excel/CSV) — primary onboarding method for existing client base (e.g. 500 clients).
  - Required fields per client: PAN, Client Name, Phone, Aadhar (optional), Category tags (see Section 5).
- **Manual individual add** — for new clients going forward, same fields.
- Both paths write to the same Client Master table — no separate logic paths downstream.
- **No automatic client creation from incoming documents, ever.** If a document doesn't match an existing client, it goes to the Review Queue (Section 6). A human must explicitly create the client record.

---

## 3. Document Identity Matching

Priority order for matching an incoming document to a client:

1. **PAN number** (regex: 5 letters, 4 digits, 1 letter — `[A-Z]{5}[0-9]{4}[A-Z]{1}`)
2. **Aadhar number** (12 digits) — store masked/hashed, not full plaintext, due to regulatory sensitivity.
3. **Phone number** — weakest signal, used only as fallback.
4. **Name matching is NOT used** — explicitly excluded due to false-positive risk.

If no identifier is found, or no match exists in Client Master → route to Review Queue. Do not guess or fuzzy-match.

---

## 4. Document Intake (MVP1 = Folder-Based Only)

- Input: a **watched local folder** (e.g., Downloads) containing up to 600–700 mixed files per batch.
- **Text-based PDFs**: extract text directly (no OCR needed) — cheaper, faster.
- **Scanned/image files (JPG, PNG, scanned PDF)**: send to OCR (Google Cloud Vision API) for text extraction.
- Skip/flag non-document file types (.exe, .zip, etc.) — do not attempt to process them.
- **Email inbound intake and WhatsApp intake are NOT in this build. Do not build any email server, inbox parser, or messaging API integration.** (Deferred to a later phase — out of scope here.)
- **Client-facing upload portal is NOT in this build.** Clients do not log in or interact with any UI. (Deferred — out of scope here.)

---

## 5. Document Requirement Profile (Base + Category)

**Base documents (required for every client, no tagging needed):**
- `AIS`
- `26AS`

**Category-based add-ons** — each client is tagged with one or more categories at onboarding; each category maps to additional required DocCodes:

| Category | Adds Required DocCodes |
|---|---|
| Salaried | `Form16` |
| Stock/Equity Investor | `CGSTMT`, `DEMAT` |
| Mutual Fund Investor | `MFSTMT` |
| Home Loan Borrower | `HLINT` |
| Rental Income | `RENT`, `RENTAGR` |
| Donations (80G) | `80G` |
| Insurance (80C/80D) | `80C`, `80D` |
| NPS Contributor | `NPS` |
| Business/Professional Income | `BANKSTMT` |

- Category → DocCode mapping must be a **configurable table**, not hardcoded in application logic.
- A client can have multiple categories; Required Docs = Base + union of all their categories' DocCodes.
- Category tagging is entered manually (via Excel column on bulk import, or checkbox on manual add). **Do not build automatic category inference from documents or history.**

---

## 6. Document Classification (Keyword-Based Only)

Use simple keyword/pattern matching on extracted text to assign a DocCode. **Do not use ML/LLM-based classification in MVP1.**

**Locked DocCode table:**

| Document | Code |
|---|---|
| Form 16 (Salary TDS Certificate) | `Form16` |
| Form 16A (Non-salary TDS Certificate) | `Form16A` |
| AIS (Annual Information Statement) | `AIS` |
| TIS (Taxpayer Information Summary) | `TIS` |
| 26AS | `26AS` |
| Capital Gains Statement | `CGSTMT` |
| Mutual Fund Statement | `MFSTMT` |
| Bank Statement | `BANKSTMT` |
| Bank Interest Certificate | `BANKINT` |
| 80C Investment Proof | `80C` |
| 80D (Health Insurance Premium) | `80D` |
| 80G (Donation Receipt) | `80G` |
| Home Loan Interest Certificate | `HLINT` |
| Rent Receipt | `RENT` |
| Rent Agreement | `RENTAGR` |
| Salary Slip | `PAYSLIP` |
| Aadhar Card | `AADHAR` |
| PAN Card | `PANCARD` |
| Demat/Broker Statement | `DEMAT` |
| NPS Statement | `NPS` |
| Property Sale Deed | `PROPDEED` |
| Unclassified / no keyword match | `MISC` |

- DocCode table (keywords → code, and code → friendly display name) must be a **configurable table**, not hardcoded.
- `MISC` documents are filed but **do not count toward "Ready for ITR"** completeness (Section 9) until manually reclassified by staff.

---

## 7. Assessment Year (AY) Logic

- **AY is system-computed automatically**, based on India's Financial Year calendar (April 1 – March 31), rolling over every April 1st.
- Formula: if today's month ≥ April, the "current AY" is `(current_year+1)-(current_year+2 mod 100)`; else it's `(current_year)-(current_year+1 mod 100)`. Example: any date between Apr 1 2026 and Mar 31 2027 → **AY 2026-27**.
- This is a **computed value at runtime**, not a stored/manually-updated setting.
- Every processing batch (a folder-intake run) requires an **AY selector at the start of the batch**, pre-filled with the computed current AY, but **CA can override it** (for back-dated/belated filing work). All documents in that batch inherit the selected AY.
- **Do not build per-document OCR-based date inference for AY.** Batch-level selection only.

---

## 8. Naming & Filing Convention

**Folder structure (nested by Assessment Year within each client):**
```
/Vault/{PAN}_{ClientName}/{AY}/
```

**Filename structure:**
```
{PAN}_{DocCode}_{AY}_{Date}.ext
```
Where `{Date}` = file processed date, format `YYMMDD`.

**Example:**
```
/Vault/FGHIJ5678K_PriyaMehta/AY26-27/FGHIJ5678K_CGSTMT_AY26-27_260726.pdf
```

- Each client's vault contains one subfolder per Assessment Year. A new AY folder is created automatically the first time a document is filed for that year — no manual folder setup needed.
- Rename + move happens as **one atomic step** at time of filing (not before).
- Original file (from the watched folder) is **archived** (moved to a `Processed_Archive` folder), **never deleted**.
- Duplicate detection: use file content hash to skip exact duplicate re-processing; flag same-PAN + similar-filename as possible duplicate for manual review rather than silently skipping or overwriting.

---

## 9. "Ready for ITR" Status Logic

```
Required Docs = Base (AIS, 26AS) + union of all DocCodes from client's tagged categories
Received Docs = all non-MISC, classified documents filed under that client for the selected AY

Missing = Required − Received

If Missing is empty → Status: "Ready"
If some but not all required docs received → Status: "In Progress (X of Y received)"
If zero required docs received → Status: "Not Started"
```

- `MISC` documents never count toward Received until manually reclassified.
- This status must be viewable per client (a list/dashboard view is in scope; do not build any charts, analytics, or trend visualizations beyond this simple per-client status list).
- **The Client Vault view shows only the currently selected/active AY's documents by default.** Since the folder structure is nested by AY (Section 8), prior years exist on disk but are not surfaced in the default view. A simple AY switcher/dropdown on the client page (to browse a different year's folder) may be added later — **do not build this in MVP1**; default view = current AY only.

---

## 10. Review Queue

- Any document that fails to match a client (no PAN/Aadhar/Phone found, or found identifier doesn't match any client) → goes to a Review Queue, unmodified/unrenamed.
- Any document that matches a client but fails keyword classification → filed under that client as `MISC`, and also flagged/listed in the Review Queue for staff to manually assign the correct DocCode.
- Review Queue is a simple list: filename, detected identifier (if any), matched client (if any), reason flagged. Staff can manually assign/correct client match and/or DocCode from this queue. **Do not build any auto-suggestion, confidence scoring UI, or ML-based triage beyond this simple manual list+action.**
- **Resolution behavior:** once staff manually assigns a client and/or DocCode to a queued file, it is immediately renamed and moved into that client's correct `/Vault/{PAN}_{ClientName}/{AY}/` folder — the same outcome as an automatic match, just human-confirmed. It does not stay behind in the Review Queue or exist in two places. The original stays archived per Section 8, exactly as with auto-filed documents.

---

## 11. Reminders (Manual, Two-Stage, Email Only)

- **Channel: Email only.** Do not build WhatsApp, SMS, or any other channel.
- **No automated/scheduled sending.** All reminders are manually triggered by CA/staff via a button/action.
- **Stage 1 — Initial Request:** CA selects a batch of clients → system sends one individually-addressed, personalized email per client (not CC/BCC), auto-drafted listing that client's full Required Docs list (using friendly display names from Section 6, not raw DocCodes).
- **Stage 2 — Follow-up:** CA triggers anytime after Stage 1 → system recalculates Required − Received per client at that moment → email lists only what's still missing → clients already "Ready" are automatically excluded from this send.
- Maintain a simple send log: client, stage, date sent — to prevent accidental duplicate sends and give visibility into reminder history.
- **Do not build email open/click tracking, A/B testing, or any marketing-style analytics.**

---

## 12. Client Document Submission

- Clients submit documents **only via replying to the request email with attachments.**
- These attachments feed into the same folder/inbox-based intake pipeline as Section 4.
- **Do not build a client-facing upload portal, login, or any client-facing UI of any kind in MVP1.**

---

## 13. Multi-Tenancy

- Data model must be **multi-tenant from the start**: every core table (Clients, Documents, Categories, DocCode mappings, Reminder logs) scoped by a `firm_id`.
- Enforce isolation at the query/data layer, not just UI-level filtering.
- **Explicit data isolation requirement:** once this scales beyond a single firm, a client (or staff member) belonging to one firm must never be able to see, query, or infer the existence of another firm's clients or documents — no cross-firm search results, no shared ID sequences that leak record counts, no error messages that reveal another firm's data exists. Every query, not just list views, must be scoped by `firm_id` — including detail views, downloads, and the Review Queue.
- **Do not build firm self-signup, billing, or plan-tier logic.** New firms are added manually by the system admin (you/me) — this is an internal action, not a user-facing flow.
- Category→DocCode mappings and DocCode tables are configurable **per firm** (Section 5, 6).
- **Data protection awareness (not a build item):** stored data includes PAN, Aadhar, phone numbers, and financial documents for potentially thousands of individuals across firms — this falls under India's DPDP Act (2023), not just Aadhar-specific rules. No specific technical action is being locked here beyond what's already specified (Aadhar masking/hashing, firm isolation) — noted so it isn't lost track of as the client base grows, and worth a legal sanity check before onboarding other firms' real client data.

---

## 14. Roles & Permissions

Exactly two roles — do not add more:

| Role | Access |
|---|---|
| **Firm Admin** | Full access: clients, staff, DocCode/category settings, reminders, all vaults |
| **Staff** | Clients, vaults, reminders, Review Queue — **no access** to firm settings (DocCode table, category mappings, staff management) |

- **Do not build per-client staff assignment (all staff see all clients within their firm).**
- **Do not build an audit trail / activity log in MVP1.**

---

## 15. Session & Document Access

- Session timeout: **60 minutes from last activity/click.**
- **In-browser document preview** (PDF/image) — required.
- **"Download all documents for a client" as a zip** — required.
- **No integration of any kind with external ITR filing software.** TaxVault is a reference/staging layer only — the CA manually cross-references it while filing elsewhere.

---

## 16. Explicitly OUT OF SCOPE for MVP1 (do not build any of these)

- Email inbound parsing / inbox integration
- WhatsApp integration
- Client-facing upload portal or any client login
- Automated/scheduled reminders (must be manually triggered)
- ML/LLM-based document classification (keyword-based only)
- OCR-based AY inference per document
- Per-client staff assignment
- Audit trail / activity logs
- Firm self-signup or billing
- Any analytics, charts, trend dashboards beyond the simple Ready/In Progress/Not Started status list
- Confidence scoring or auto-suggestion UI in the Review Queue
- Any integration with external ITR filing tools
- Auto-creation of client records from incoming documents

---

## 17. Tech Stack (for reference — do not substitute without asking)

- Backend/App: Django (Python)
- Database: PostgreSQL
- File Storage: Cloudflare R2 (S3-compatible)
- OCR: Google Cloud Vision API (only for non-text-extractable files)
- Email: transactional provider (e.g., SES/Mailgun/Postmark) — outbound only for MVP1
- Background jobs: Celery/Django-Q + Redis (for batch folder intake)
- Hosting: cost-conscious, scale-to-zero preferred (e.g., Neon + Cloud Run) given seasonal usage pattern

---

*End of locked spec. Any change to this document must come from me explicitly, not be inferred or added during implementation.*
