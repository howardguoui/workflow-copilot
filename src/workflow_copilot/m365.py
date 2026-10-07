"""Serve a workflow copilot through the Microsoft 365 Agents SDK.

`workflow-copilot serve "vault/GPU Sizing Assistant.md"` starts http://localhost:3978/api/messages, the endpoint
Microsoft 365 Agents Playground connects to locally (anonymous, no Azure account needed). The same app can be
registered as an Azure Bot to reach Teams and Microsoft 365 Copilot; that step needs an Azure subscription.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from aiohttp import web
from microsoft_agents.hosting.aiohttp import CloudAdapter, jwt_authorization_middleware, start_agent_process
from microsoft_agents.hosting.core import (
    AgentApplication,
    AgentAuthConfiguration,
    AnonymousTokenProvider,
    MemoryStorage,
    TurnContext,
    TurnState,
)
from microsoft_agents.hosting.core.authorization.connection_manager import ConnectionManager

from .agent import WorkflowCopilot

# Local and Agents Playground use: anonymous. For Teams / Microsoft 365 Copilot, register an Azure Bot and replace
# this with an MSAL connection manager (microsoft-agents-authentication-msal) configured from environment variables.
ANONYMOUS = AgentAuthConfiguration(anonymous_allowed=True)


def create_agent_app(compiled: dict, vault: str | Path, client_factory: Callable[[], object]):
    connections = ConnectionManager(lambda _cfg: AnonymousTokenProvider(), {"SERVICE_CONNECTION": ANONYMOUS})
    adapter = CloudAdapter(connection_manager=connections)
    agent_app = AgentApplication[TurnState](storage=MemoryStorage(), connection_manager=connections)
    sessions: dict[str, WorkflowCopilot] = {}
    wf = compiled["workflow"]

    @agent_app.conversation_update("membersAdded")
    async def on_members_added(context: TurnContext, _state: TurnState):
        example = wf["examples"][0] if wf["examples"] else "ask me anything"
        await context.send_activity(f"Hi, I'm {wf['name']}. {wf['description']} Try: {example}")

    @agent_app.activity("message")
    async def on_message(context: TurnContext, _state: TurnState):
        conversation = context.activity.conversation.id if context.activity.conversation else "default"
        if conversation not in sessions:
            sessions[conversation] = WorkflowCopilot(compiled, vault, client_factory())
        reply = await sessions[conversation].ask(context.activity.text or "")
        await context.send_activity(reply)

    return agent_app, adapter, sessions


def create_web_app(compiled: dict, vault: str | Path, client_factory: Callable[[], object]) -> web.Application:
    agent_app, adapter, sessions = create_agent_app(compiled, vault, client_factory)

    async def messages(request: web.Request) -> web.StreamResponse:
        return await start_agent_process(request, agent_app, adapter)

    app = web.Application(middlewares=[jwt_authorization_middleware])
    app["agent_configuration"] = ANONYMOUS
    app.router.add_post("/api/messages", messages)
    app["agent_app"], app["adapter"], app["sessions"] = agent_app, adapter, sessions
    return app
