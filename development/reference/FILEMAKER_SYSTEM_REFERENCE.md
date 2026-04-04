# UCPPC FileMaker System Reference

This document provides a general-purpose reference for the UCPPC (University of California Physical Planning & Construction) FileMaker application used by UCSC PPDO. It is intended for developers and AI agents interacting with this system.

## Overview

- **File**: `UCPPC.fmp12`
- **Database Design Report (DDR)**: `N:\PPDO\BS\Records Department\Sys Admin\Filemaker\database_design_reports\20260402\UCPPC_ddr\UCPPC.html`
- **Scale**: 73 base tables, 211 relationships, 468 layouts, 346 scripts, 90 value lists
- **Records snapshot** (April 2026): ~10K projects, ~5.7K contracts, ~1.2K CAANs, ~19K people, ~1.4K companies
- **API version**: v1 (FileMaker Data API)
- **SSL**: Not verified for internal connections (`verify_ssl=False`)

## Accessing Data via the FM Data API

The archives system currently uses the **python-fmrest** library to access FileMaker data. The FM Data API is a REST API exposed by FileMaker Server. Key concepts:

- **Layouts** determine what data you can access. A layout is bound to a **table occurrence** (see below), and only fields placed on that layout are returned via the API.
- Authentication is token-based (fmrest handles login/logout automatically).
- The `get_records()` method retrieves all records from a layout. Use `limit` param to control batch size.
- Results come back as a `Foundset` which can be converted to a pandas DataFrame via `.to_df()`.

### Connection Pattern (from archives_app)

```python
import fmrest

fmrest.utils.TIMEOUT = 300  # increase for large datasets

server = fmrest.Server(
    host_location,        # FILEMAKER_HOST_LOCATION config key
    user=user,            # FILEMAKER_USER
    password=password,    # FILEMAKER_PASSWORD
    database=database,    # FILEMAKER_DATABASE_NAME (value: "UCPPC")
    layout=layout_name,   # e.g. "projects_table"
    api_version="v1",
    verify_ssl=False
)
server.login()
foundset = server.get_records(limit=100000)
df = foundset.to_df()
server.logout()
```

### Existing API Layouts (used by archives_app sync)

These layouts were created specifically for data access and are confirmed present in the DDR:

| Layout Name          | Purpose                           |
|----------------------|-----------------------------------|
| `projects_table`     | Project records (Projects table)  |
| `caan_table`         | CAAN/building records             |
| `caan_project_join`  | Project-CAAN many-to-many links   |

There is **no existing `contracts_table`** layout. Contracts-related layouts that exist include `dev.Contracts`, `script.Contracts`, and the main `Contracts` layout — but a dedicated API layout may need to be created for clean data access.

## Table Occurrences (Relationship Graph Aliases)

FileMaker's relationship graph uses **table occurrences** (TOs) — aliases of base tables that participate in specific relationship contexts. The same base table can appear many times under different names. This is a core FileMaker architecture concept.

For example, the `Projects` base table has occurrences:
- `Projects` (primary/same-name)
- `Projects 2`, `Projects 3`, `Projects 4` (used in different relationship chains)
- `LookupProjectID` (used for lookups)

When a layout is based on a specific TO, queries through that layout follow the relationship graph from that TO's perspective.

### Key Table Occurrences by Base Table

**Projects** (5 occurrences): Projects, Projects 2, Projects 3, Projects 4, LookupProjectID

**Contracts** (7 occurrences): Contracts, Companies_Contracts, Companies_Contracts_s, Companies_PeopleContractor_Contracts, MainMenu_Companies_Contracts~Merge01/02/03

**CAANs**: CAANs, ProjectCAANs_CAANs, CAANs_KeyManagement, Projects_CAANs~z_CAAN_g, CAANs_ProjectCAANs~ae

**ProjectCAANs**: ProjectCAANs, Projects_ProjectCAANs, Projects_ProjectCAANs~ae

**Companies** (10 occurrences): Companies, Companies 2, various merge/address aliases

**People** (47 occurrences): People plus many role-specific aliases (Auth PM, Contracts Inspector, etc.)

## Key Relationships

### Projects → Contracts
```
Projects.ID_Primary = Contracts.ID_Projects
```
One project can have multiple contracts. The `Contracts.ProjectNumber` field is a *denormalized* number field (not the join key).

