from agents import ModelSettings
from agency_swarm import Agent, WebSearchTool
from openai.types.shared import Reasoning
from coding_agent.tools import apply_patch, shell_tool, OpenAIImageGenerationTool, update_plan

coding_agent = Agent(
    name="CodingAgent",
    description="A gpt-5.1-based coding assistant template with no tools or instructions configured.",
    instructions="./instructions.md",
    model="gpt-5.1-codex",
    
    model_settings=ModelSettings(
        reasoning=Reasoning(
            effort="medium",
            summary="auto",
        ),
    ),
)


