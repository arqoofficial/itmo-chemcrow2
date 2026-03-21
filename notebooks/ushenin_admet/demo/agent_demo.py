from __future__ import annotations

import argparse
import json
import os
import uuid
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import BaseMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

try:
    from langfuse import get_client
    from langfuse.langchain import CallbackHandler
except Exception:
    get_client = None
    CallbackHandler = None


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "Openai/Gpt-oss-120b")
ADMET_BASE_URL = os.getenv("ADMET_BASE_URL", "http://127.0.0.1:8144").rstrip("/")


@tool
def SMILES_to_ADMET(smiles: str) -> Dict[str, Any]:
    """Convert one single-molecule SMILES string into RDKit descriptors and heuristic ADMET proxy predictions."""
    s = (smiles or "").strip()
    if not s:
        return {
            "success": False,
            "error": {
                "type": "validation_error",
                "message": "SMILES is empty.",
            },
            "input": {"smiles": smiles},
            "result": None,
        }

    payload = {
        "smiles": s,
        "allow_explicit_h": False,
        "max_heavy_atoms": 200,
        "include_descriptors": True,
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            response = client.post(f"{ADMET_BASE_URL}/v1/admet", json=payload)

        try:
            data = response.json()
        except ValueError:
            data = None

        if response.is_success:
            if isinstance(data, dict):
                data.setdefault("success", True)
                return data

            return {
                "success": False,
                "error": {
                    "type": "invalid_response",
                    "message": "ADMET service returned non-JSON success response.",
                    "status_code": response.status_code,
                },
                "input": {"smiles": s},
                "result": None,
            }

        return {
            "success": False,
            "error": {
                "type": "http_error",
                "message": (
                    data.get("error", {}).get("message")
                    if isinstance(data, dict)
                    else f"ADMET service returned HTTP {response.status_code}."
                ),
                "status_code": response.status_code,
            },
            "input": {"smiles": s},
            "service_response": data,
            "result": None,
        }

    except httpx.TimeoutException as e:
        return {
            "success": False,
            "error": {
                "type": "timeout",
                "message": "ADMET service request timed out.",
                "details": str(e),
            },
            "input": {"smiles": s},
            "result": None,
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "error": {
                "type": "network_error",
                "message": "Could not reach ADMET service.",
                "details": str(e),
            },
            "input": {"smiles": s},
            "result": None,
        }
    except Exception as e:
        return {
            "success": False,
            "error": {
                "type": "unexpected_error",
                "message": "Unexpected tool failure.",
                "details": str(e),
            },
            "input": {"smiles": s},
            "result": None,
        }


def _collect_callbacks(user_prompt: str) -> List[Any]:
    has_langfuse = all(
        os.getenv(name)
        for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
    )
    if not has_langfuse or CallbackHandler is None:
        return []

    session_id = os.getenv("LANGFUSE_SESSION_ID", f"admet-demo-{uuid.uuid4().hex[:12]}")
    user_id = os.getenv("LANGFUSE_USER_ID", "local-cli-user")

    handler = CallbackHandler(
        trace_context={
            "name": "admet-agent-cli",
            "session_id": session_id,
            "user_id": user_id,
            "metadata": {
                "app": "admet-microservice-demo",
                "model": OPENAI_MODEL,
                "admet_base_url": ADMET_BASE_URL,
                "prompt_preview": user_prompt[:200],
            },
            "tags": ["admet", "langchain", "cli-demo"],
        }
    )
    return [handler]


def _pretty_last_message(result: Dict[str, Any]) -> str:
    messages: List[BaseMessage] = result.get("messages", [])
    if not messages:
        return json.dumps(result, indent=2, ensure_ascii=False)

    last = messages[-1]
    content = getattr(last, "content", last)
    if isinstance(content, str):
        return content
    return json.dumps(content, indent=2, ensure_ascii=False, default=str)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a LangChain + Langfuse demo against the ADMET microservice."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default=(
            "Estimate ADMET for aspirin with SMILES CC(=O)Oc1ccccc1C(=O)O. "
            "Explain the main absorption and toxicity risks briefly."
        ),
    )
    args = parser.parse_args()

    llm = ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_API_BASE,
        temperature=0,
    )

    agent = create_agent(
        model=llm,
        tools=[SMILES_to_ADMET],
        system_prompt=(
            "You are an ADMET assistant. "
            "When a user gives a SMILES string or asks for ADMET estimation, call the SMILES_to_ADMET tool. "
            "Be explicit that the service returns descriptor-based heuristic proxy predictions, not experimental truth."
        ),
    )

    callbacks = _collect_callbacks(args.prompt)

    # SANITY CHECK, LLM WORK
    resp = llm.invoke("Reply with exactly: hello")
    print(resp)
    print("content:", repr(resp.content))

    # SANITY CHECK, TOOL CALL
    model_with_tools = llm.bind_tools([SMILES_to_ADMET])
    resp = model_with_tools.invoke(
        "Estimate ADMET for aspirin with SMILES CC(=O)Oc1ccccc1C(=O)O. "
        "You must call the SMILES_to_ADMET tool."
    )
    print("content:", repr(resp.content))
    print("tool_calls:", resp.tool_calls)
    print("full:", resp)

    result = agent.invoke(
        {"messages": [{"role": "user", "content": args.prompt}]},
        config={
            "callbacks": callbacks,
            "run_name": "admet_agent_run",
            "metadata": {
                "component": "cli-demo",
                "openai_model": OPENAI_MODEL,
            },
            "tags": ["admet", "demo"],
        },
    )

    print("\n=== Final agent answer ===\n")
    print(_pretty_last_message(result))

    if get_client is not None:
        try:
            get_client().flush()
        except Exception:
            pass


if __name__ == "__main__":
    main()