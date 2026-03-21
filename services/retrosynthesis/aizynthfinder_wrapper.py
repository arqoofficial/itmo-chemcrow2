"""AiZynthFinder wrapper for retrosynthesis analysis."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

from aizynthfinder.aizynthfinder import AiZynthFinder

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)


class AiZynthFinderWrapper:
    """Wrapper for AiZynthFinder to simplify retrosynthesis operations."""

    def __init__(self, config_path: Path) -> None:
        """Initialize AiZynthFinder with configuration.

        Args:
            config_path: Path to the AiZynthFinder YAML config file
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self.config_path = config_path
        self._finder: AiZynthFinder | None = None
        logger.info(f"AiZynthFinder initialized with config: {config_path}")

    @property
    def finder(self) -> AiZynthFinder:
        """Lazy-load AiZynthFinder instance."""
        if self._finder is None:
            self._finder = AiZynthFinder(configfile=str(self.config_path))
        return self._finder


    def run_tree_search(
        self,
        smiles: str,
        max_transforms: int = 12,
        time_limit: int = 10,
        iterations: int = 100,
        expansion_model: str = "uspto",
        stock: str = "zinc",
    ) -> dict[str, Any]:
        """Run retrosynthesis tree search for a given SMILES.

        Args:
            smiles: SMILES string of target molecule
            max_transforms: Maximum number of transforms (depth)
            time_limit: Time limit in seconds
            iterations: Number of iterations
            expansion_model: Name of expansion model to use
            stock: Name of stock to use

        Returns:
            Dictionary containing synthesis tree and statistics
        """
        # Reset finder for new search
        self._finder = AiZynthFinder(configfile=str(self.config_path))

        # Configure search parameters
        self.finder.target_smiles = smiles
        self.finder.config.max_transforms = max_transforms
        self.finder.config.time_limit = time_limit
        self.finder.config.iteration_limit = iterations

        # Set expansion strategy and stock
        self.finder.expansion_policy.select(expansion_model)
        self.finder.stock.select(stock)

        logger.info(
            f"Starting tree search for {smiles} with params: "
            f"max_transforms={max_transforms}, time_limit={time_limit}, "
            f"iterations={iterations}, expansion_model={expansion_model}, stock={stock}"
        )

        # Run the tree search
        self.finder.prepare_tree()
        self.finder.tree_search()
        self.finder.build_routes()

        # Get results
        stats = self.finder.extract_statistics()
        routes = self.finder.routes
        routes_dict = routes.dict_with_extra()
        stock_info = self.finder.stock_info()
        result: dict[str, Any] = {
            "smiles": smiles,
            "parameters": {
                "max_transforms": max_transforms,
                "time_limit": time_limit,
                "iterations": iterations,
                "expansion_model": expansion_model,
                "stock": stock,
            },
            "statistics": stats,
            "stock_info": stock_info,
            "routes": routes_dict,
        }

        logger.info(
            f"Tree search completed: solved={result['statistics']['is_solved']}, "
            f"routes={result['statistics']['number_of_solved_routes']}"
        )

        return result


    def get_available_models(self) -> dict[str, list[str]]:
        """Get available expansion models and stocks.

        Returns:
            Dictionary with available models and stocks
        """
        expansion_models = list(self.finder.expansion_policy.items)
        stocks = list(self.finder.stock.items)

        return {
            "expansion_models": expansion_models,
            "stocks": stocks,
        }


def _print_result(result: dict[str, Any]) -> None:
    """Pretty-print retrosynthesis result to the terminal."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    stats = result["statistics"]
    params = result["parameters"]

    solved = stats.get("is_solved", False)
    status = "[bold green]SOLVED[/]" if solved else "[bold red]NOT SOLVED[/]"

    console.print()
    console.print(
        Panel(
            f"[bold]{result['smiles']}[/]\n\nStatus: {status}",
            title="[cyan]Retrosynthesis Result[/]",
            border_style="cyan",
        )
    )

    param_table = Table(title="Search Parameters", show_header=False, border_style="dim")
    param_table.add_column("Parameter", style="bold")
    param_table.add_column("Value")
    for key, value in params.items():
        param_table.add_row(key.replace("_", " ").title(), str(value))
    console.print(param_table)

    stats_table = Table(title="Statistics", show_header=False, border_style="dim")
    stats_table.add_column("Metric", style="bold")
    stats_table.add_column("Value")
    for key, value in stats.items():
        label = key.replace("_", " ").title()
        if isinstance(value, bool):
            cell = "[green]Yes[/]" if value else "[red]No[/]"
        elif isinstance(value, float):
            cell = f"{value:.4f}"
        else:
            cell = str(value)
        stats_table.add_row(label, cell)
    console.print(stats_table)

    n_routes = stats.get("number_of_solved_routes", 0)
    if n_routes:
        console.print(f"\n[green]Found {n_routes} solved route(s).[/]")
    else:
        console.print("\n[yellow]No solved routes found.[/]")
    console.print()


def cli() -> dict[str, Any]:
    parser = argparse.ArgumentParser(
        description="Run retrosynthesis analysis via AiZynthFinder",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--smiles", type=str, required=True, help="target molecule SMILES")
    parser.add_argument("--max-transforms", type=int, default=12, help="max tree depth")
    parser.add_argument("--time-limit", type=int, default=10, help="time limit in seconds")
    parser.add_argument("--iterations", type=int, default=100, help="MCTS iterations")
    parser.add_argument("--expansion-model", type=str, default="uspto", help="expansion policy")
    parser.add_argument("--stock", type=str, default="zinc", help="stock database")
    parser.add_argument(
        "--json", action="store_true", help="output raw JSON instead of formatted table"
    )
    args = parser.parse_args()

    wrapper = AiZynthFinderWrapper(Path(os.getenv("AZF_CONFIG_PATH")))
    result = wrapper.run_tree_search(
        args.smiles,
        args.max_transforms,
        args.time_limit,
        args.iterations,
        args.expansion_model,
        args.stock,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_result(result)

    return result


if __name__ == "__main__":
    cli()
