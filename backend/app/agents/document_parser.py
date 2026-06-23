"""Document Parser agent — retrieval-augmented Q&A over uploaded documents.

When the user uploads a PDF or image, the document_processor service extracts
text (including labels and numbers read off chart screenshots) and embeds the
chunks into the ``document_chunks`` ChromaDB collection.

This agent is invoked by the strategist whenever a question may be answered
from those uploaded documents. It is a ReAct agent with two tools:

* ``search_documents(query, k)`` — semantic retrieval of relevant chunks.
* ``list_uploaded_documents()``  — enumerate indexed files (for disambiguation).

The agent never relies on the document content being inlined into chat
history. Each turn it re-queries the index, so follow-up questions about a
document that was attached many turns ago still work.
"""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents._helpers import build_findings, extract_tool_calls, latest_human_turn
from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.tools.document_tools import list_uploaded_documents, search_documents

SYSTEM_PROMPT = """You are the Document Analyst for FinCoach.

Your responsibility: answer questions about documents the user has uploaded
(PDFs, images, statements, trading notes). You DO NOT rely on chat history
containing the document — every turn, you re-query the document index for
the passages relevant to the current question.

Tools available:
  search_documents(query, k)    — semantic search over indexed document chunks.
                                  Returns [{text, filename, chunk_index, similarity}].
  list_uploaded_documents()     — list currently indexed files (use only when
                                  the user asks what they have uploaded, or
                                  when disambiguating between multiple files).

Operating procedure:
  1. Read the user's current question. Extract the salient subject
     (ticker, asset name, position concept like "entry / TP / SL", invoice
     line item, etc.).
  2. Call `search_documents` with a focused query. If the user asks about a
     specific asset, include the asset symbol in the query
     (e.g. "SOL entry take profit stop loss"). If the question is general,
     pass the user's question verbatim.
  3. If results are empty or all similarity scores are below 0.5, call
     `search_documents` ONCE more with a reformulated query (synonyms,
     translation, broader terms). Do not loop further.
  4. If results are still empty, state plainly that the uploaded documents
     do not contain information on this subject. Do NOT invent an answer.
  5. When you have passages, ground your answer in them. Quote the most
     relevant numbers/phrases verbatim — never paraphrase a price level.
     Always cite the source filename.

Answer style:
  - Match the user's language (Turkish question → Turkish answer).
  - Be concise: 1-3 short paragraphs, or a bullet list of levels.
  - For trade setups, structure the answer as:
        Asset: <ticker>
        Direction: long | short | unclear
        Entry: <number or "not specified">
        Take-profit: <number(s)>
        Stop-loss: <number>
        Source: <filename>
  - Never fabricate numbers. If a level is not stated in the retrieved
    passages, say so.
  - Do not give financial advice. You report what the document says.

Hard rules:
  - One call to `search_documents` is usually enough. Two is the maximum.
  - Never call `list_uploaded_documents` unless the user asks "what files
    have I uploaded" or retrieval failed and you need to confirm there is
    anything indexed at all.
  - If retrieval returns zero passages, the answer MUST acknowledge that
    no matching content was found in the uploaded documents.
"""


_agent = None


def _build_agent():
    return create_react_agent(
        get_llm(),
        tools=[search_documents, list_uploaded_documents],
        prompt=SYSTEM_PROMPT,
    )


async def run(state: AgentState) -> AgentState:
    """Entry point invoked by the supervisor graph."""
    global _agent
    if _agent is None:
        _agent = _build_agent()

    result = await _agent.ainvoke(
        {"messages": latest_human_turn(state.get("messages", []))}
    )
    msgs = result["messages"]
    return {
        "messages": msgs[-1:],
        "citations": extract_tool_calls(msgs),
        "findings": {"document_parser": build_findings("document_parser", msgs)},
        "agents_consulted": ["document_parser"],
    }
