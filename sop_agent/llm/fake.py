from sop_agent.sop.extraction import TurnExtraction


class FakeLLM:
    """Scripted LLM for tests. A scripted extraction or reply that is an Exception is raised."""

    def __init__(self, extractions: list[TurnExtraction], replies=()):
        self._extractions = list(extractions)
        self._replies = list(replies)
        self.calls: list[dict] = []

    def extract(self, *, system: str, messages: list[dict]) -> TurnExtraction:
        self.calls.append({"role": "extract", "system": system, "messages": messages})
        if not self._extractions:
            return TurnExtraction()
        extraction = self._extractions.pop(0)
        if isinstance(extraction, Exception):
            raise extraction
        return extraction

    def phrase(self, *, system: str, messages: list[dict]) -> str:
        self.calls.append({"role": "phrase", "system": system, "messages": messages})
        if self._replies:
            reply = self._replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        content = messages[-1]["content"]  # echo the template, as phraser_user() lays it out
        return content.split("TEMPLATE:\n", 1)[-1].split("\n\nFACTS:", 1)[0]
