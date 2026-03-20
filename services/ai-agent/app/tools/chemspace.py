"""Molecule pricing tool via ChemSpace API.

Optional — only active when CHEMSPACE_API_KEY is set.
Ported from chemcrow v1.
"""
from __future__ import annotations

import logging

import molbloom
import pandas as pd
import requests
from langchain.tools import tool

logger = logging.getLogger(__name__)


class _ChemSpaceClient:
    """Thin wrapper around the ChemSpace REST API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._renew_token()

    def _renew_token(self):
        resp = requests.get(
            url="https://api.chem-space.com/auth/token",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        self.token = resp.json()["access_token"]

    def _request(self, query: str, request_type: str, count: int, categories: str):
        def _do():
            return requests.post(
                f"https://api.chem-space.com/v3/search/{request_type}"
                f"?count={count}&page=1&categories={categories}",
                headers={
                    "Accept": "application/json; version=3.1",
                    "Authorization": f"Bearer {self.token}",
                },
                data={"SMILES": query},
            ).json()

        data = _do()
        if data.get("message") == "Your request was made with invalid credentials.":
            self._renew_token()
            data = _do()
        return data

    def buy_mol(self, smiles: str) -> str:
        try:
            purchasable = molbloom.buy(smiles, canonicalize=True)
        except Exception:
            purchasable = False

        data = self._request(smiles, "exact", 1, "CSMB,CSSB")
        try:
            if data["count"] == 0:
                if purchasable:
                    return "Compound is purchasable, but price is unknown."
                return "Compound is not purchasable."
        except KeyError:
            return "Invalid query, try something else."

        dfs = []
        for item in data["items"]:
            dfs_tmp = []
            item_smiles = item["smiles"]
            for off in item["offers"]:
                df_tmp = pd.DataFrame(off["prices"])
                df_tmp["vendorName"] = off["vendorName"]
                df_tmp["time"] = off["shipsWithin"]
                df_tmp["purity"] = off["purity"]
                dfs_tmp.append(df_tmp)
            df_this = pd.concat(dfs_tmp)
            df_this["smiles"] = item_smiles
            dfs.append(df_this)

        df = pd.concat(dfs).reset_index(drop=True)
        df["quantity"] = df["pack"].astype(str) + df["uom"]
        df["time"] = df["time"].astype(str) + " days"
        df = df.drop(columns=["pack", "uom"])
        df = df[df["priceUsd"].astype(str).str.isnumeric()]

        cheapest = df.iloc[df["priceUsd"].astype(float).idxmin()]
        return (
            f"{cheapest['quantity']} of this molecule cost "
            f"{cheapest['priceUsd']} USD and can be purchased at "
            f"{cheapest['vendorName']}."
        )


@tool
def get_molecule_price(query: str) -> str:
    """Get the cheapest available price of a molecule.

    Args:
        query: A SMILES string or molecule name.
    """
    from app.config import settings

    if not settings.CHEMSPACE_API_KEY:
        return "No Chemspace API key found. This tool may not be used without a Chemspace API key."
    try:
        client = _ChemSpaceClient(settings.CHEMSPACE_API_KEY)
        return client.buy_mol(query)
    except Exception as e:
        return str(e)
