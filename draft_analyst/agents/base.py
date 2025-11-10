from abc import ABC, abstractmethod

from draft_analyst.domain.models import AgentOutput, DraftState
from draft_analyst.llm_client import LLMClient


class Agent(ABC):
    """Base class for draft agents. Only exists because the eval needs
    to swap between single-agent and multi-agent implementations."""

    def __init__(self, name: str, llm: LLMClient, model: str):
        self.name = name
        self.llm = llm
        self.model = model

    @abstractmethod
    def run(self, state: DraftState) -> AgentOutput:
        ...
