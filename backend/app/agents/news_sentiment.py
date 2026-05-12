"""News & Sentiment agent — headlines, hot-trending tickers, rumor detection."""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.llm import get_llm
from app.agents.state import AgentState
from app.agents._helpers import extract_tool_calls
from app.tools.news_tools import search_news
from app.tools.market_tools import scan_hot_trends, scan_rumors

SYSTEM_PROMPT_BASE = """You are the News & Sentiment agent for FinCoach.

Tools:
- search_news(query, limit)  — recent finance headlines
- scan_hot_trends()          — what''s trending NOW across CoinGecko, Yahoo, Google News
- scan_rumors()              — M&A whispers, insider moves, analyst actions, scored 1-10

Pick ONE tool that answers the user''s question. For each item you cite:
- Quote the headline (max 15 words, in quotes)
- Include the source URL when available
- Tag sentiment: positive / neutral / negative

Never present rumors as confirmed news. Two short paragraphs max."""

RISK_GUIDANCE = {
    "conservative": """
RISK PROFILE: Conservative (0-50 score)
NEWS FILTERING STRATEGY:
- Prioritize: Blue-chip company earnings, dividend announcements, regulatory updates
- Highlight: Stable industry news, dividend increases, credit rating upgrades
- De-emphasize: Crypto news, pre-revenue startups, high-volatility sector moves
- Rumor approach: Warn about M&A rumors but emphasize "unconfirmed whispers"
- Company focus: Fortune 500 / S&P 500 companies, government bonds
- Trends to avoid: Meme stocks, emerging cryptocurrencies, speculative SPACs

ANALYSIS PRIORITIES:
- Dividend sustainability and payout increases
- Company stability metrics (debt, cash flow)
- Regulatory & legal developments (positive for stability)""",
    "balanced": """
RISK PROFILE: Balanced (51-90 score)
NEWS FILTERING STRATEGY:
- Balance: Mix of blue-chip + growth company news
- Highlight: Earnings beats, sector rotations, tech innovations, analyst upgrades
- Include: Some M&A rumors (marked as "early signals"), IPO news, sector trends
- Crypto news: Include with context ("volatile alternative asset")
- Company focus: Mix of large-cap value + mid-cap growth
- Trends to monitor: Emerging sectors (fintech, AI), sector rotation signals

ANALYSIS PRIORITIES:
- Earnings trends and guidance changes
- Sector momentum shifts
- Technology and competitive advantages
- M&A and consolidation trends""",
    "aggressive": """
RISK PROFILE: Aggressive (91-125 score)
NEWS FILTERING STRATEGY:
- Focus: Growth companies, disruptive tech, emerging leaders, high-conviction bets
- Highlight: Pre-revenue startup funding rounds, crypto ecosystem growth, M&A rumors
- Include: Aggressive positioning on hot trends, emerging markets opportunities
- Rumor approach: Highlight early M&A whispers as "alpha opportunities"
- Company focus: Growth tech, biotech, small-cap movers, crypto ecosystem
- Trends to follow: AI boom, metaverse plays, emerging markets, crypto protocols

ANALYSIS PRIORITIES:
- Revenue growth acceleration
- Market share gains and disruption
- Early-stage signals (before mainstream coverage)
- Speculative opportunities (M&A, industry disruption, innovation cycles)""",
}


def _build_prompt(risk_profile: str = "balanced") -> str:
    """Build risk-aware system prompt based on user''s risk profile."""
    guidance = RISK_GUIDANCE.get(risk_profile, RISK_GUIDANCE["balanced"])
    return SYSTEM_PROMPT_BASE + "\n" + guidance


_TOOLS = [search_news, scan_hot_trends, scan_rumors]


def _build_agent(risk_profile: str = "balanced"):
    prompt = _build_prompt(risk_profile)
    return create_react_agent(get_llm(), tools=_TOOLS, prompt=prompt)


async def run(state: AgentState) -> AgentState:
    risk_profile = state.get("risk_profile", "balanced")
    agent = _build_agent(risk_profile)
    result = await agent.ainvoke({"messages": state.get("messages", [])})
    return {
        "messages": result["messages"][-1:],
        "citations": extract_tool_calls(result["messages"]),
    }
