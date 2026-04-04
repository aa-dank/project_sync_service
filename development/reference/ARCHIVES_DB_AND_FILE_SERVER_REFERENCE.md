# Archives Database & File Server Reference

This document provides context for AI agents and developers working with the UCSC PPDO archives system. It covers the PostgreSQL database, the file server, and how to use them together to find construction/project documents.

## System Overview

The archives system tracks **construction project documents** for the UC Santa Cruz Physical Planning, Development & Construction (PPDO) department. It consists of:

1. **PostgreSQL Database** (`business_services_db`) — Indexes ~740K unique files across ~980K file locations, linked to ~9,700 projects and ~1,200 campus buildings (CAANs).
2. **File Server** — A Windows SMB/CIFS share (`//10.133.65.79/PPDO`) containing the actual document files (PDFs, drawings, photos, specs, etc.).
3. **Archives Web App** — Flask application at `/opt/app/archives_app/` that provides a UI for managing the archive.
4. **Archives Scraper** — Nightly worker at `/opt/app/archives_scraper/` that extracts text content and generates embeddings from files.

## Database Connection

- **Host**: `127.0.0.1` (localhost on the app server `ppdo-prod-app-1.vm.aws.ucsc.edu` / `10.132.65.32`)
- **Port**: `5432`
- **Database**: `business_services_db`
- **Read-only user**: `archives_readonly`
- **Read-only password**: stored in `/home/adankert/readonly.env`
- **Admin user**: `archives_admin` (used by the app; avoid for read-only tasks)
- **PostgreSQL version**: 17
- **SSL**: Available but not required for localhost connections

### Connecting via psql

```bash
# Load creds from env file (note: file uses spaces around '=')
PGPASSWORD='1156H!gh' psql -h 127.0.0.1 -U archives_readonly -d business_services_db
```

### Connecting from Python

```python
import psycopg2
conn = psycopg2.connect(
    host="127.0.0.1",
    port=5432,
    database="business_services_db",
    user="archives_readonly",
    password="1156H!gh"
)
```

## File Server & Path Conventions

### The File Share

The file server is a Windows SMB share at `//10.133.65.79/PPDO`. It is mounted on the app server in two places:

| Share Path | App Server Mount Point |
|---|---|
| `//10.133.65.79/PPDO` | `/opt/app/mnt/PPDO` |
| `//10.133.65.79/PPDO/Records` | `/opt/app/Records` |

The **Records** subdirectory is where all indexed project files live. This is the root that database paths are relative to.

### Path Mapping (CRITICAL)

Database columns `file_locations.file_server_directories` and `projects.file_server_location` store paths **relative to the Records root** using forward slashes.

To construct a usable filesystem path, prepend the appropriate mount root for your system:

**On the app server (Linux):**
```
/opt/app/mnt/PPDO/Records/ + <file_server_directories> + / + <filename>
```
Example:
```
/opt/app/mnt/PPDO/Records/12xx   Hahn/1200/1200/A - General/some_document.pdf
```

**On Windows user PCs (mapped drive):**
```
N:\PPDO\Records\ + <file_server_directories (backslashes)> + \ + <filename>
```
Example:
```
N:\PPDO\Records\12xx   Hahn\1200\1200\A - General\some_document.pdf
```

**On any other system:** Replace the root prefix with wherever the share is mounted and convert slashes as needed. The relative path portion from the database is always the same.

### Converting Paths Between Platforms

When an agent is running on a platform different from the app server:
- Replace forward slashes with backslashes (Windows) or vice versa (Linux/macOS)
- Prepend the correct mount root for the target system
- The `file_server_directories` value from the DB is the **directory** path only; append `filename` to get the full file path

### Top-Level Records Directory Structure

The Records directory is organized by project number ranges associated with campus buildings:

```
Records/
├── 00xx  Consulting Agreements/
├── 01xx   JOCs/
├── 10xx   Regulatory Requirements/
├── 12xx   Hahn/
│   ├── 1200/
│   │   └── 1200/
│   │       ├── A - General/
│   │       ├── E - Program and Design/
│   │       ├── F - Bid Documents and Contract Award/
│   │       └── G - Construction/
│   ├── 1201/
│   └── ...
├── 13xx   Original Ranch Buildings/
├── 14xx   Thimann Labs/
├── 49xx   Long Marine Lab/
├── 55xx   College 9 & 10/
├── 100xx  Multiple Locations/
└── ...
```

