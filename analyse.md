# Functionele Analyse: Betoled Automatisation

**App naam:** `betoled_automatisation`  
**Versie:** 1.0  
**Laatst bijgewerkt:** 31 december 2024  
**Doel:** Automatisering van bedrijfsprocessen voor BETOWARE en LASTAMAR in ERPNext

---

## 1. Overzicht

De `betoled_automatisation` app is een custom ERPNext applicatie die verschillende automatiseringsprocessen implementeert voor de bedrijfsvoering van BETOWARE en LASTAMAR. De app is ontworpen om te werken met meerdere companies binnen één ERPNext installatie.

### 1.1 Ondersteunde Companies
- BETOWARE
- LASTAMAR

### 1.2 Kernfunctionaliteiten
1. **Ponto Bank Integratie** - Automatisch ophalen van banktransacties
2. **Betalingsreconciliatie** - Automatisch matchen van betalingen met facturen
3. **2-Fase Matching Systeem** - Intelligente matching via gestructureerde mededeling en fuzzy logic

---

## 2. Ponto Bank Integratie

### 2.1 Beschrijving
Integratie met de Ponto API (MyPonto) voor het automatisch ophalen van banktransacties. Elke company heeft een eigen Ponto account met aparte credentials.

### 2.2 Technische Details

**API Endpoint:** `https://api.myponto.com`  
**Authenticatie:** OAuth2 met Basic Auth (client credentials grant)

### 2.3 Configuratie (Ponto Settings DocType)

| Veld | Type | Beschrijving |
|------|------|--------------|
| `company` | Link | Gekoppelde ERPNext Company |
| `enabled` | Check | Integratie actief/inactief |
| `client_id` | Data | Ponto API Client ID |
| `client_secret` | Password | Ponto API Client Secret |
| `ponto_account_id` | Data | UUID van het bankaccount in Ponto |
| `iban` | Data | IBAN van de bankrekening |
| `days_to_fetch` | Int | Aantal dagen terug om transacties op te halen (default: 7) |
| `last_sync` | Datetime | Tijdstip van laatste synchronisatie |

### 2.4 Automatische Scheduling

De transactie-ophaling draait automatisch:
- **07:00** - Ochtend synchronisatie
- **14:00** - Middag synchronisatie

Configuratie via `hooks.py`:
```python
scheduler_events = {
    "cron": {
        "0 7 * * *": ["betoled_automatisation.tasks.fetch_and_reconcile_all"],
        "0 14 * * *": ["betoled_automatisation.tasks.fetch_and_reconcile_all"]
    }
}
```

### 2.5 Opgehaalde Transactiegegevens

Per transactie worden de volgende gegevens opgeslagen:
- Transaction ID (Ponto UUID)
- Datum (execution date, value date)
- Bedrag en valuta
- Credit/Debit indicator
- Tegenpartij naam en IBAN
- Mededeling (remittance information)
- Gestructureerde mededeling (indien aanwezig)

---

## 3. Betalingsreconciliatie

### 3.1 Beschrijving
Automatisch matchen van inkomende bankbetalingen met openstaande Sales Invoices in ERPNext. Het systeem gebruikt een 2-fase matching approach voor maximale nauwkeurigheid.

### 3.2 Matching Fases

#### Fase 1: Gestructureerde Mededeling Matching
**Primaire matching methode**

1. Extract de gestructureerde mededeling uit de banktransactie
2. Zoek Sales Invoice met exact dezelfde `gestructureerde_mededeling`
3. Vergelijk bedragen

**Gestructureerde Mededeling Format (België):**
```
+++XXX/XXXX/XXXXX+++
of
***XXX/XXXX/XXXXX***
of
12 opeenvolgende cijfers met modulo 97 check
```

**Match Types Fase 1:**
| Type | Beschrijving | Confidence |
|------|--------------|------------|
| Exact Match | Bedrag komt exact overeen | 100% |
| Partial Payment | Betaling < openstaand bedrag | 85% |
| Overpayment | Betaling > openstaand bedrag | 70% |

