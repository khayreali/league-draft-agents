import asyncio
import logging

import typer

app = typer.Typer(help="League draft analyst — multi-agent draft recommender")


@app.command()
def ingest(
    since: str = typer.Option(..., help="Start date, e.g. 2026-03-01"),
    platforms: str = typer.Option("kr,euw1,na1", help="Platforms to pull from"),
    max_players: int = typer.Option(10, help="Max players per platform"),
    matches_per_player: int = typer.Option(10, help="Matches per player"),
    num_patches: int = typer.Option(5, help="Number of recent patches to scrape notes for"),
):
    """Pull recent high-elo matches, patch notes, and champion data."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_ingest(since, platforms, max_players, matches_per_player, num_patches))


async def _ingest(
    since: str, platforms: str, max_players: int,
    matches_per_player: int, num_patches: int,
):
    from draft_analyst.data.data_dragon import DataDragonClient
    from draft_analyst.data.ingestion import IngestionPipeline
    from draft_analyst.data.riot_client import RiotClient

    platform_list = [p.strip() for p in platforms.split(",")]

    riot = RiotClient()
    dd = DataDragonClient()
    pipeline = IngestionPipeline(riot, dd)

    try:
        summary = await pipeline.run(
            since=since,
            platforms=platform_list,
            max_players_per_platform=max_players,
            matches_per_player=matches_per_player,
            num_patches=num_patches,
        )
        typer.echo(f"champions: {summary['champions_loaded']} (patch {summary['champion_version']})")
        typer.echo(f"matches ingested: {summary['matches_ingested']} (total in db: {summary['total_matches_in_db']})")
        typer.echo(f"patch notes: {summary['patches_with_notes']}")
    finally:
        await riot.close()
