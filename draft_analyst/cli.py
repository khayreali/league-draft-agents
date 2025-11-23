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


@app.command()
def index_patches():
    """Chunk and embed patch notes into ChromaDB."""
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_index_patches())


async def _index_patches():
    from draft_analyst.data.patch_index import PatchIndex
    from draft_analyst.data.patch_scraper import PatchNotesScraper

    scraper = PatchNotesScraper()

    # load from DB cache first, then local files
    notes = scraper.get_all_cached()
    if not notes:
        typer.echo("no cached notes, loading from local YAML files...")
        patches = ["16.7", "16.6", "16.5"]
        notes = await scraper.fetch_recent(patches)

    if not notes:
        typer.echo("no patch notes found to index")
        return

    typer.echo(f"indexing {len(notes)} patch notes...")
    index = PatchIndex()
    n = index.index_notes(notes)
    typer.echo(f"done — {n} chunks indexed ({index.count()} total in collection)")


@app.command()
def recommend(
    role: str = typer.Option(..., help="Your role: top, jungle, mid, bot, support"),
    patch: str = typer.Option(..., help="Current patch, e.g. 16.7"),
    picks: str = typer.Option("", help="Your team's picks, comma-separated"),
    bans: str = typer.Option("", help="All bans, comma-separated"),
    enemy: str = typer.Option("", help="Enemy picks, comma-separated"),
    rank: str = typer.Option("emerald+", help="Rank filter for solo queue stats"),
    baseline: bool = typer.Option(False, help="Run single-agent baseline instead"),
):
    """Get draft recommendations for the given state."""
    logging.basicConfig(level=logging.INFO)
    from rich.console import Console
    from rich.table import Table

    from draft_analyst.agents.context import build_tool_executor
    from draft_analyst.domain.models import DraftState
    from draft_analyst.llm_client import get_llm_client
    from draft_analyst.config import DEFAULT_AGENT_MODEL

    pick_list = [p.strip() for p in picks.split(",") if p.strip()]
    ban_list = [b.strip() for b in bans.split(",") if b.strip()]
    enemy_list = [e.strip() for e in enemy.split(",") if e.strip()]

    state = DraftState(
        patch=patch,
        user_team_picks=pick_list,
        enemy_team_picks=enemy_list,
        bans=ban_list,
        user_role=role,
        rank=rank,
    )

    tool_executor = build_tool_executor(patch)
    llm = get_llm_client()

    if baseline:
        from draft_analyst.agents.baseline import SingleAgentBaseline
        agent = SingleAgentBaseline(llm, DEFAULT_AGENT_MODEL, tool_executor)
        typer.echo("running single-agent baseline...")
    else:
        from draft_analyst.agents.coordinator import LangGraphCoordinator
        agent = LangGraphCoordinator(llm, DEFAULT_AGENT_MODEL, tool_executor)
        typer.echo("running multi-agent system...")

    output = agent.run(state)

    # print results
    console = Console()
    table = Table(title=f"Draft Recommendations ({output.agent_name})")
    table.add_column("Rank", style="bold")
    table.add_column("Champion", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Reasoning")

    for i, rec in enumerate(output.recommendations[:5], 1):
        table.add_row(str(i), rec.champion, f"{rec.score:.2f}", rec.reasoning)

    console.print(table)
    typer.echo(f"\ntool calls: {output.tool_calls_made}")
