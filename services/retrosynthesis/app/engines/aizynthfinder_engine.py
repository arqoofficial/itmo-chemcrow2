"""AiZynthFinder retrosynthesis engine."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import yaml
from aizynthfinder.aizynthfinder import AiZynthFinder

from app.engines.base import RetrosynthesisEngine

logger = logging.getLogger(__name__)


class AiZynthFinderEngine(RetrosynthesisEngine):
    """Multi-step retrosynthesis via AiZynthFinder tree search."""

    def __init__(self, config_path: Path) -> None:
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")
        self._config_path = self._ensure_valid_config(config_path)
        self._finder: AiZynthFinder | None = None
        logger.info("AiZynthFinderEngine created (config=%s)", self._config_path)

    @staticmethod
    def _ensure_valid_config(config_path: Path) -> Path:
        """Re-generate config with corrected paths if files are not found at the original paths.

        Handles the case when config.yml was generated on the host
        but the data is mounted at a different location in Docker.
        """
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        data_dir = config_path.parent
        needs_fix = False

        for _, paths in cfg.get("expansion", {}).items():
            for p in paths:
                if not Path(p).exists():
                    needs_fix = True
                    break

        for _, p in cfg.get("stock", {}).items():
            if not Path(p).exists():
                needs_fix = True

        if not needs_fix:
            return config_path

        logger.info("Config paths invalid — rebasing to %s", data_dir)
        fixed: dict[str, Any] = {}
        for section in ("expansion", "filter", "stock"):
            block = cfg.get(section, {})
            if not block:
                continue
            fixed[section] = {}
            for key, val in block.items():
                if isinstance(val, list):
                    fixed[section][key] = [
                        str(data_dir / Path(p).name) for p in val
                    ]
                else:
                    fixed[section][key] = str(data_dir / Path(val).name)

        tmp = Path(tempfile.gettempdir()) / "azf_config.yml"
        with open(tmp, "w") as f:
            yaml.dump(fixed, f, default_flow_style=False)
        logger.info("Wrote fixed config to %s", tmp)
        return tmp

    @property
    def name(self) -> str:
        return "aizynthfinder"

    @property
    def finder(self) -> AiZynthFinder:
        if self._finder is None:
            self._finder = AiZynthFinder(configfile=str(self._config_path))
        return self._finder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_multi_step(
        self,
        smiles: str,
        *,
        max_transforms: int = 12,
        time_limit: int = 10,
        iterations: int = 100,
        expansion_model: str = "uspto",
        stock: str = "zinc",
    ) -> dict[str, Any]:
        self._finder = AiZynthFinder(configfile=str(self._config_path))

        self.finder.target_smiles = smiles
        self.finder.config.max_transforms = max_transforms
        self.finder.config.time_limit = time_limit
        self.finder.config.iteration_limit = iterations

        self.finder.expansion_policy.select(expansion_model)
        self.finder.stock.select(stock)

        logger.info(
            "Tree search: %s (transforms=%d, time=%ds, iter=%d, model=%s, stock=%s)",
            smiles, max_transforms, time_limit, iterations, expansion_model, stock,
        )

        self.finder.prepare_tree()
        self.finder.tree_search()
        self.finder.build_routes()

        stats = self.finder.extract_statistics()
        routes_dict = self.finder.routes.dict_with_extra()
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
            "Done: solved=%s, routes=%s",
            result["statistics"].get("is_solved"),
            result["statistics"].get("number_of_solved_routes"),
        )
        return result

    def get_resources(self) -> dict[str, list[str]]:
        return {
            "expansion_models": list(self.finder.expansion_policy.items),
            "stocks": list(self.finder.stock.items),
        }
