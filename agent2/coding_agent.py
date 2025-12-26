from agents import ModelSettings
from agency_swarm import Agent, WebSearchTool
from openai.types.shared import Reasoning

code = Agent(
    name="CodingAgent",
    description="A gpt-5.1-based coding assistant template with no tools or instructions configured.",
    instructions="./instructions.md",
    model="gpt-5.2",
    
    model_settings=ModelSettings(
        reasoning=Reasoning(
            effort="medium",
            summary="auto",
        ),
    ),
)


