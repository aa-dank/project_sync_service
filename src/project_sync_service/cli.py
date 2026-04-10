"""
CLI entry point for project_sync_service.
Uses Click for commands and Rich for terminal output.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .config import load_config, AppConfig
from .db import Database
from .fm_adapter import FileMakerAdapter, FileMakerError
from .mappings import load_mappings
from .preflight import run_preflight
from .sync.base import SyncResult
from .sync.caans import sync_caans
from .sync.contracts import sync_contracts
from .sync.project_caans import sync_project_caans
from .sync.projects import sync_projects
from .utils import get_run_id, setup_logging

console = Console()
logger = logging.getLogger(__name__)

ENTITY_ORDER = ["caans", "projects", "contracts", "project_caans"]
ENTITY_SYNCS = {
    "caans": sync_caans,
    "projects": sync_projects,
    "contracts": sync_contracts,
    "project_caans": sync_project_caans,
}


@click.group()
@click.version_option()
def cli() -> None:
    """project-sync: Sync data from FileMaker (UCPPC) into PostgreSQL (business_services_db)."""


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--entity", "-e",
              type=click.Choice(ENTITY_ORDER + ["project-caans"]),
              default=None,
              help="Sync only a specific entity. Defaults to all in dependency order.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would change without writing to the database.")
def run(entity: Optional[str], dry_run: bool) -> None:
    """Run the sync (all entities or a single entity)."""
    # Normalise project-caans → project_caans
    if entity == "project-caans":
        entity = "project_caans"

    cfg = _load_config_or_exit()
    setup_logging(cfg.log_level)
    run_id = get_run_id()

    if dry_run:
        console.print(f"[bold yellow]DRY RUN — no changes will be written.[/bold yellow]")

    console.print(f"[dim]Run ID: {run_id}[/dim]")
    logger.info("Starting sync run=%s dry_run=%s entity=%s", run_id, dry_run, entity or "all")

    mappings = load_mappings(cfg.mappings_path)
    entities_to_run = [entity] if entity else ENTITY_ORDER

    start_time = time.monotonic()
    results: list[SyncResult] = []

    with FileMakerAdapter(cfg.fm) as fm, Database(cfg.pg) as db:
        db.connect()
        for ent_name in entities_to_run:
            ent_mapping = mappings.get(ent_name)
            if not ent_mapping:
                console.print(f"[red]Unknown entity '{ent_name}' — skipping.[/red]")
                continue

            sync_fn = ENTITY_SYNCS[ent_name]
            console.print(f"\n[bold]Syncing {ent_name}…[/bold]")
            try:
                result = sync_fn(
                    entity=ent_mapping,
                    fm=fm,
                    db=db,
                    fetch_limit=cfg.fm.fetch_limit,
                    dry_run=dry_run,
                )
                results.append(result)
                _print_result_row(result)
            except Exception as exc:
                logger.exception("Error syncing %s: %s", ent_name, exc)
                console.print(f"[red]  ERROR: {exc}[/red]")
                results.append(SyncResult(entity=ent_name, errors=1, error_details=[str(exc)]))

    elapsed = time.monotonic() - start_time
    _print_summary_table(results, elapsed, dry_run)
    _log_structured_summary(results, elapsed, run_id)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@cli.command()
def check() -> None:
    """Test FileMaker and PostgreSQL connections."""
    cfg = _load_config_or_exit()
    setup_logging(cfg.log_level)

    console.print("[bold]Checking connections…[/bold]\n")

    fm = FileMakerAdapter(cfg.fm)
    try:
        fm.ping()
        console.print("[green]✓[/green] FileMaker connection OK")
    except FileMakerError as exc:
        console.print(f"[red]✗ FileMaker connection FAILED:[/red] {exc}")
    except Exception as exc:
        console.print(f"[red]✗ FileMaker connection FAILED:[/red] {exc}")
    finally:
        fm.logout()

    db = Database(cfg.pg)
    if db.ping():
        console.print("[green]✓[/green] PostgreSQL connection OK")
    else:
        console.print("[red]✗ PostgreSQL connection FAILED[/red]")
    db.close()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@cli.command()
def validate() -> None:
    """Validate FM layouts, required fields, and PG connectivity before first sync."""
    cfg = _load_config_or_exit()
    setup_logging(cfg.log_level)
    mappings = load_mappings(cfg.mappings_path)

    console.print("[bold]Running preflight validation…[/bold]\n")

    fm = FileMakerAdapter(cfg.fm)
    db = Database(cfg.pg)
    try:
        db.connect()
        result = run_preflight(fm, db, mappings, cfg.fm.fetch_limit)
    finally:
        fm.logout()
        db.close()

    for msg in result.passed:
        console.print(f"[green]✓[/green] {msg}")
    for msg in result.warnings:
        console.print(f"[yellow]⚠[/yellow] {msg}")
    for msg in result.failures:
        console.print(f"[red]✗[/red] {msg}")

    console.print()
    if result.ok:
        console.print("[bold green]Validation passed.[/bold green]")
    else:
        console.print(f"[bold red]Validation FAILED ({len(result.failures)} failure(s)).[/bold red]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# mappings
# ---------------------------------------------------------------------------

@cli.command("mappings")
def show_mappings() -> None:
    """Display the current field mappings from field_mappings.yaml."""
    from dotenv import load_dotenv
    load_dotenv(override=False)
    mappings_path = Path(os.environ.get(
        "MAPPINGS_PATH",
        str(Path(__file__).resolve().parent.parent.parent / "config" / "field_mappings.yaml"),
    ))
    all_mappings = load_mappings(mappings_path)

    for entity_name, entity in all_mappings.items():
        table = Table(
            title=f"{entity_name}  (FM layout: {entity.fm_layout} → PG table: {entity.pg_table})",
            show_lines=True,
        )
        table.add_column("FM Field", style="cyan")
        table.add_column("PG Column", style="green")
        table.add_column("Transform")
        table.add_column("Lookup Only")

        for f in entity.fields:
            lookup_str = "✓" if f.is_lookup_only else ""
            table.add_row(f.fm, f.pg, f.transform or "", lookup_str)

        console.print(table)
        console.print()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@cli.command()
def status() -> None:
    """Show current sync status (last synced timestamps from the database)."""
    cfg = _load_config_or_exit()
    setup_logging(cfg.log_level)

    db = Database(cfg.pg)
    try:
        db.connect()
        table = Table(title="Sync Status", show_lines=True)
        table.add_column("Entity", style="bold")
        table.add_column("Table")
        table.add_column("Row Count")
        table.add_column("Last Synced")

        status_queries = [
            ("caans", "caans"),
            ("projects", "projects"),
            ("contracts", "contracts"),
            ("project_caans", "project_caans"),
        ]

        for entity_name, tbl in status_queries:
            try:
                row = db.fetchone(f"SELECT COUNT(*) AS cnt FROM {tbl}")  # noqa: S608
                count = row["cnt"] if row else "?"
            except Exception:
                count = "table missing"

            last_synced = "—"
            if tbl not in ("project_caans",):
                try:
                    row2 = db.fetchone(
                        f"SELECT MAX(last_synced_at) AS ts FROM {tbl}"  # noqa: S608
                    )
                    if row2 and row2["ts"]:
                        last_synced = str(row2["ts"])
                except Exception:
                    pass

            table.add_row(entity_name, tbl, str(count), last_synced)

        console.print(table)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config_or_exit() -> AppConfig:
    try:
        return load_config()
    except RuntimeError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        sys.exit(1)


def _print_result_row(result: SyncResult) -> None:
    parts = [
        f"[green]+{result.added} added[/green]",
        f"[yellow]~{result.updated} updated[/yellow]",
        f"[red]-{result.removed} removed[/red]",
    ]
    if result.errors:
        parts.append(f"[bold red]{result.errors} error(s)[/bold red]")
    console.print("  " + "  ".join(parts))


def _print_summary_table(results: list[SyncResult], elapsed: float, dry_run: bool) -> None:
    title = "Sync Summary (DRY RUN)" if dry_run else "Sync Summary"
    table = Table(title=title, show_lines=True)
    table.add_column("Entity", style="bold")
    table.add_column("Added", style="green", justify="right")
    table.add_column("Updated", style="yellow", justify="right")
    table.add_column("Removed", style="red", justify="right")
    table.add_column("Errors", style="bold red", justify="right")

    for r in results:
        table.add_row(r.entity, str(r.added), str(r.updated), str(r.removed), str(r.errors))

    console.print()
    console.print(table)
    console.print(f"\n[dim]Completed in {elapsed:.1f}s[/dim]")


def _log_structured_summary(
    results: list[SyncResult],
    elapsed: float,
    run_id: str,
) -> None:
    summary = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(elapsed, 2),
        "entities": [
            {
                "entity": r.entity,
                "added": r.added,
                "updated": r.updated,
                "removed": r.removed,
                "errors": r.errors,
                "error_details": r.error_details,
            }
            for r in results
        ],
    }
    logger.info("Sync complete: %s", json.dumps(summary))


if __name__ == "__main__":
    cli()
