from agency_swarm.tools import BaseTool
from pydantic import BaseModel, Field, field_validator
from typing import List, Literal


class PlanStep(BaseModel):
    """
    A single step in the plan with a description and status.
    """
    description: str = Field(
        ...,
        description="A concise 1-sentence description of the step (5-7 words recommended)."
    )
    status: Literal["pending", "in_progress", "completed"] = Field(
        ...,
        description="The current status of this step: 'pending', 'in_progress', or 'completed'."
    )


class UpdatePlan(BaseTool):
    """
    Create or update a step-by-step plan for the current task.
    
    Use this tool to:
    - Create a new plan with 5-7 short steps
    - Mark completed steps as 'completed' and move to the next step
    - Keep track of progress through a multi-step task
    
    Rules:
    - Each step should be 1 sentence (5-7 words each)
    - There should always be exactly one 'in_progress' step until all steps are done
    - You can mark multiple steps as 'completed' in a single call
    - When all steps are complete, mark all as 'completed'
    """
    
    steps: List[PlanStep] = Field(
        ...,
        description="List of plan steps with their current status.",
        min_length=1
    )
    
    @field_validator('steps')
    @classmethod
    def validate_in_progress_count(cls, steps: List[PlanStep]) -> List[PlanStep]:
        """
        Validate that there's exactly one 'in_progress' step, unless all steps are completed.
        """
        in_progress_count = sum(1 for step in steps if step.status == "in_progress")
        completed_count = sum(1 for step in steps if step.status == "completed")
        
        # If all steps are completed, that's valid
        if completed_count == len(steps):
            return steps
        
        # Otherwise, there must be exactly one in_progress step
        if in_progress_count != 1:
            raise ValueError(
                f"There must be exactly one 'in_progress' step (found {in_progress_count}). "
                "Either mark one step as 'in_progress' or mark all steps as 'completed'."
            )
        
        return steps

    def run(self):
        """
        Store the plan in agency context and return a formatted summary.
        """
        # Store the plan in agency context
        plan_data = [step.model_dump() for step in self.steps]
        if self.context:
            self.context.set("current_plan", plan_data)
        
        # Calculate progress statistics
        total = len(self.steps)
        completed = sum(1 for step in self.steps if step.status == "completed")
        in_progress_step = next(
            (i + 1 for i, step in enumerate(self.steps) if step.status == "in_progress"),
            None
        )
        
        # Format the plan for display
        result = ["📋 Current Plan:", ""]
        
        for i, step in enumerate(self.steps, 1):
            status_icon = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅"
            }[step.status]
            
            result.append(f"{status_icon} Step {i}: {step.description} [{step.status}]")
        
        result.append("")
        result.append(f"Progress: {completed}/{total} steps completed")
        
        if completed == total:
            result.append("🎉 All steps completed!")
        elif in_progress_step:
            result.append(f"Currently working on: Step {in_progress_step}")
        
        return "\n".join(result)


if __name__ == "__main__":
    # Test case 1: Create a new plan
    print("Test 1: Creating a new plan")
    tool = UpdatePlan(steps=[
        PlanStep(description="Read project structure", status="completed"),
        PlanStep(description="Create tool file", status="in_progress"),
        PlanStep(description="Add tool to agent", status="pending"),
        PlanStep(description="Test the tool", status="pending"),
    ])
    print(tool.run())
    print("\n" + "="*50 + "\n")
    
    # Test case 2: Update plan with progress
    print("Test 2: Marking more steps as completed")
    tool = UpdatePlan(steps=[
        PlanStep(description="Read project structure", status="completed"),
        PlanStep(description="Create tool file", status="completed"),
        PlanStep(description="Add tool to agent", status="in_progress"),
        PlanStep(description="Test the tool", status="pending"),
    ])
    print(tool.run())
    print("\n" + "="*50 + "\n")
    
    # Test case 3: All steps completed
    print("Test 3: All steps completed")
    tool = UpdatePlan(steps=[
        PlanStep(description="Read project structure", status="completed"),
        PlanStep(description="Create tool file", status="completed"),
        PlanStep(description="Add tool to agent", status="completed"),
        PlanStep(description="Test the tool", status="completed"),
    ])
    print(tool.run())
    print("\n" + "="*50 + "\n")
    
    # Test case 4: Invalid - no in_progress step
    print("Test 4: Invalid - no in_progress step (should fail)")
    try:
        tool = UpdatePlan(steps=[
            PlanStep(description="Read project structure", status="completed"),
            PlanStep(description="Create tool file", status="pending"),
            PlanStep(description="Add tool to agent", status="pending"),
        ])
        print(tool.run())
    except ValueError as e:
        print(f"✓ Validation error as expected: {e}")
    print("\n" + "="*50 + "\n")
    
    # Test case 5: Invalid - multiple in_progress steps
    print("Test 5: Invalid - multiple in_progress steps (should fail)")
    try:
        tool = UpdatePlan(steps=[
            PlanStep(description="Read project structure", status="in_progress"),
            PlanStep(description="Create tool file", status="in_progress"),
            PlanStep(description="Add tool to agent", status="pending"),
        ])
        print(tool.run())
    except ValueError as e:
        print(f"✓ Validation error as expected: {e}")