#### Fase 2: Fuzzy Matching (Amount + Name)
**Secundaire matching wanneer Fase 1 faalt**

Wordt alleen uitgevoerd als:
- Geen gestructureerde mededeling gevonden
- `enable_fuzzy_matching` is ingeschakeld

**Stappen:**
1. Zoek facturen met bedrag binnen tolerantie (±X%)
2. Vergelijk tegenpartij naam met:
   - `customer_name` van de klant
   - `custom_alias` veld (comma-gescheiden alternatieven)
3. Bereken fuzzy similarity score
4. Match als score >= threshold

### 3.3 Fuzzy Matching Configuratie

| Instelling | Default | Beschrijving |
|------------|---------|--------------|
| `amount_tolerance_percent` | 5% | Maximale afwijking van factuurbedrag |
| `fuzzy_match_threshold` | 80% | Minimum similarity score (0-100) |
| `enable_fuzzy_matching` | Aan | Fase 2 matching aan/uit |

### 3.4 Fuzzy Matching Algoritme

Het similarity algoritme gebruikt meerdere technieken:
1. **Exacte match** → 100%
2. **Substring match** → Proportioneel aan lengteverhouding
3. **Word overlap** → Jaccard similarity van woorden
4. **Levenshtein ratio** → Character-gebaseerde similarity

### 3.5 Custom Alias Veld

**DocType:** Customer  
**Veld:** `custom_alias`  
**Type:** Small Text  
**Beschrijving:** Comma-gescheiden lijst van alternatieve namen

Voorbeeld:
```
ACME Corporation, ACME Corp, A.C.M.E. BV, Acme NV
```

### 3.6 Auto-Reconciliatie

Bij exacte matches (Fase 1, bedrag klopt exact):
- Automatisch Payment Entry aanmaken
- Sales Invoice markeren als (gedeeltelijk) betaald
- Transactie status → "Reconciled"

**Voorwaarde:** `auto_reconcile_exact_matches` moet aanstaan in Ponto Settings

### 3.7 Handmatige Review

Matches die niet automatisch worden verwerkt:
- Fuzzy matches (Fase 2)
- Partial payments
- Overpayments
- Multiple matches

Deze worden opgeslagen als **Payment Match** records voor handmatige goedkeuring.

---

## 4. DocTypes

### 4.1 Ponto Settings
**Doel:** Configuratie per company voor Ponto integratie

| Veld | Type | Verplicht | Beschrijving |
|------|------|-----------|--------------|
| company | Link → Company | Ja | Uniek per company |
| enabled | Check | Nee | Integratie actief |
| client_id | Data | Nee* | Ponto API credentials |
| client_secret | Password | Nee* | Ponto API credentials |
| ponto_account_id | Data | Nee | Auto-detect mogelijk |
| iban | Data | Nee | Van Company's Default Bank Account |
| days_to_fetch | Int | Nee | Default: 7 |
| auto_reconcile_exact_matches | Check | Nee | Default: Aan |
| amount_tolerance_percent | Float | Nee | Default: 5% |
| fuzzy_match_threshold | Int | Nee | Default: 80 |
| enable_fuzzy_matching | Check | Nee | Default: Aan |

*Verplicht wanneer `enabled` = 1

### 4.2 Ponto Transaction
**Doel:** Log van alle geïmporteerde banktransacties

| Veld | Type | Beschrijving |
|------|------|--------------|
| company | Link → Company | Bron company |
| ponto_transaction_id | Data | Unieke Ponto UUID |
| status | Select | Pending/Matched/Reconciled/Ignored/Error |
| transaction_date | Date | Uitvoeringsdatum |
| value_date | Date | Valutadatum |
| amount | Currency | Transactiebedrag |
| currency | Link → Currency | Valuta (default: EUR) |
| credit_debit | Select | Credit/Debit |
| counterpart_name | Data | Naam tegenpartij |
| counterpart_iban | Data | IBAN tegenpartij |
| remittance_information | Small Text | Volledige mededeling |
| structured_reference | Data | Geëxtraheerde gestructureerde mededeling |
| matched_invoice | Link → Sales Invoice | Gekoppelde factuur |
| payment_entry | Link → Payment Entry | Aangemaakte betaling |
| match_status | Select | Match resultaat |
| match_notes | Small Text | Details van matching |
| raw_data | Code (JSON) | Originele API response |

