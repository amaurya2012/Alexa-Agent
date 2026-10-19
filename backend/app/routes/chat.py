from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agent import Agent
from app.deps import get_agent, require_api_key
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("/chat", response_model=ChatResponse, summary="Send a natural-language request to the agent")
async def chat(payload: ChatRequest, agent: Agent = Depends(get_agent)) -> ChatResponse:
    result = await agent.handle_message(payload.message)
    return ChatResponse(response=result.response, events=result.events)