Each project folder is organized using a standardized filing code system (A through H, with subcategories like G21 for Construction Photos).

## Database Tables

### Core Tables for Finding Files

#### `caans` (1,215 rows)
Campus buildings/facilities. "CAAN" is a campus asset/account number. This is the starting point when searching by building name.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| caan | varchar | CAAN code (e.g., "7115", "G144", "P101") |
| name | varchar | Building/facility name (e.g., "Hahn Student Services") |
| description | varchar | Additional description |

Sample data:
```
 id   | caan | name                    | description
------+------+-------------------------+----------------------------
 2112 | 7115 | Hahn Student Services   | Hahn Student Services
 2189 | 7199 | Hahn Art Facility       | Hahn Art Facility
 2023 | 7010 | Chinquapin              | Equipment on UCSC main campus
 2024 | 7011 | Village Housing B1      | Village Housing B1
```

#### `projects` (9,710 rows)
Construction projects. Each project has a number, name, and optionally a file server location.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| number | varchar | Project number (e.g., "1200", "1200-032", "4932") |
| name | varchar | Project description |
| file_server_location | varchar | Relative path to project folder on file server (may be NULL) |
| drawings | boolean | Whether project has drawings |

Sample data:
```
 id    | number | name                                                           | file_server_location
-------+--------+----------------------------------------------------------------+---------------------------
 64682 | 1200   | Hahn Central Student Services - Preliminary, Ancillary and ... | 12xx   Hahn/1200/1200
 64683 | 1201   | Hahn Central Student Services - Original Construction...       | 12xx   Hahn/1201/1201
 64684 | 1202   | Hahn Central Student Services - Alterations                    | 12xx   Hahn/1202
```

Note: Some projects (especially sub-projects like "1200-032") may have NULL `file_server_location`.

#### `project_caans` (11,018 rows)
Many-to-many join table linking projects to CAANs (buildings).

| Column | Type | Description |
|---|---|---|
| project_id | integer (PK, FK → projects.id) | Project reference |
| caan_id | integer (PK, FK → caans.id) | CAAN reference |

#### `files` (739,600 rows)
Unique files identified by content hash. A single file (same hash) may appear in multiple locations.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| hash | varchar (UNIQUE) | SHA-1 hash of file content |
| size | bigint | File size in bytes |
| extension | varchar | File extension (e.g., "pdf", "jpg", "dwg") |

Top file types by count: pdf (298K), jpg (108K), tif (91K), dwg (64K), doc (22K), docx (9K), xls (9K), xlsx (5K).

#### `file_locations` (979,315 rows)
Maps files to their location(s) on the file server. This is the key table for finding where files are.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| file_id | integer (FK → files.id) | Reference to the file |
| file_server_directories | varchar | **Relative directory path** from the Records root (forward slashes) |
| filename | varchar | The filename including extension |
| existence_confirmed | timestamp | Last time the file was confirmed to exist on disk |
| hash_confirmed | timestamp | Last time the file hash was re-verified |

Sample data:
```
 id     | file_id | file_server_directories                                            | filename
--------+---------+--------------------------------------------------------------------+----------------------------
 620132 | 414708  | 49xx   Long Marine Lab/4932/4932/G - Construction/G21 Constr...    | DSC_0065_MV_MFAETKPRKHUA.JPG
```

**Full-text search indexes** exist on both `file_server_directories` and `filename` columns (GIN indexes on tsvector). The app uses `websearch_to_tsquery()` for searching.

### Content & Analysis Tables (populated by archives_scraper)

#### `file_contents` (79,818 rows, 1.8 GB)
Extracted text and vector embeddings for files. Populated by the nightly archives_scraper.

| Column | Type | Description |
|---|---|---|
| file_hash | varchar (PK, FK → files.hash) | Links to files.hash |
| source_text | text | Extracted text content |
| minilm_model | text | Embedding model name (default: "all-MiniLM-L6-v2") |
| minilm_emb | vector | MiniLM embedding vector (binary, pgvector type) |
| mpnet_model | text | Optional second embedding model name |
| mpnet_emb | vector | Optional second embedding vector |
| text_length | integer | Character count of source_text |
| updated_at | timestamptz | When content was last extracted |

IVFFlat indexes exist on `minilm_emb` and `mpnet_emb` for vector similarity search.

