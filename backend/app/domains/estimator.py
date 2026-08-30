"""Cost estimation. No real calls; purely computed token/cost projections."""

# Simulated price per token (input+output blended), clearly a simulation constant.
PRICE_PER_TOKEN = 0.000002
SAFETY_MARGIN = 0.20  # 20%


def estimate_for_agents(agent_ids: list[str], agent_registry: dict) -> dict:
    per_agent = []
    total_min = total_prob = total_max = 0.0
    total_tokens = 0
    total_calls = 0
    for aid in agent_ids:
        contract = agent_registry.get(aid, {})
        tok = contract.get("token_limit", 1200)
        # min/probable/max token usage assumptions
        tok_min = int(tok * 0.4)
        tok_prob = int(tok * 0.65)
        tok_max = tok
        c_min = round(tok_min * PRICE_PER_TOKEN, 6)
        c_prob = round(tok_prob * PRICE_PER_TOKEN, 6)
        c_max = round(tok_max * PRICE_PER_TOKEN, 6)
        per_agent.append({
            "agent_id": aid,
            "agent_name": contract.get("name", aid),
            "tokens_estimated": tok_prob,
            "calls": 1,
            "cost_min": c_min, "cost_probable": c_prob, "cost_max": c_max,
        })
        total_min += c_min
        total_prob += c_prob
        total_max += c_max
        total_tokens += tok_prob
        total_calls += 1

    external_tools_cost = 0.0
    total_max_with_margin = round(total_max * (1 + SAFETY_MARGIN) + external_tools_cost, 6)
    return {
        "cost_min": round(total_min, 6),
        "cost_probable": round(total_prob, 6),
        "cost_max": round(total_max, 6),
        "approvable_cap": total_max_with_margin,
        "per_agent": per_agent,
        "tokens_estimated": total_tokens,
        "calls_estimated": total_calls,
        "external_tools_cost": external_tools_cost,
        "safety_margin": SAFETY_MARGIN,
        "currency": "USD",
        "mode": "SIMULAZIONE",
    }