### Projects → CAANs (via ProjectCAANs)
```
Projects.ID_Primary → ProjectCAANs.ID_Project
ProjectCAANs.CAAN → CAANs.CAAN
```
Many-to-many relationship. Note the join to CAANs is on the text CAAN code, not a numeric ID.

### Contracts → ContractAmendments
```
Contracts.ID_Primary = ContractAmendments.ID_Contracts
```

### ContractAmendments → ContractSubContracts
```
ContractAmendments.ID_Primary ↔ ContractSubContracts.ID_Contracts
```
(The `∞` symbol in the DDR indicates a many relationship on this side.)

## Base Table Field Inventories

### Projects (157 fields, ~10,033 records)

**Core identity fields:**
- `ID_Primary` (Number) — primary key
- `ProjectNumber` (Text) — human-readable project number (e.g., "1200", "4932-001")
- `ProjectName` (Text)
- `Status` (Text)

**Key data fields:**
- `Location` (Text)
- `Unit` (Text)
- `Drawings` (Text) — "Yes"/"No" values
- `FileServerLocation` (Text) — relative path on archives file server
- `CAANAssetNumber` (Text) — legacy single-CAAN field (predates the ProjectCAANs join table)
- `CampusClient` (Text)

**Personnel references (numeric FKs to People table):**
- `ID_ProjectManager`
- `ID_Inspector`

**Construction Permit fields (CP*):** ~50 fields for inspection tracking (CPMasterDemo, CPElectricalRough, CPFinalBuilding, etc.)

**Plan Review / Punch List fields:** PlanReviewPercent, PlanReviewPhase, PunchListSpec, etc.

**Calculated/summary fields:** CountContracts_c, CountArchives_c, InspectorFullName, PrimaryFundingNumber, etc.

**UC Export fields (z_UCExport_*):** ~15 calculated fields for data export to UC system

**Audit fields:** z_CreatedBy, z_CreatedDate, z_ModifiedBy, z_ModifiedDate, z_CreatedTimestamp, z_ModificationTimestamp, z_LogData

### Contracts (218 fields, ~5,692 records)

**Core identity fields:**
- `ID_Primary` (Number) — primary key
- `ContractNumber` (Number)
- `ID_Projects` (Number) — FK to Projects.ID_Primary
- `ProjectNumber` (Number) — denormalized project number
- `ProjectNumber_lk` (Text) — lookup project number
- `ProjectName` (Text) — denormalized

**Contract details:**
- `Description` (Text)
- `DescriptionBrief` (Text)
- `ContractForm` (Text) — form type
- `FormTypeBrief` (Text)
- `TypeOfConstruction` (Text)
- `TypesOfWorkers` (Text)
- `Status_ae` (Text) — auto-enter status
- `CEQA` (Text)

**Financial:**
- `OriginalCost` (Number)
- `OriginalTime` (Number) — days
- `Estimate` (Number)
- `Phase1Cost`, `Phase1Time`, `Phase2Cost`, `Phase2Time` (Number)
- `ChangeOrdersCostOfficial` (Calculated, Number)
- `ChangeOrdersRevisedCost` (Calculated, Number)
- `AmendmentsCost`, `AmendmentsCostRevised` (Calculated, Number)

**Dates:**
- `ContractDate` (Date)
- `StartDate` (Date)
- `CompletionDate` (Date)
- `SubstantialCompletion` (Date)
- `BeneficialOccupancy` (Date)
- `ProjectBidDate` (Date)
- `TerminationDate` (Date)
- `JOCStart`, `JOCEnd` (Date)

**Personnel references (numeric FKs):**
- `ID_ContractorContact`, `ID_ContractorSubContact`
- `ID_ProjectManager`, `ID_Inspector`
- `ID_SignOff`, `ID_PPC`, `ID_Plant`, `ID_Architect`

**Company info (denormalized on contract):**
- `CompanyName` (Text) — contractor company
- `CompanyNameArchitect` (Text)
- `ID_Company` (Number) — FK to Companies
- `AddressStreet`, `AddressCity`, `AddressState`, `AddressZipcode` (Text)

**Bid Form fields (BF*):** ~40 fields for bid/contract form data

**SBE (Small Business Enterprise):**
- `SBE_Encumbrance`, `SBE_Contract` (Text)

