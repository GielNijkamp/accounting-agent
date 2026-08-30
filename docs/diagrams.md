# Process diagrams

Flowcharts of each process in boekpilot. All agents are **read-only by default** — the `--book`
branches only run when you pass that flag.

## Architecture / data flow

```mermaid
flowchart LR
    A1["Agent 1<br>bank"]
    A2["Agent 2<br>tax"]
    A3["Agent 3<br>assets"]
    A4["Agent 4<br>wealth"]
    MB["moneybird.py<br>mb / mb_list / llm_model"]
    CFG["config.py<br>tax.toml"]
    REP["report.py"]
    CLI["moneybird-cli"]
    MBIRD[("Moneybird<br>administration")]
    LLM["LLM API"]
    HUMAN["You<br>review + book"]

    A1 --> MB
    A2 --> MB
    A3 --> MB
    A4 --> MB
    A2 --> CFG
    A4 --> CFG
    MB --> CLI --> MBIRD
    A1 -. fuzzy calls .-> LLM
    A2 -. fuzzy calls .-> LLM
    A3 -. fuzzy calls .-> LLM
    A4 -. fuzzy calls .-> LLM
    A1 --> REP
    A2 --> REP
    A3 --> REP
    A4 --> REP
    REP --> HUMAN
    HUMAN -->|approved bookings| MBIRD
```

## Agent 1 — bank classification

```mermaid
flowchart TD
    S(["agent1_bank.py --period"]) --> CTX["Load company context"]
    CTX --> UM["Fetch unprocessed mutations"]
    UM --> Q0{"any?"}
    Q0 -->|no| RPT
    Q0 -->|yes| MI["Deterministic:<br>exact-total invoice match"]
    MI --> BK1{"--book?"}
    BK1 -->|yes| L1["Link payment to invoice"]
    BK1 -->|no| P1["Propose link"]
    L1 --> REM
    P1 --> REM
    REM{"mutations left<br>to classify?"}
    REM -->|no| RPT
    REM -->|yes| CL["LLM classify in batches"]
    CL --> RC["reconcile_proposals<br>drop hallucinated, fill gaps"]
    RC --> SP{"confidence >= 0.8?"}
    SP -->|yes| BK2{"--book?"}
    SP -->|no| QL["Review list + reasoning"]
    BK2 -->|yes| BOOK["Book to ledger account<br>(continue past failures)"]
    BK2 -->|no| PROP["Propose booking"]
    BOOK --> RPT
    PROP --> RPT
    QL --> RPT
    RPT["Record summary -> report"] --> E(["done"])
```

## Agent 2 — tax (accruals, hours criterion, deductions)

```mermaid
flowchart TD
    S(["agent2_tax.py --fiscal-year Y"]) --> V["Validate year:<br>TAX table + tax.toml"]
    V --> IL["Fetch purchase invoice lines"]
    IL --> HASP{"line has a<br>period field?"}
    HASP -->|yes| DET["Deterministic:<br>fraction after fiscal year"]
    HASP -->|no| LLM["LLM: is it prepaid?<br>derive the period"]
    DET --> FR
    LLM --> FR
    FR{"fraction > 0?"}
    FR -->|no| SKIP["skip line"]
    FR -->|yes| PROP["Accrual proposal"]
    PROP --> C{"confidence >= 0.8?"}
    C -->|yes| BK{"--book &<br>prepaid account?"}
    C -->|no| QREV["Review manually"]
    BK -->|yes| POST["book_accruals<br>(idempotent + rollback)"]
    BK -->|no| SUG["Propose to book"]
    POST --> HR
    SUG --> HR
    QREV --> HR
    SKIP --> HR
    HR["Hours criterion<br>1225h + majority"] --> DED["Deductions:<br>self-employed / starter / SME"]
    DED --> RPT["Record summary -> report"] --> E(["done"])
```

## Agent 3 — assets (capitalization, KIA, disposals)

```mermaid
flowchart TD
    S(["agent3_asset.py --fiscal-year Y"]) --> V["Validate year:<br>KIA table"]
    V --> AS["Fetch assets +<br>already-capitalized lines"]
    AS --> CAND["Candidates:<br>invoice lines >= 450,<br>not yet capitalized"]
    CAND --> LLM["LLM: is it a fixed asset?<br>propose lifespan / residual"]
    LLM --> C{"confidence >= 0.8?"}
    C -->|yes| BK{"--book?"}
    C -->|no| QREV["Review manually"]
    BK -->|yes| CAP["capitalize:<br>create asset -> link line<br>(rollback delete if link fails)"]
    BK -->|no| SUG["Propose capitalization"]
    CAP --> KIA
    SUG --> KIA
    QREV --> KIA
    KIA["KIA over the year's investments"] --> DIS["Flag disposals<br>within 5 years"]
    DIS --> RPT["Record summary -> report"] --> E(["done"])
```

## Agent 4 — wealth (annual margin, annuity)

```mermaid
flowchart TD
    S(["agent4_wealth.py --year Y"]) --> V["Validate year:<br>ANNUAL_MARGIN + tax.toml"]
    V --> INP["income, factor A<br>from tax.toml"]
    INP --> MISS{"income missing?"}
    MISS -->|yes| EX["LLM: read assessment / UPO<br>PDFs from Moneybird inbox"]
    MISS -->|no| CALC
    EX --> CALC
    CALC["Compute annual margin<br>(jaarruimte formula)"] --> DEP["Recognize annuity deposits<br>in bank mutations"]
    DEP --> RPT["Record summary -> report"] --> E(["done"])
```

