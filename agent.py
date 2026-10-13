
import os

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, MessagesState, StateGraph


REGION = "ap-south-2"

# Replace this with the inference profile ID or ARN
# available to your AWS account for Claude Haiku 4.5.
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]


llm = ChatBedrockConverse(
    model=MODEL_ID,
    region_name=REGION,
    temperature=0,
)


def call_model(state: MessagesState):
    response = llm.invoke(state["messages"])
    return {"messages": [response]}


builder = StateGraph(MessagesState)

builder.add_node("assistant", call_model)
builder.add_edge(START, "assistant")
builder.add_edge("assistant", END)

agent = builder.compile()


if __name__ == "__main__":
    question = input("You: ").strip()

    if not question:
        raise SystemExit("Please enter a question.")

    result = agent.invoke({
        "messages": [HumanMessage(content=question)]
    })

    print("\nAgent:")
    print(result["messages"][-1].content)
