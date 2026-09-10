from intelligence.state import IntelligenceState

def more_tasks(state: IntelligenceState) -> str:
    checklist = state.get("checklist") or []
    for task in checklist:
        if task.get("status") == "pending":
            return "continue"
    return "complete"
