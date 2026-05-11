"""News & Sentiment agent — headlines, hot-trending tickers, rumor detection."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.tools.news_tools import search_news
from app.tools.market_tools import scan_hot_trends, scan_rumors

SYSTEM_PROMPT = """You are the News & Sentiment agent for FinCoach.

Tools:
- search_news(query, limit)  — recent finance headlines
- scan_hot_trends()          — what's trending NOW across CoinGecko, Yahoo, Google News
- scan_rumors()              — M&A whispers, insider moves, analyst actions, scored 1-10

Pick ONE tool that answers the user's question. For each item you cite:
- Quote the headline (max 15 words, in quotes)
- Include the source URL when available
- Tag sentiment: positive / neutral / negative

Never present rumors as confirmed news. Two short paragraphs max."""


_TOOLS = [search_news, scan_hot_trends, scan_rumors]
_agent = None


def _build_agent():
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=SYSTEM_PROMPT)


async def run(state: AgentState) -> AgentState:
    global _agent
    if _agent is None:
        _agent = _build_agent()
    result = await _agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