### CAANs (19 fields, ~1,215+ records)

- `ID_Primary` (Text) — primary key (note: Text type, not Number)
- `CAAN` (Text) — the CAAN code (e.g., "7115", "G144")
- `Name` (Text) — building/facility name
- `Description` (Text)
- `Address` (Text)
- `City` (Text)
- `Zip` (Text)
- `Area` (Text) — campus area
- `Valid_flag` (Number) — validity indicator
- Audit fields: z_CreationTimestamp, z_CreatedBy, z_ModificationTimestamp, z_ModifiedBy

### ProjectCAANs (10 fields, join table)

- `ID_Primary` (Text) — primary key
- `ID_Project` (Number) — FK to Projects.ID_Primary
- `CAAN` (Text) — FK to CAANs.CAAN
- Audit fields: z_CreatedTimestamp, z_CreatedBy, z_ModificationTimestamp, z_ModifiedBy

### ContractAmendments (19 fields, ~103 records)

- `ID_Primary` (Number) — primary key
- `ID_Contracts` (Number) — FK to Contracts.ID_Primary
- `AmendmentNumber` (Number)
- `BidPackageNumber` (Text)
- `OfficialDate` (Date)
- `CostSum_c` (Calculated, Number)
- `ID_Company_lk` (Number)

### ContractSubContracts (19 fields, ~629 records)

- `ID_Primary` (Number) — primary key
- `ID_Contracts` (Number) — FK to Contracts.ID_Primary
- `SubcontractNumber` (Text)
- `Title` (Text)
- `Cost` (Number)
- `ID_Subcontract` (Number) — FK to People/Companies
- `SubcontractorName` (Text) — denormalized
- `BidPackageNumber` (Text)

## Other Notable Tables (not in current sync scope)

- **Companies** (88 fields, ~1,440 records) — contractor/consultant companies
- **People** (61 fields, ~19,100 records) — contacts, PMs, inspectors, etc.
- **Authorizations** (61 fields, ~5,886 records) — project authorizations
- **ChangeOrders** (51 fields) — contract change orders
- **ChangeOrderItems** (56 fields) — line items for change orders
- **WorkRequests** (54 fields) — maintenance/work requests
- **Submittal/SubmittalItems/SubmittalReview** — construction submittal tracking

## Field Naming Conventions

- `ID_Primary` — record's own primary key
- `ID_<TableName>` — foreign key to another table (e.g., `ID_Projects`, `ID_Contracts`)
- `z_*` — system/audit fields (creation/modification timestamps, log data)
- `*_c` — calculated fields (suffix convention)
- `*_g` — global fields (shared across all records)
- `*_lk` — lookup fields
- `*_ae` — auto-enter fields
- `CP*` — construction permit inspection fields
- `BF*` — bid form fields
- `Count*_c` — calculated count of related records

## Deprecated / Legacy Features

The following areas of the UCPPC system are considered deprecated or legacy. They may still contain data but are no longer actively maintained or relied upon:

- **File locations / project file data**: The `FileServerLocation` field on Projects and related file tracking in FileMaker are deprecated. File server location resolution is now handled independently by the archives_app via filesystem scanning.
- **Key Management** (`KeyManagement`, `KeysIssued` tables): Key tracking functionality is no longer actively used.
- **People/Company lists and mailings**: The list-management and mailing features (PeopleLists, PeopleListItems, Labels, etc.) are deprecated. However, the **Companies and People rolodex data itself remains relevant** — the contact/company records are still the system of record for contractor, architect, and personnel information.
- **Archive sheets and print invoices**: The ArchiveSheets, PrintInvoices, and PrintInvoiceItems tables relate to legacy print/physical-archive workflows.

## Data Quality Notes

- Some text fields contain trailing `\r` (carriage return) from legacy data. Use `strip()` or `regexp_replace()`.
- The `Drawings` field on Projects is Text with values like "Yes", "No", "yes", "YES" — not boolean.
- `ProjectNumber` on Projects is Text; `ProjectNumber` on Contracts is Number — type mismatch to be aware of.
- Some fields have spaces in names (e.g., `z_Modification Date`, `Cost Per Set`, `BFSole Source`).
- `CAANs.ID_Primary` is Text type while most other tables use Number for their ID_Primary.
- `CertofOcc` on Contracts is a Text field despite holding date-like values.