## Shared — paginated reads (`mb_list`)

```mermaid
flowchart TD
    S(["mb_list(resource)"]) --> P["page = 1"]
    P --> F["Fetch page (per_page=100)"]
    F --> EMPTY{"empty?"}
    EMPTY -->|yes| DONE
    EMPTY -->|no| NEW{"page adds<br>new rows?"}
    NEW -->|"no (endpoint ignores page)"| DONE
    NEW -->|yes| ADD["Keep new rows"] --> INC["page += 1"] --> F
    DONE["Return de-duplicated rows"] --> E(["done"])
```

## Shared — accrual booking safety (`book_accruals`)

```mermaid
flowchart TD
    S(["book_accruals"]) --> L["List existing journals<br>by reference"]
    L --> B{"both entries<br>exist?"}
    B -->|yes| SKIP(["skip — already posted"])
    B -->|no| ONE{"one exists?"}
    ONE -->|yes| HEAL(["post the missing entry<br>(self-heal)"])
    ONE -->|no| M["Post 31-Dec entry"]
    M --> R["Post 1-Jan reversal"]
    R --> OK{"reversal ok?"}
    OK -->|yes| DONE(["posted"])
    OK -->|no| RB["Delete 31-Dec entry<br>(compensating rollback)"]
    RB --> RBOK{"delete ok?"}
    RBOK -->|yes| DONE2(["rolled back"])
    RBOK -->|no| ORPH(["report orphan<br>reference / id"])
```

## Scheduled weekly run + report (`run_weekly.sh` + `report.py`)

```mermaid
flowchart TD
    CRON(["launchd / cron · weekly"]) --> KEY["Load .env<br>ANTHROPIC_API_KEY · LLM_MODEL"]
    KEY --> R1["Agent 1 (read-only)"]
    R1 --> R2["Agent 2 (read-only)"]
    R2 --> R3["Agent 3 (read-only)"]
    R3 --> R4["Agent 4 (read-only)"]
    R1 --> J
    R2 --> J
    R3 --> J
    R4 --> J
    J["Per-agent summary JSON<br>logs/summary-DATE-*.json"] --> BUILD["report.py build:<br>merge into report-DATE.md"]
    BUILD --> SEC["Sections:<br>What ran · For you to do · Risks"]
    SEC --> NOTE["macOS notification<br>headline + report path"]
    NOTE --> E(["you review, book what you approve"])
```

## Write-safety model (`--book`)

How any proposal reaches (or doesn't reach) your books.

```mermaid
flowchart TD
    P["Proposal from an agent"] --> RO{"--book passed?"}
    RO -->|no| REP["Report as a proposal<br>(nothing written)"]
    RO -->|yes| CONF{"confidence >= 0.8?"}
    CONF -->|no| Q["Question list (you decide)"]
    CONF -->|yes| PRE{"prerequisites met?"}
    PRE -->|no| WARN["Warn + skip<br>(create the account in Moneybird)"]
    PRE -->|yes| WRITE["Write via moneybird-cli<br>(continue past per-row failures)"]
    WRITE --> MULTI{"multi-step write?"}
    MULTI -->|no| DONE["Booked (reversible in Moneybird)"]
    MULTI -->|yes| STEP2{"all steps ok?"}
    STEP2 -->|yes| DONE
    STEP2 -->|no| RB["Compensating rollback"]
    RB --> RBOK{"rollback ok?"}
    RBOK -->|yes| CLEAN["Consistent again — re-run to retry"]
    RBOK -->|no| ORPH["Report orphan id — fix manually"]
```

## API call ordering (sequence diagrams)

### Agent 1 — read, classify, and (optionally) book

```mermaid
sequenceDiagram
    actor U as You
    participant A as Agent 1
    participant CLI as moneybird-cli
    participant MB as Moneybird
    participant LLM as LLM API
    U->>A: run --period (read-only)
    A->>CLI: financial_mutations list (mb_list)
    CLI->>MB: GET financial_mutations
    MB-->>A: mutations
    A->>CLI: sales / purchase invoices list
    CLI->>MB: GET invoices
    MB-->>A: open invoices
    Note over A: deterministic exact-total match
    A->>LLM: classify remaining (batched)
    LLM-->>A: proposals (account, confidence, reason)
    Note over A: reconcile + split certain / questions
    opt --book
        A->>CLI: link_booking (per certain proposal)
        CLI->>MB: PATCH financial_mutations
        MB-->>A: booked
    end
    A-->>U: report (booked / to-do / risks)
```

### Accrual booking with rollback (`book_accruals`)

```mermaid
sequenceDiagram
    participant A as Agent 2
    participant CLI as moneybird-cli
    participant MB as Moneybird
    A->>CLI: general_journal_documents list
    CLI->>MB: GET journals
    MB-->>A: existing references
    alt both accrual journals exist
        Note over A: skip — already posted
    else neither exists
        A->>CLI: create accruals-Y (31 Dec)
        CLI->>MB: POST journal A
        MB-->>A: id A
        A->>CLI: create accruals-Y-reversal (1 Jan)
        CLI->>MB: POST journal B
        alt reversal succeeds
            MB-->>A: id B (posted)
        else reversal fails
            A->>CLI: delete journal A
            CLI->>MB: DELETE journal A (rollback)
            MB-->>A: rolled back
        end
    end
```
