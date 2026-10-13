import os

from bedrock_agentcore import BedrockAgentCoreApp
from langchain_core.messages import HumanMessage

from agent import agent

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict):
    prompt = payload.get("prompt") or payload.get("input")

    if not prompt:
        return {"error": "Provide a non-empty 'prompt' or 'input' field."}

    result = agent.invoke({
        "messages": [HumanMessage(content=prompt)]
    })

    answer = result["messages"][-1].content

    return {"response": answer}


if __name__ == "__main__":
    app.run()
