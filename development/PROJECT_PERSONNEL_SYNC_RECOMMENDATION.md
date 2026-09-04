# Project inspector and project-manager sync recommendation

## Recommendation

Add the two FileMaker person IDs and two current display-name snapshots directly
to PostgreSQL's `projects` table. Do **not** start by adding a full `people`
sync or a PostgreSQL `people` table.

Suggested PostgreSQL columns:

```sql
ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS inspector_fmp_id INTEGER,
    ADD COLUMN IF NOT EXISTS inspector_name TEXT,
    ADD COLUMN IF NOT EXISTS project_manager_fmp_id INTEGER,
    ADD COLUMN IF NOT EXISTS project_manager_name TEXT;
```

These are FileMaker IDs, not PostgreSQL foreign keys. The name values are
deliberately denormalized snapshots: they make the common use case (show the
current inspector and PM on a project) available without introducing another
synced entity or retaining all 19,000 People records.

This is a small-to-moderate change to the service, not a difficult relational
integration. The FileMaker relationships already resolve each person.

## What the FileMaker design actually does

The source is not a join table or a view. It is two stored numeric foreign-key
fields on the `Projects` base table:

| Project role | Stored FileMaker field | Role-specific People table occurrence | Join |
| --- | --- | --- | --- |
| Project manager | `Projects::ID_ProjectManager` | `Projects People PM` | `ID_ProjectManager = People::ID_Primary` |
| Inspector | `Projects::ID_Inspector` | `Project People Inspector` | `ID_Inspector = People::ID_Primary` |

The two right-hand occurrences are aliases of the same `People` base table;
they exist so FileMaker can hold both roles for one project at the same time.
They do not add cardinality or create a many-to-many relationship.

The FileMaker DDR confirms that `ID_ProjectManager` and `ID_Inspector` are
normal Number fields, and that both are already placed on `ImportProjects`.
Therefore the service can fetch their IDs with no FileMaker schema change.

The DDR also defines two useful calculated `Projects` fields:

| FileMaker field | Calculation source | Suggested PostgreSQL column |
| --- | --- | --- |
| `z_UCExport_ProjectManager` | `Projects People PM::NameLastFirst` | `project_manager_name` |
| `z_UCExport_Inspector` | `Project People Inspector::NameLastFirst` | `inspector_name` |

Those calculations provide a consistent `Last, First` display format and are a
better matched pair than `InspectorFullName`: the latter is an older calculated
field whose DDR calculation text only contains a comment. The two export
calculation fields are not currently shown as being on `ImportProjects`; add
them to that layout before relying on them through the Data API. A FileMaker
field must be placed on the layout for the API to return it.

`ImportPeople` also exists and includes the `People` base-table fields, so a
future normalized People sync is possible. It is not necessary for this
project-role feature.

## Proposed implementation

1. Have the FileMaker administrator add `z_UCExport_ProjectManager` and
   `z_UCExport_Inspector` to `ImportProjects`. The existing calculated fields
   and relationships can be reused; no new relationship or calculation is
   required.
2. Apply the four-column SQL change through the normal external PostgreSQL
   deployment workflow. This repository currently has no
   `src/project_sync_service/migrations/` directory, despite older development
   notes referring to SQL artifacts, so the deployment SQL should be tracked
   or handed to the database deployment owner explicitly.
3. Extend the `projects` entry in `config/field_mappings.yaml` (the mapping
   source of truth):

   ```yaml
   - fm: ID_Inspector
     pg: inspector_fmp_id
     transform: integer
     critical: true
   - fm: ID_ProjectManager
     pg: project_manager_fmp_id
     transform: integer
     critical: true
   - fm: z_UCExport_Inspector
     pg: inspector_name
     transform: strip
     critical: true
   - fm: z_UCExport_ProjectManager
     pg: project_manager_name
     transform: strip
     critical: true
   ```

   Marking all four fields critical is appropriate once the layout is updated:
   a missing layout field should fail preflight rather than silently make the
   new data incomplete.
4. Add the four PostgreSQL columns to `PERSIST_COLUMNS`, `UPDATE_COLUMNS`, and
   the `db.get_all(... columns=...)` list in
   `src/project_sync_service/sync/projects.py`. No new sync entity, resolver,
   ordering rule, or special transform is needed.
5. Update `development/FILEMAKER_POSTGRES_FIELD_MAPPING.md` and run
   `project-sync validate`, followed by `project-sync run --entity projects
   --dry-run`, before the first write.

## Complexity and risks

| Area | Assessment | Why |
| --- | --- | --- |
| FileMaker work | Low | Add two existing calculated fields to the already-used import layout. |
| PostgreSQL work | Low | Four nullable columns; no FK or backfill matching is required. |
| Python service work | Low | Four ordinary mappings and existing project upsert lists. |
| Deployment verification | Moderate | Verify that the Data API returns both fields, including projects without a role. |
| Ongoing correctness | Low | Each project sync refreshes the current ID/name snapshot from FileMaker. |

The primary operational risk is layout exposure, not relationship resolution.
The existing `projects` sync currently passes a mapping value through to its
upsert columns; unlike the contracts sync, it does not preserve an existing
value when a mapped FileMaker field is absent. Do not add optional personnel
mappings before the FileMaker layout change. Making them critical and running
preflight prevents an absent layout field from reaching an upsert.

Null is expected and should overwrite old values when a project has no current
PM or inspector. The implementation must distinguish that valid FileMaker null
from a field missing because the layout was not updated.

## When a full People sync becomes worthwhile

Choose a separate `people` entity only if consumers need more than these two
current project-role snapshots: contact details, titles, inactive state,
company relationships, reuse across contracts/authorizations, or querying a
person's full portfolio of projects.

That is a medium-sized feature. It needs a new PostgreSQL `people` table, its
own `ImportPeople` mapping and sync module, a unique conflict key on
`fmp_id_primary`, a dependency order of People before Projects, and a decision
about hard-delete behavior and foreign keys. PostgreSQL foreign keys would also
make the service's existing hard-delete parity policy more consequential.

Even then, retain the FileMaker person IDs on `projects` and resolve them to
PostgreSQL `people.id` during the project sync, following the existing
contracts/project and project-CAAN resolver patterns. Do not attempt to match
people by name.

## Evidence consulted

- `development/reference/fmp_database_design_report/UCPPC_ddr/UCPPC.html`
  (Projects and People field definitions, `ImportProjects` layout, the two
  relationship definitions, and `ImportPeople` layout)
- `config/field_mappings.yaml`
- `src/project_sync_service/sync/projects.py`
- `src/project_sync_service/preflight.py`
