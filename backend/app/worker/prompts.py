"""Background message templates for the async tool pipeline.

Only two templates: S2 success and papers ingested.
Failures are communicated via background_error SSE events — never as background messages.
"""

S2_RESULTS = """\
[Background: Literature Search Results]
Your earlier search for "{query}" found {n} paper(s):

{papers_formatted}

Please analyze these results and provide relevant information to the conversation."""

PAPERS_INGESTED = """\
[Background: New Papers Available]
The following articles from your earlier search have been parsed and added to the knowledge base:

{papers_formatted}

Please search the RAG corpus for detailed information from these documents relevant to this conversation."""
