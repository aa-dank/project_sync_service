# FileMaker-to-PostgreSQL field mapping

This reference describes the data currently synchronized from FileMaker into
PostgreSQL. The authoritative, machine-readable definition is
[`config/field_mappings.yaml`](../config/field_mappings.yaml); update that file
first when changing a mapping.

## Overview

| Sync entity | FileMaker layout | PostgreSQL table | Sync identity |
| --- | --- | --- | --- |
| CAANs | `ImportCAANs` | `caans` | `caan` |
| Projects | `ImportProjects` | `projects` | `fmp_id_primary` |
| Project–CAAN links | `ImportProjectCAANs` | `project_caans` | Resolved `project_id` + `caan_id` |
| Contracts | `ImportContracts` | `contracts` | `fmp_id_primary` |

The run order is CAANs, projects, contracts, then project–CAAN links, so the
required referenced records are available before foreign keys are resolved.

## Value conversions

| Conversion | Result |
| --- | --- |
| `strip` | Trimmed text; blank values become `NULL`. |
| `integer` | Converted to an integer; invalid or blank values become `NULL`. |
| `decimal` | Converted to a decimal value; invalid or blank values become `NULL`. |
| `date` | Converted to a date; invalid or blank values become `NULL`. |
| `boolean_yesno` | `Yes` → `true`; `No` → `false`; any other value → `NULL`. |
| `boolean_closed` | `Closed` → `true`; every other value, including blank, → `false`. |

## CAANs: `ImportCAANs` → `caans`

| FileMaker field | PostgreSQL column | Conversion | Notes |
| --- | --- | --- | --- |
| `ID_Primary` | `fmp_id_primary` | integer | FM field is text; stored as an integer. |
| `CAAN` | `caan` | strip | Sync identity; unique in PostgreSQL. |
| `Name` | `name` | strip | |
| `Description` | `description` | strip | |
| `Address` | `address_street` | strip | |
| `City` | `address_city` | strip | |
| `Zip` | `address_zip` | strip | |
| `Area` | `area` | strip | |

## Projects: `ImportProjects` → `projects`

| FileMaker field | PostgreSQL column | Conversion | Notes |
| --- | --- | --- | --- |
| `ID_Primary` | `fmp_id_primary` | integer | Required; sync identity. |
| `ProjectNumber` | `number` | strip | Records with a blank or digitless project number are skipped. Project number is not assumed unique. |
| `ProjectName` | `name` | strip | |
| `Drawings` | `drawings` | boolean_yesno | |
| `Status` | `closed` | boolean_closed | |

## Contracts: `ImportContracts` → `contracts`

| FileMaker field | PostgreSQL column | Conversion | Notes |
| --- | --- | --- | --- |
| `ID_Primary` | `fmp_id_primary` | integer | Required; sync identity. |
| `ContractNumber` | `contract_number` | integer | Required. |
| `ID_Projects` | `project_id` | integer | Required lookup: matched to `projects.fmp_id_primary`, then its PostgreSQL `id` is stored. |
| `ProjectNumber_lk` | `project_id` | strip | Fallback lookup only: matched to `projects.number` if `ID_Projects` does not resolve. May be ambiguous. |
| `ContractDate` | `contract_date` | date | |
| `StartDate` | `ntp_start_date` | date | NTP = Notice to Proceed. |
| `BeneficialOccupancyDate` | `beneficial_occupancy_date` | date | |
| `SubstantialCompletionDate` | `substantial_completion_date` | date | |
| `CertofOcc` | `certificate_of_occupancy_date` | date | FM text field parsed as a date. |
| `CompletionDate` | `noc_completion_date` | date | NOC = Notice of Completion. |
| `DateRecorded` | `noc_recorded_date` | date | |
| `TerminationDate` | `termination_date` | date | |
| `ProjectBidDate` | `bid_date` | date | |
| `ChangeOrdersRevisedDate` | `change_order_revised_expected_end` | date | Calculated FM field. |
| `Estimate` | `cost_estimate` | decimal | |
| `OriginalCost` | `original_contract_cost` | decimal | |
| `ChangeOrdersCostOfficial` | `change_order_total` | decimal | Calculated FM field. |
| `ChangeOrdersRevisedCost` | `change_order_revised_cost` | decimal | Calculated FM field. |
| `AccountNumber` | `account_number` | strip | |
| `CFRNumber` | `funding_number` | strip | |
| `OriginalTime_c` | `original_project_duration` | integer | Effective original duration in calendar days. FileMaker uses `OriginalTime` for standard contracts and `Phase1Time + Phase2Time` for CM-at-Risk contracts. |
| `ChangeOrdersTimeOfficial` | `change_order_time_total` | integer | Calculated FM field; duration in days. |
| `ChangeOrdersRevisedTime` | `change_order_revised_duration` | integer | Calculated FM field; duration in days. |
| `CompanyName` | `contractor_org_name` | strip | |
| `Contracts Architect::Company_c` | `executive_design_org_name` | strip | Related FM field; no related record becomes `NULL`. |
| `BFDescriptionofWork` | `scope_description` | strip | |

`ID_Projects` and `ProjectNumber_lk` are not stored as contract columns.
They are temporary resolver values: the result is `contracts.project_id`. If
neither lookup finds a project, `project_id` is stored as `NULL`.

## Project–CAAN links: `ImportProjectCAANs` → `project_caans`

`project_caans` is a join table rather than a direct field-for-field copy. It
stores the resolved PostgreSQL IDs as a composite relationship.

| FileMaker field | Resolution | PostgreSQL result | Notes |
| --- | --- | --- | --- |
| `ID_Project` | Match against `projects.fmp_id_primary` | `project_id` | Required; source ID itself is not persisted in the join table. |
| `CAAN` | Match against `caans.caan` | `caan_id` | Required; source CAAN code itself is not persisted in the join table. |

Rows whose project or CAAN cannot be resolved are skipped and logged. The
table persists only `(project_id, caan_id)`.

## Sync-managed PostgreSQL columns

The mapping tables above exclude PostgreSQL-generated or service-managed
columns. In particular, the service sets `last_synced_at` from the PostgreSQL
clock whenever it upserts a CAAN, project, or contract. Primary keys such as
`id` are maintained by PostgreSQL.
