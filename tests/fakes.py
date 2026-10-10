"""A scripted chat model: replays prepared AI messages, supports tool calls and token streaming."""
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


class ScriptedChatModel(BaseChatModel):
    script: list[AIMessage]
    cursor: int = 0
    seen: list = Field(default_factory=list)  # the messages the model received on every call

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _next(self, messages) -> AIMessage:
        self.seen.append(list(messages))
        message = self.script[self.cursor]
        self.cursor += 1
        return message

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._next(messages)
        if message.tool_calls:
            chunks = [{"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                      for i, c in enumerate(message.tool_calls)]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
        else:
            for word in re.findall(r"\S+\s*", message.content):
                yield ChatGenerationChunk(message=AIMessageChunk(content=word))