#### `file_content_failures` (4,395 rows)
Tracks files that failed text extraction or embedding (to avoid retrying endlessly).

| Column | Type | Description |
|---|---|---|
| file_hash | varchar (PK, FK → files.hash) | Links to files.hash |
| stage | text | Which stage failed ("extraction", "embedding", etc.) |
| error | text | Error message |
| attempts | integer | Number of failed attempts |
| last_failed_at | timestamptz | When the last failure occurred |

#### `file_date_mentions` (50,263 rows)
Dates found mentioned within document text (extracted by scraper).

| Column | Type | Description |
|---|---|---|
| file_hash | varchar (PK, FK → files.hash) | Links to files.hash |
| mention_date | date (PK) | The date mentioned in the document |
| granularity | text (PK) | "day", "month", or "year" |
| mentions_count | integer | How many times this date appears |
| extractor | text | Extraction method (e.g., "regex-basic") |
| extracted_at | timestamptz | When extraction was performed |

### Operational Tables

#### `archived_files` (65,489 rows)
Records of files that were archived (filed) by archivists through the web app. Contains metadata about the archiving action.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| file_id | integer (FK → files.id) | Reference to the file |
| destination_path | varchar | Relative path where file was archived (from Records root) |
| project_number | varchar | Project number the file was filed under |
| document_date | varchar | Date of the document (free text) |
| file_code | varchar | Filing code (e.g., "A", "G", "G21") |
| filename | varchar | Original filename |
| file_size | float | File size |
| date_archived | timestamp | When the file was archived |
| archivist_id | integer (FK → users.id) | Who archived it |
| notes | varchar | Archivist notes |

#### `server_changes` (111,633 rows)
Audit log of file/folder operations (CREATE, DELETE, RENAME, MOVE) on the file server.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| old_path | varchar | Original path (full path including mount point) |
| new_path | varchar | New path (for RENAME/MOVE/CREATE) |
| change_type | varchar | "CREATE", "DELETE", "RENAME", "MOVE" |
| files_effected | integer | Number of files affected |
| data_effected | numeric | Bytes affected |
| date | timestamp | When the change occurred |
| user_id | integer (FK → users.id) | Who made the change |

Note: Paths in `server_changes` use **full absolute paths** (e.g., `/opt/app/mnt/PPDO/Records/...`), unlike other tables which use relative paths.

#### `users` (25 rows)
Application user accounts.

| Column | Type | Description |
|---|---|---|
| id | integer (PK) | Auto-increment ID |
| email | varchar (UNIQUE) | Email address |
| first_name | varchar | First name |
| last_name | varchar | Last name |
| roles | varchar | Comma-separated roles: "ADMIN", "ARCHIVIST", "STAFF" |
| password | varchar | Hashed password |
| active | boolean | Whether the account is active |

#### `worker_tasks` (26,534 rows)
Background job tracking for the RQ task queue.

#### `timekeeper` (3,804 rows)
Employee clock-in/clock-out records.

#### `schema_migration` (1 row)
Internal migration tracking.

## Common Query Patterns

### 1. Find a building by name

```sql
SELECT id, caan, name, description
FROM caans
WHERE name ILIKE '%hahn%';
```

Result:
```
 id   | caan | name                    | description
------+------+-------------------------+-------------------------
 2112 | 7115 | Hahn Student Services   | Hahn Student Services
 2189 | 7199 | Hahn Art Facility       | Hahn Art Facility
 ...
```

### 2. Find projects for a building (via CAAN)

```sql
SELECT p.id, p.number, p.name, p.file_server_location
FROM projects p
JOIN project_caans pc ON p.id = pc.project_id
WHERE pc.caan_id = 2112  -- Hahn Student Services
ORDER BY p.number;
```

### 3. Find files in a project's directory

```sql
SELECT fl.file_server_directories, fl.filename, f.extension, f.size
FROM file_locations fl
JOIN files f ON fl.file_id = f.id
WHERE fl.file_server_directories LIKE '12xx   Hahn/1200%'
LIMIT 20;
```

### 4. Full-text search across filenames and paths

```sql
-- Search filenames for "lighting fixture"
SELECT fl.file_server_directories, fl.filename
FROM file_locations fl
WHERE to_tsvector('english', fl.filename) @@ websearch_to_tsquery('lighting fixture')
LIMIT 20;

-- Search both path and filename
SELECT fl.file_server_directories, fl.filename
FROM file_locations fl
WHERE (to_tsvector('english', fl.filename) || to_tsvector('english', fl.file_server_directories))
      @@ websearch_to_tsquery('lighting fixture')
LIMIT 20;
```

