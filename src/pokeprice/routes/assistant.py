"""The management chat routes (assistant.py): state, questions, forgetting, flags.

``create_app`` imports this module at start-up, not at import, like the
assistant modules it reads.
"""

import json

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..agent import AgentError
from ..assistant import MAX_QUESTION, Refused
from ..assistant_signals import MAX_NOTE
from .context import AppContext


class AssistantQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    conversation_id: str | None = Field(default=None, max_length=40, pattern=r"^[a-f0-9-]{36}$")
    # V1.1, contexte de la question (fiche 0036) : liste blanche appliquée par
    # assistant_context.clean dans Assistant.prepare ; le superflu est écarté.
    context: dict | None = None


# Chantier V1.1 « capture des échecs » (decision 0038): the 👎 under an
# answer, with a free note, kept beside it for the bench.
class AssistantFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=MAX_NOTE)


def register_assistant(app, ctx: AppContext):
    """Register the assistant routes on ``app``, where ``create_app`` had them."""
    store = ctx.store
    staff = ctx.auth.staff
    assistant = ctx.assistant

    def assistant_refused(error):
        if isinstance(error, AgentError):
            raise HTTPException(error.status, str(error))
        headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
        raise HTTPException(error.status, str(error), headers=headers)

    @app.get("/api/assistant")
    def assistant_state(user=Depends(staff)):
        try:
            from ..assistant import principal

            principal(store, user["id"])
        except AgentError as error:
            assistant_refused(error)
        return assistant.state(user["id"])

    @app.post("/api/assistant")
    def assistant_ask(values: AssistantQuestion, user=Depends(staff)):
        try:
            question = assistant.prepare(user["id"], values.question, values.conversation_id,
                                         values.context)
        except (Refused, AgentError) as error:
            assistant_refused(error)

        def events():
            for kind, data in assistant.run(question):
                yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/assistant/conversations")
    def assistant_forget_all(user=Depends(staff)):
        return assistant.journal.delete(user["id"])

    @app.delete("/api/assistant/conversations/{conversation_id}")
    def assistant_forget(conversation_id: str, user=Depends(staff)):
        return assistant.journal.delete(user["id"], conversation_id)

    @app.post("/api/assistant/answers/{message_id}/flag")
    def assistant_flag(message_id: int, values: AssistantFlag, user=Depends(staff)):
        try:
            return assistant.journal.thumbs_down(user["id"], message_id, values.note)
        except KeyError as error:
            raise HTTPException(404, str(error.args[0])) from None
