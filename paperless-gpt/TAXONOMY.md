# Paperless Taxonomy

The prompts in `./prompts/` reference Paperless's **tags**, **document types**, and **custom fields**. These must exist in your Paperless instance before the LLM can use them.

**Quickest path — run the provisioning script:**

```bash
python3 paperless-gpt/provision.py
```

The script is idempotent: it reads `PAPERLESS_API_TOKEN` from `./.env`, GETs each collection, and POSTs only what's missing. Safe to re-run after a destructive reset, or after editing the lists in `provision.py`.

**Manual alternative** — create entries via the Paperless web UI:

- Tags:           `http://localhost:8000` → Settings → Tags
- Document Types: `http://localhost:8000` → Settings → Document Types
- Custom Fields:  `http://localhost:8000` → Settings → Custom Fields

The prompts pass these to the LLM via `{{.AvailableTags}}` / `{{.AvailableDocumentTypes}}` / `{{.CustomFieldsXML}}`. Remove or rename items freely — the LLM only picks from what's actually available.

**One coupling to know about:** `custom_field_prompt.tmpl` has **named heuristics** for the boolean fields `Tax Deductible`, `Residency-Related`, `Recurring`, and `Action Required`. If you rename them in Paperless, also update the prompt so the heuristics still apply.

---

## Tags (max 6 per document)

The prompt selects up to 6 tags per document. Flat, mid-grain, single-level — intentionally avoids duplicating the document type ("what shape is this"). Tags carry the topic + qualifier axes.

### Financial nature (pick 0–1)
- `invoice` — bill creating an obligation to pay
- `receipt` — proof of payment after the fact
- `statement` — periodic account/balance summary
- `quote` — estimate before commitment

### Domain (pick 1–3)
- `rent` — rental agreement, monthly rent, deposit
- `utilities` — electricity, gas, water, waste
- `internet-telecom` — internet, phone, mobile carrier
- `banking` — bank statements, account changes, transfers
- `insurance` — policy documents, claims, premium notices
- `subscription` — recurring services (streaming, software, gym)
- `tax` — anything tax-related
- `residency` — Anmeldung, Meldebescheinigung, registration
- `visa-immigration` — visa, Aufenthaltstitel, Ausländerbehörde
- `government` — official correspondence (non-tax, non-immigration)
- `legal` — lawyer correspondence, court, NDAs, agreements
- `employment` — work letters, contracts, professional correspondence
- `payslip` — Gehaltsabrechnung, salary statements
- `freelance-business` — own business activity, invoices issued
- `flight` — air travel
- `hotel-lodging` — hotels, Airbnb, accommodation
- `train-rail` — Deutsche Bahn, regional rail
- `restaurant-bar` — restaurant receipts and reservations
- `event-ticket` — concerts, sports, conferences
- `vehicle` — car/bike registration, repairs, fuel
- `health-medical` — doctor visits, hospital, medical bills
- `prescription` — prescriptions, pharmacy
- `education` — courses, certificates, school/university
- `groceries` — supermarket and grocery store receipts (Kaufland, Rewe, Aldi, Edeka, Lidl, Penny, …)
- `shopping-retail` — general retail purchases (clothing, electronics, etc. — not groceries)
- `home-services` — handymen, cleaning, repair

### Qualifiers (pick 0–2)
- `tax-deductible` — likely deductible on the German Steuererklärung
- `actionable` — requires user action (payment, signature, response) by a date
- `identification` — ID documents (passport, ID card, license, residence card)
- `confidential` — NDAs, sensitive contracts
- `warranty` — covers a warranty or guarantee
- `recurring` — recurring charge or event

---

## Document Types

Exactly one document type per document. Type describes the document's **shape/form**, not its topic.

| Type             | What it covers                                              |
|------------------|-------------------------------------------------------------|
| Invoice          | Bill creating a payment obligation                          |
| Receipt          | Proof of payment after the fact                             |
| Statement        | Bank / utility / account summary                            |
| Contract         | Signed agreement creating ongoing obligations               |
| Letter           | Correspondence without a transaction                        |
| Form             | Fillable form or application                                |
| Notice           | Official notification (government, insurance, etc.)         |
| Tax Document     | Steuerbescheid, Lohnsteuerbescheinigung, tax-return forms   |
| Payslip          | Gehaltsabrechnung                                           |
| Certificate      | Meldebescheinigung, diploma, official certificate           |
| Identification   | Passport, ID card, driver's license, residence card         |
| Booking          | Reservation confirmation (flight, hotel, table, event)      |
| Ticket           | Boarding pass, event ticket                                 |
| Medical Record   | Doctor's note, prescription, diagnosis, lab result          |
| Warranty         | Warranty / guarantee document                               |
| Quote            | Estimate or proposal before commitment                      |
| Report           | Structured report (audit, expense report, etc.)             |

---

## Custom Fields

Up to **10 fields populated per document**. Boolean heuristics produce `true` only when clearly justified; otherwise the field is omitted.

### Money
| Name              | Paperless type | Notes                                                   |
|-------------------|----------------|---------------------------------------------------------|
| Total Amount      | Monetary       | Document total, currency-prefixed (e.g. `EUR1664.58`)   |
| Tax / VAT Amount  | Monetary       | VAT / MwSt portion when shown separately                |
| Amount Due        | Monetary       | Outstanding balance when partial                        |

### Dates
| Name                       | Paperless type | Notes                                |
|----------------------------|----------------|--------------------------------------|
| Due Date                   | Date           | When payment or action is due        |
| Service Period Start       | Date           | Start of billed period               |
| Service Period End         | Date           | End of billed period                 |
| Event / Reservation Date   | Date           | When the planned event occurs        |

### References
| Name             | Paperless type | Notes                                                       |
|------------------|----------------|-------------------------------------------------------------|
| Document Number  | Text           | Invoice / receipt / booking ID                              |
| Customer Number  | Text           | Your customer/account number with the correspondent         |
| Reference        | Text           | Transaction ID, case number, other reference                |

### Flags (booleans — see heuristics in `custom_field_prompt.tmpl`)
| Name              | Paperless type | Heuristic                                                          |
|-------------------|----------------|--------------------------------------------------------------------|
| Tax Deductible    | Boolean        | Plausibly deductible on a German Steuererklärung                   |
| Residency-Related | Boolean        | Connected to Anmeldung, visa, Aufenthaltstitel, Ausländerbehörde   |
| Recurring         | Boolean        | Recurring charge or schedule explicit in the document              |
| Action Required   | Boolean        | Clear deadline, payment due, or required response                  |

### Misc
| Name           | Paperless type | Notes                                       |
|----------------|----------------|---------------------------------------------|
| Brief Summary  | Text           | 1–2 sentence model-generated TL;DR          |

---

## After changing prompts or this taxonomy

Reload paperless-gpt to pick up prompt changes:

```bash
docker compose restart paperless-gpt
```

Paperless reads tags/types/fields live, so changes in the Paperless UI take effect on the next document processing pass.