### 5. End-to-end: Building name → files

Given a question like "find lighting fixture documents for Hahn Student Services":

```sql
-- Step 1: Find the CAAN(s)
-- Step 2: Find projects linked to those CAANs
-- Step 3: Search file_locations within those project paths

SELECT fl.file_server_directories, fl.filename, f.extension, f.size
FROM file_locations fl
JOIN files f ON fl.file_id = f.id
WHERE fl.file_server_directories LIKE ANY (
    SELECT p.file_server_location || '%'
    FROM projects p
    JOIN project_caans pc ON p.id = pc.project_id
    JOIN caans c ON pc.caan_id = c.id
    WHERE c.name ILIKE '%hahn student services%'
      AND p.file_server_location IS NOT NULL
)
AND (
    to_tsvector('english', fl.filename) @@ websearch_to_tsquery('lighting fixture')
    OR fl.filename ILIKE '%light%'
)
LIMIT 20;
```

### 6. Search extracted text content

```sql
-- Find files whose extracted text mentions a topic
SELECT fl.file_server_directories, fl.filename, fc.text_length
FROM file_contents fc
JOIN files f ON fc.file_hash = f.hash
JOIN file_locations fl ON fl.file_id = f.id
WHERE fc.source_text ILIKE '%lighting fixture%'
LIMIT 20;
```

### 7. Construct a user-facing file path from query results

Given a `file_server_directories` value and `filename` from the database:

**For Linux (app server):**
```
full_path = "/opt/app/mnt/PPDO/Records/" + file_server_directories + "/" + filename
```

**For Windows (user PC with N: drive mapped):**
```
full_path = "N:\\PPDO\\Records\\" + file_server_directories.replace("/", "\\") + "\\" + filename
```

**Generic formula:**
```
full_path = <MOUNT_ROOT_FOR_YOUR_SYSTEM> + "/" + file_server_directories + "/" + filename
```

## Filing Code System

Project folders use a standardized filing code hierarchy. These are the top-level codes:

- **A** - General
- **B** - Administrative Reviews and Approvals
- **C** - Consultants
- **D** - Environmental Review Process
- **E** - Program and Design
- **F** - Bid Documents and Contract Award
- **G** - Construction
- **H** - Submittals and O&M's

Each has subcategories (e.g., G21 = Construction Photos, F5 = Drawings and Specifications, E6 = Reports). These appear as subdirectory names like `G - Construction/G21 Construction Photos/`.

## Key Relationships Diagram

```
caans (buildings)
  │
  └── project_caans (many-to-many)
        │
        └── projects (construction projects)
              │
              └── [file_server_location] ──→ directory on file server
                    │
                    └── file_locations (file paths on server)
                          │
                          └── files (unique by hash)
                                │
                                ├── file_contents (extracted text + embeddings)
                                ├── file_content_failures (extraction errors)
                                └── file_date_mentions (dates found in text)

archived_files ──→ files (records of archival actions)
server_changes (audit log of file server operations)
users (app accounts, referenced by archived_files and server_changes)
```

## Notes for Agents

1. **Path slashes**: Database stores forward slashes. Convert to backslashes for Windows paths.
2. **NULL file_server_location**: Many projects (especially sub-projects like "1200-032") don't have a `file_server_location`. You can still find their files via `file_locations` where `file_server_directories` contains the project number.
3. **Case sensitivity**: Use `ILIKE` for case-insensitive searches in PostgreSQL. Building names and file paths may have inconsistent casing.
4. **Carriage returns**: Some text fields contain trailing `\r` from legacy data imports. Use `trim()` or `regexp_replace()` if needed.
5. **file_contents coverage**: Only ~80K of ~740K files have extracted text so far. The scraper runs nightly and processes more files over time.
6. **Full-text search**: Use the GIN indexes on `file_locations` for text search — they are much faster than `LIKE`/`ILIKE` on this ~1M row table.
7. **server_changes paths are absolute**: Unlike `file_locations` and `projects`, the `server_changes` table stores full filesystem paths (e.g., `/opt/app/mnt/PPDO/Records/...`).
8. **Read-only access**: The `archives_readonly` user has SELECT-only access. Do not attempt to modify data.