### 4.3 Payment Match
**Doel:** Voorgestelde matches voor handmatige review

| Veld | Type | Beschrijving |
|------|------|--------------|
| ponto_transaction | Link → Ponto Transaction | Bron transactie |
| company | Link → Company | Company |
| status | Select | Pending Review/Approved/Rejected/Auto-Reconciled |
| sales_invoice | Link → Sales Invoice | Voorgestelde factuur |
| invoice_amount | Currency | Factuurbedrag |
| outstanding_amount | Currency | Openstaand bedrag |
| gestructureerde_mededeling | Data | Mededeling van factuur |
| transaction_amount | Currency | Betalingsbedrag |
| transaction_date | Date | Betalingsdatum |
| counterpart_name | Data | Naam betaler |
| match_type | Select | Exact/Partial/Overpayment/Fuzzy/Manual |
| confidence_score | Percent | Zekerheid van match (0-100) |
| payment_entry | Link → Payment Entry | Resulterende betaling |
| processed_by | Link → User | Wie heeft goedgekeurd |
| processed_date | Datetime | Wanneer verwerkt |
| notes | Small Text | Opmerkingen |

---

## 5. Custom Fields

### 5.1 Customer DocType

| Veld | Type | Beschrijving |
|------|------|--------------|
| `custom_alias` | Small Text | Comma-gescheiden alternatieve namen voor fuzzy matching |

---

## 6. Pages

### 6.1 Ponto Dashboard
**URL:** `/app/ponto-dashboard`  
**Toegang:** System Manager, Accounts Manager

**Functionaliteit:**
- Overzicht van reconciliatie statistieken (laatste 30 dagen)
- Status per company (enabled/disabled, last sync)
- Quick actions:
  - Fetch All Transactions
  - Fetch per Company
  - Review Pending Matches
  - View Unmatched Transactions
- Company status tabel met IBAN en sync info

---

## 7. API Endpoints

### 7.1 Publieke API Methodes

| Methode | Beschrijving |
|---------|--------------|
| `get_reconciliation_summary(company, days)` | Statistieken overzicht |
| `get_pending_matches(company)` | Lijst van te reviewen matches |
| `get_unmatched_transactions(company, limit)` | Transacties zonder match |
| `manually_match_transaction(transaction_name, invoice_name)` | Handmatige koppeling |
| `find_potential_matches(transaction_name)` | Suggesties voor matching |
| `run_reconciliation_now()` | Start reconciliatie job |
| `run_reconciliation_for_company(company)` | Reconciliatie per company |

---

## 8. Workflows

### 8.1 Automatische Reconciliatie Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Scheduled Task (07:00, 14:00)                                │
│ fetch_and_reconcile_all()                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Voor elke enabled Ponto Settings:                            │
│ 1. OAuth2 authenticatie                                      │
│ 2. GET /accounts → vind account by IBAN                      │
│ 3. GET /accounts/{id}/transactions                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Per credit transactie:                                       │
│ 1. Check of al geïmporteerd (ponto_transaction_id)          │
│ 2. Maak Ponto Transaction record                             │
│ 3. Extract gestructureerde mededeling                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ FASE 1: Structured Reference Matching                        │
│ → Zoek Sales Invoice met gestructureerde_mededeling          │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          │                                       │
          ▼                                       ▼
   ┌─────────────┐                         ┌─────────────┐
   │ MATCH       │                         │ NO MATCH    │
   │ GEVONDEN    │                         │             │
   └─────────────┘                         └─────────────┘
          │                                       │
          ▼                                       ▼
   ┌─────────────┐                   ┌─────────────────────┐
   │ Exact +     │                   │ FASE 2: Fuzzy       │
   │ Auto-rec ON │                   │ (indien enabled)    │
   │ ?           │                   │ Amount + Name match │
   └─────────────┘                   └─────────────────────┘
          │                                       │
    ┌─────┴─────┐                    ┌────────────┴────────────┐
    ▼           ▼                    ▼                         ▼
