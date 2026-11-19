"""The management assistant's brief, V0 (todo.py)."""

from fastapi import Depends

from .context import AppContext


def register_todo(app, ctx: AppContext):
    """Register the brief of the management assistant, where ``create_app`` had them."""
    from ..todo import default_since, parse_since

    todo = ctx.todo
    editor = ctx.auth.editor

    @app.get("/api/todo")
    def todo_index(since: str = "", user=Depends(editor)):
        try:
            moment = parse_since(since) if since else default_since()
        except ValueError:
            raise ValueError("Date invalide : utilisez AAAA-MM-JJ.") from None
        return todo.brief(moment)
