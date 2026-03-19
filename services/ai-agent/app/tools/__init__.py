from __future__ import annotations

from langchain.tools import BaseTool

from app.tools.literature_search import literature_search
from app.tools.property_prediction import predict_properties
from app.tools.retrosynthesis import retrosynthesis

ALL_TOOLS: list[BaseTool] = [
    predict_properties,
    retrosynthesis,
    literature_search,
]