┌────────┐ ┌─────────┐        ┌─────────────┐          ┌─────────────┐
│ AUTO   │ │ REVIEW  │        │ FUZZY MATCH │          │ NO MATCH    │
│ Payment│ │ Payment │        │ → Review    │          │ → Pending   │
│ Entry  │ │ Match   │        │ Payment     │          │ status      │
└────────┘ └─────────┘        │ Match       │          └─────────────┘
                              └─────────────┘
```

### 8.2 Handmatige Review Flow

```
┌─────────────────────────────────────────────────────────────┐
│ User opent Payment Match met status "Pending Review"         │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       ┌─────────────┐                 ┌─────────────┐
       │ APPROVE     │                 │ REJECT      │
       └─────────────┘                 └─────────────┘
              │                               │
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│ 1. Create Payment Entry │     │ 1. Status → Rejected    │
│ 2. Link to Invoice      │     │ 2. Ponto Txn → Pending  │
│ 3. Status → Approved    │     │ 3. Log reason           │
│ 4. Ponto Txn →          │     └─────────────────────────┘
│    Reconciled           │
└─────────────────────────┘
```

---

## 9. Beveiliging

### 9.1 Permissies

| Role | Ponto Settings | Ponto Transaction | Payment Match |
|------|----------------|-------------------|---------------|
| System Manager | CRUD | CRUD | CRUD |
| Accounts Manager | CRUD | CRU | CRU |
| Accounts User | - | R | R |

### 9.2 Gevoelige Data

- **Ponto Client Secret:** Opgeslagen als Password field (versleuteld)
- **Access Token:** Opgeslagen als Password field, automatisch ververst
- **API communicatie:** HTTPS met OAuth2 Bearer tokens

---

## 10. Logging & Audit

### 10.1 Error Logging
- Alle API fouten worden gelogd in Error Log
- Transaction processing fouten per transactie
- Connection failures met stack traces

### 10.2 Audit Trail
- Payment Match heeft `processed_by` en `processed_date`
- Ponto Transaction heeft `match_notes` met matching details
- Track Changes enabled op alle DocTypes

### 10.3 Log Retention
```python
default_log_clearing_doctypes = {
    "Ponto Transaction": 90  # 90 dagen bewaren
}
```

---

## 11. Toekomstige Uitbreidingen

### 11.1 Gepland
- [ ] Email notificaties voor pending matches
- [ ] Batch approval van matches
- [ ] Rapportage module
- [ ] Support voor Purchase Invoices (uitgaande betalingen)

### 11.2 Mogelijk
- [ ] Machine learning voor betere matching
- [ ] Multi-currency support
- [ ] Bank statement import (CODA, MT940)
- [ ] Integratie met andere bank APIs

---

## 12. Installatie & Deployment

### 12.1 Installatie
```bash
bench get-app https://github.com/[repo]/betoled_automatisation
bench --site [site] install-app betoled_automatisation
bench --site [site] migrate
```

### 12.2 Configuratie Stappen
1. Ga naar **Ponto Settings**
2. Maak record per company
3. Vul Ponto credentials in
4. Configureer matching instellingen
5. Test connection
6. Enable de integratie

### 12.3 Dependencies
- ERPNext (verplicht)
- betoled_peppol (voor `gestructureerde_mededeling` veld)

---

## 13. Changelog

### v1.0 (31-12-2024)
- Initiële release
- Ponto API integratie
- 2-fase matching systeem
- Ponto Dashboard
- Payment Match workflow
- Custom alias field voor fuzzy matching

