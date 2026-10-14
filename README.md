import pypandoc, os, textwrap
readme = r'''# Deploy a LangGraph Agent to Amazon Bedrock AgentCore Runtime

A practical, end-to-end guide for packaging a Python/LangGraph agent in Docker, storing the image in Amazon Elastic Container Registry (Amazon ECR), deploying it to Amazon Bedrock AgentCore Runtime, and invoking it.

> **Security and sharing note:** This README intentionally uses placeholders for AWS account IDs, ARNs, repository names, runtime IDs, and model configuration. Do not publish access keys, secret keys, session tokens, `.env` files, private endpoints, or unredacted logs. Replace every `<PLACEHOLDER>` locally with values from your own AWS account. Never commit credentials to source control.

## Table of contents

1. [What you will build](#1-what-you-will-build)
2. [Architecture and request flow](#2-architecture-and-request-flow)
3. [Prerequisites](#3-prerequisites)
4. [Recommended project structure](#4-recommended-project-structure)
5. [Step 1: Create the Python environment](#5-step-1-create-the-python-environment)
6. [Step 2: Build the LangGraph agent](#6-step-2-build-the-langgraph-agent)
7. [Step 3: Add the AgentCore entry point](#7-step-3-add-the-agentcore-entry-point)
8. [Step 4: Define dependencies](#8-step-4-define-dependencies)
9. [Step 5: Build the Docker image](#9-step-5-build-the-docker-image)
10. [Step 6: Create and push to ECR](#10-step-6-create-and-push-to-ecr)
11. [Step 7: Configure IAM roles and permissions](#11-step-7-configure-iam-roles-and-permissions)
12. [Step 8: Configure the AgentCore runtime](#12-step-8-configure-the-agentcore-runtime)
13. [Step 9: Create and verify the runtime](#13-step-9-create-and-verify-the-runtime)
14. [Step 10: Invoke and test the deployed agent](#14-step-10-invoke-and-test-the-deployed-agent)
15. [What the important files do](#15-what-the-important-files-do)
16. [Troubleshooting](#16-troubleshooting)
17. [Security checklist](#17-security-checklist)
18. [Updating and cleaning up](#18-updating-and-cleaning-up)

---

## 1. What you will build

The finished system contains:

- **Python + LangGraph** to define the agent workflow.
- **LangChain AWS integration** to call a model hosted by Amazon Bedrock.
- **Bedrock AgentCore SDK** to expose the application as an AgentCore runtime entry point.
- **Docker** to package code and Python dependencies into a reproducible image.
- **Amazon ECR** to store that image.
- **Amazon Bedrock AgentCore Runtime** to run the container and expose an invocation API.
- **IAM** to control who can deploy/invoke the runtime and which AWS services the runtime can access.

A successful deployment has two separate checks:

1. The runtime's lifecycle status becomes `READY`.
2. An actual invocation returns a successful HTTP status and a response from the agent.

`READY` alone is not a substitute for an end-to-end invocation test.

## 2. Architecture and request flow

```text
DEVELOPMENT / DEPLOYMENT
------------------------
Developer workstation
  ├── agent.py
  ├── runtime.py
  ├── Requirement.txt
  └── Dockerfile
        |
        | docker build
        v
   Local Docker image
        |
        | docker push (authenticated to ECR)
        v
   Amazon ECR repository
        |
        | AgentCore pulls image using execution role permissions
        v
   Amazon Bedrock AgentCore Runtime
        |
        | InvokeAgentRuntime API
        v

RUNTIME REQUEST / MODEL CALL
----------------------------
Caller (AWS CLI, backend, or application)
        |
        | JSON payload, e.g. {"prompt": "..."}
        v
AgentCore runtime endpoint
        |
        v
runtime.py: @app.entrypoint handler
        |
        v
agent.py: compiled LangGraph
        |
        v
LangChain AWS chat-model integration
        |
        | authenticated using runtime execution-role credentials
        v
Amazon Bedrock model / inference profile
        |
        v
Generated answer -> runtime response -> caller
```

### Three connections that are easy to confuse

1. **Image upload:** Docker on the developer workstation authenticates to ECR and pushes the image.
2. **Image pull and model access:** AgentCore uses its execution role to retrieve the image and the application uses that role's credentials to call Bedrock.
3. **Deployment and invocation:** The local AWS CLI uses the developer's AWS identity. That identity needs permission to create/read/invoke the runtime and to pass the execution role where required.

The developer identity and the runtime execution role are different identities and should have different, least-privilege permissions.

## 3. Prerequisites

Install and configure:

- Python 3.12.
- Docker Desktop or another Docker engine that supports building Linux images.
- AWS CLI v2.
- An AWS account with access to Amazon ECR, Bedrock, and AgentCore in your chosen region.
- A model or inference profile enabled for your account and permitted for the runtime execution role.
- IAM permissions to create/configure the runtime, pass the execution role, and invoke the deployed runtime.

Check tools:

```powershell
python --version
docker --version
aws --version
aws sts get-caller-identity
```

**Why check identity?** `aws sts get-caller-identity` confirms which AWS identity the CLI is using. Before deploying, verify the account and identity are the intended ones. Do not publish the full output if it reveals account or identity details.

Configure credentials using an approved method, such as an AWS CLI profile, AWS IAM Identity Center, or your organization's credential provider. Avoid hardcoding access keys in Python, Dockerfiles, README files, or source control.

Set these values for your own environment. They are placeholders, not real values:

```powershell
$env:AWS_REGION = "<AWS_REGION>"
$env:AWS_ACCOUNT_ID = "<12_DIGIT_ACCOUNT_ID>"
$env:ECR_REPOSITORY = "<ECR_REPOSITORY_NAME>"
$env:AGENT_RUNTIME_NAME = "<RUNTIME_NAME>"
$env:EXECUTION_ROLE_ARN = "<EXECUTION_ROLE_ARN>"
$env:BEDROCK_MODEL_ID = "<MODEL_OR_INFERENCE_PROFILE_ID>"
```

For the commands below, use a region where the required AgentCore features and selected Bedrock model/profile are available.

## 4. Recommended project structure

```text
langgraph-agent/
├── agent.py                 # LangGraph workflow and model integration
├── runtime.py               # AgentCore application and request handler
├── Requirement.txt          # Python dependencies installed into the image
├── Dockerfile               # Instructions to package the application
├── create-runtime.json      # Runtime creation configuration (local/deployment file)
├── payload.json             # Example request used for smoke testing
├── response.json            # Example response output; normally not committed
├── .gitignore
└── README.md
```

Optional local-only files/folders:

```text
.venv/                       # Local virtual environment; do not commit
.aws/                        # Do not store credentials in the repository
.env                         # Secrets/config; do not commit
```

A suitable `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.env
.env.*
!.env.example
payload.json
response.json
.aws/
```

If you want to commit a sample payload, use a safe, generic example that contains no customer data. Never commit real credentials or private runtime output.

## 5. Step 1: Create the Python environment

Run from the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Line by line:

- `python -m venv .venv` creates a project-local virtual environment.
- `Activate.ps1` activates that environment in the current PowerShell session.
- `python -m pip install --upgrade pip` updates the package installer in that environment.

Install the packages needed by your code:

```powershell
python -m pip install bedrock-agentcore langgraph langchain-core langchain-aws
```

If you already have a tested `Requirement.txt`, install from it instead:

```powershell
python -m pip install -r Requirement.txt
```

Validate imports and syntax:

```powershell
python -m py_compile agent.py runtime.py
```

This checks Python syntax; it does not prove that AWS credentials, permissions, or model access are valid.

## 6. Step 2: Build the LangGraph agent

The following is a **minimal illustrative agent** for this deployment pattern. It shows a single model node and is not a multi-tool or multi-agent workflow. Keep your project's tested `agent.py` if it differs.

### `agent.py`

```python
import os

from langchain_aws import ChatBedrockConverse
from langgraph.graph import END, START, MessagesState, StateGraph

REGION = os.environ.get("AWS_REGION", "<AWS_REGION>")
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]

model = ChatBedrockConverse(
    model=MODEL_ID,
    region_name=REGION,
)


def call_model(state: MessagesState):
    response = model.invoke(state["messages"])
    return {"messages": [response]}


builder = StateGraph(MessagesState)
builder.add_node("model", call_model)
builder.add_edge(START, "model")
builder.add_edge("model", END)

agent = builder.compile()
```

### Line-by-line explanation

- `import os`: reads configuration from environment variables instead of embedding environment-specific values in code.
- `ChatBedrockConverse`: provides a LangChain chat-model interface for Amazon Bedrock's Converse API.
- `END`, `START`, `MessagesState`, `StateGraph`: building blocks used to define the LangGraph workflow.
- `REGION = ...`: selects the AWS region. Set it to a real region through the environment or replace the placeholder with your chosen region.
- `MODEL_ID = os.environ["BEDROCK_MODEL_ID"]`: requires the model ID/profile to be supplied in the environment. If missing, Python raises a clear `KeyError` at startup.
- `ChatBedrockConverse(...)`: configures the model integration. It does not embed AWS credentials; the AWS SDK obtains credentials from its configured credential chain.
- `call_model(state)`: defines a graph node that receives the current state.
- `model.invoke(state["messages"])`: sends the messages to the model and waits for a response.
- `return {"messages": [response]}`: returns the updated messages in the format expected by `MessagesState`.
- `StateGraph(MessagesState)`: creates a graph whose state is a collection of messages.
- `add_node("model", call_model)`: registers the function under the node name `model`.
- `add_edge(START, "model")`: routes the graph's entry point to the model node.
- `add_edge("model", END)`: ends this simple workflow after the model returns.
- `compile()`: turns the graph definition into an executable LangGraph object.

### What this example does not implement

This example is a single-node model workflow. It does not define tools, conditional edges, persistent conversation memory, retrieval-augmented generation (RAG), or multi-agent delegation. Add those features explicitly if the application requires them.

## 7. Step 3: Add the AgentCore entry point

### `runtime.py`

This is the entry-point pattern used by the deployed application:

```python
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
```

### Line-by-line explanation

- `BedrockAgentCoreApp`: the SDK class that wraps the Python application for AgentCore Runtime.
- `HumanMessage`: represents the incoming user prompt as a LangChain message.
- `from agent import agent`: imports the compiled graph from `agent.py`.
- `app = BedrockAgentCoreApp()`: creates the runtime application object.
- `@app.entrypoint`: registers the function that AgentCore calls when it receives an invocation.
- `def invoke(payload: dict)`: defines a handler expecting a JSON-like dictionary.
- `payload.get("prompt") or payload.get("input")`: supports either `prompt` or `input` as the request field.
- `if not prompt`: rejects missing or empty input.
- `HumanMessage(content=prompt)`: wraps the prompt in the message structure expected by the graph.
- `agent.invoke(...)`: runs the graph synchronously and waits for the final state.
- `result["messages"][-1].content`: retrieves the content of the final message.
- `return {"response": answer}`: returns a JSON-serializable response object.
- `if __name__ == "__main__":`: ensures the server starts when this file is executed directly.
- `app.run()`: starts the AgentCore application server.

Example input:

```json
{
  "prompt": "Explain LangGraph in three sentences."
}
```

Example response shape:

```json
{
  "response": "A generated answer from the model."
}
```

The response text is generated at runtime and can vary between invocations.

### Local smoke test (optional)

You can start the application locally:

```powershell
python runtime.py
```

In a second terminal, check the health endpoint:

```powershell
Invoke-WebRequest http://localhost:8080/ping -UseBasicParsing
```

A healthy response verifies the local server is listening. It does not verify the deployed AWS runtime.

## 8. Step 4: Define dependencies

The dependency file must be valid pip requirements syntax, not the visual table produced by `pip list`.

### `Requirement.txt`

Use tested package versions in the real project. A minimal illustrative list is:

```text
bedrock-agentcore==<TESTED_VERSION>
langchain-aws==<TESTED_VERSION>
langchain-core==<TESTED_VERSION>
langgraph==<TESTED_VERSION>
```

Replace the placeholders with valid package versions before building. Alternatively, maintain a fully pinned requirements file produced and reviewed from the project's working environment.

Install dependencies in the active virtual environment:

```powershell
python -m pip install -r Requirement.txt
```

Why this file exists: Docker builds a fresh Linux environment. It cannot rely on packages installed only in the developer's Windows `.venv`; it installs the listed packages inside the image.

## 9. Step 5: Build the Docker image

### `Dockerfile`

This mirrors the Dockerfile pattern used for the deployment. Verify the architecture supported by your target runtime before choosing `linux/arm64`.

```dockerfile
FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

COPY Requirement.txt .
RUN pip install --no-cache-dir -r Requirement.txt

COPY agent.py runtime.py ./

ENV PYTHONUNBUFFERED=1
ENV BEDROCK_MODEL_ID=<MODEL_OR_INFERENCE_PROFILE_ID>

CMD ["python", "runtime.py"]
```

### Line-by-line explanation

- `FROM --platform=linux/arm64 python:3.12-slim`: chooses a small Python base image for the target Linux architecture.
- `WORKDIR /app`: sets the container's working directory.
- `COPY Requirement.txt .`: copies the dependency list into `/app`.
- `RUN pip install --no-cache-dir -r Requirement.txt`: installs the Python packages into the image and avoids retaining pip's download cache.
- `COPY agent.py runtime.py ./`: copies the application's entry-point and graph modules.
- `ENV PYTHONUNBUFFERED=1`: helps make Python logs appear promptly in container logs.
- `ENV BEDROCK_MODEL_ID=...`: sets the model configuration. The value shown is a placeholder, not a secret.
- `CMD ["python", "runtime.py"]`: starts the AgentCore application when the container starts.

Do not put AWS access keys in the Dockerfile. The runtime should obtain AWS credentials from the execution role.

Build the image:

```powershell
docker build --platform linux/arm64 -t <LOCAL_IMAGE_NAME>:latest .
```

Check it exists:

```powershell
docker image ls
```

Why Docker is used: it packages the Python runtime, dependencies, and application files together so AgentCore can run the same packaged application independently of the developer's workstation.

## 10. Step 6: Create and push to ECR

Amazon ECR stores the image that AgentCore pulls. Create a private repository in the same region used for deployment, then set your own variables:

```powershell
$env:AWS_REGION = "<AWS_REGION>"
$env:AWS_ACCOUNT_ID = "<12_DIGIT_ACCOUNT_ID>"
$env:ECR_REPOSITORY = "<ECR_REPOSITORY_NAME>"
$env:ECR_REGISTRY = "$($env:AWS_ACCOUNT_ID).dkr.ecr.$($env:AWS_REGION).amazonaws.com"
$env:ECR_IMAGE_URI = "$($env:ECR_REGISTRY)/$($env:ECR_REPOSITORY):latest"
```

Create the repository if it does not already exist:

```powershell
aws ecr create-repository `
    --repository-name $env:ECR_REPOSITORY `
    --region $env:AWS_REGION
```

If it already exists, do not recreate it; verify it using `aws ecr describe-repositories`.

Authenticate Docker to ECR:

```powershell
aws ecr get-login-password --region $env:AWS_REGION |
    docker login --username AWS --password-stdin $env:ECR_REGISTRY
```

Tag the image:

```powershell
docker tag <LOCAL_IMAGE_NAME>:latest $env:ECR_IMAGE_URI
```

Push the image:

```powershell
docker push $env:ECR_IMAGE_URI
```

Verify the image tag:

```powershell
aws ecr describe-images `
    --repository-name $env:ECR_REPOSITORY `
    --region $env:AWS_REGION
```

### Why these commands are separate

- `create-repository` creates the remote image repository.
- `get-login-password` obtains a short-lived ECR authentication token.
- `docker login` configures Docker to authenticate to the registry.
- `docker tag` gives the local image the destination registry name.
- `docker push` uploads the image layers and manifest.
- `describe-images` verifies that ECR has an image available.

The ECR login is for pushing from the workstation. AgentCore's runtime execution role separately needs permission to pull the image.

## 11. Step 7: Configure IAM roles and permissions

IAM has two main responsibilities in this setup.

### A. Deployment/invocation identity

The identity used by your local AWS CLI needs permissions for the control-plane operations it performs, such as creating the runtime, creating related resources when required, reading runtime status, and invoking the runtime. It may also need `iam:PassRole` for the selected execution role.

Examples of relevant actions can include:

```text
bedrock-agentcore:CreateAgentRuntime
bedrock-agentcore:CreateAgentRuntimeEndpoint
bedrock-agentcore:CreateWorkloadIdentity
bedrock-agentcore:GetAgentRuntime
bedrock-agentcore:InvokeAgentRuntime
iam:PassRole
```

This is an illustrative list, not a complete universal policy. Exact actions and resource ARNs depend on the API calls and resources used. Scope permissions to the intended account, region, runtime, endpoint, and role where supported.

### B. AgentCore execution role

The runtime execution role is assumed by the AgentCore service. Its trust policy must permit the appropriate AgentCore service principal to assume the role and should use source conditions where supported.

The role also needs ECR image-pull permissions. `ecr:GetAuthorizationToken` must use `"Resource": "*"`, while the pull actions can be scoped to the repository ARN.

Illustrative ECR policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuthorizationToken",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "PullContainerImage",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchCheckLayerAvailability"
      ],
      "Resource": "<ECR_REPOSITORY_ARN>"
    }
  ]
}
```

The role also needs the relevant Bedrock invocation permissions for the selected model or inference profile. Keep those resources aligned with the actual model configuration.

### Why trust policy and permission policy are different

- A **trust policy** defines which principal can assume a role.
- A **permissions policy** defines what an assumed role can do.

Both must be correct. Granting a role Bedrock permissions does not, by itself, allow AgentCore to assume that role.

### Troubleshooting IAM errors

When AWS returns `AccessDeniedException`, read all three parts:

1. The action that was denied.
2. The resource ARN named in the error.
3. The identity named in the error.

For example, a base runtime and its default endpoint can have different resource ARNs. A permission on one resource may not authorize the other.

Use the IAM policy simulator where permitted:

```powershell
aws iam simulate-principal-policy `
    --policy-source-arn "<IAM_USER_OR_ROLE_ARN>" `
    --action-names "bedrock-agentcore:GetAgentRuntime" `
    --resource-arns "<RUNTIME_ARN>" `
    --output json
```

A simulation result of `allowed` is useful evidence about the evaluated policies, but a real API request is still needed to confirm the operation works in its actual context.

## 12. Step 8: Configure the AgentCore runtime

Create a runtime configuration file such as `create-runtime.json`. Keep it local if it contains account-specific infrastructure identifiers; a sanitized template can be committed.

```json
{
  "agentRuntimeName": "<RUNTIME_NAME>",
  "agentRuntimeArtifact": {
    "containerConfiguration": {
      "containerUri": "<ECR_IMAGE_URI>"
    }
  },
  "roleArn": "<EXECUTION_ROLE_ARN>",
  "networkConfiguration": {
    "networkMode": "PUBLIC"
  },
  "protocolConfiguration": {
    "serverProtocol": "HTTP"
  },
  "environmentVariables": {
    "BEDROCK_MODEL_ID": "<MODEL_OR_INFERENCE_PROFILE_ID>"
  },
  "description": "LangGraph agent using Amazon Bedrock"
}
```

### What each field means

- `agentRuntimeName`: friendly name for the runtime.
- `agentRuntimeArtifact.containerConfiguration.containerUri`: the exact ECR image to run.
- `roleArn`: execution role AgentCore uses.
- `networkConfiguration.networkMode`: the selected network configuration. `PUBLIC` is shown because this deployment used public networking; use a suitable network mode for your environment.
- `protocolConfiguration.serverProtocol`: declares the server protocol expected by AgentCore.
- `environmentVariables`: configuration available to the Python process.
- `description`: a human-readable explanation of the runtime.

Create the runtime:

```powershell
aws bedrock-agentcore-control create-agent-runtime `
    --cli-input-json file://create-runtime.json `
    --region $env:AWS_REGION `
    --output json
```

Record the returned runtime ID and ARN privately. Do not publish real account-specific ARNs in a public README.

The initial status is normally a provisioning state such as `CREATING`. A successful create API response does not guarantee that the container has finished starting.

## 13. Step 9: Create and verify the runtime

Use the runtime ID returned by AWS:

```powershell
aws bedrock-agentcore-control get-agent-runtime `
    --agent-runtime-id "<AGENT_RUNTIME_ID>" `
    --agent-runtime-version "1" `
    --region $env:AWS_REGION `
    --output json
```

Check the `status` field:

- `CREATING`: provisioning is still in progress.
- `READY`: runtime is ready for testing.
- `CREATE_FAILED`: inspect the returned failure details and runtime logs.

Do not assume that the runtime ID or version will be the same in different AWS accounts or deployments.

## 14. Step 10: Invoke and test the deployed agent

Create a request payload. Use a generic prompt and avoid private or customer data:

```powershell
@'
{"prompt":"Explain what a LangGraph agent is in three simple sentences."}
'@ | Set-Content -Encoding utf8 payload.json
```

Invoke the runtime:

```powershell
aws bedrock-agentcore invoke-agent-runtime `
    --agent-runtime-arn "<AGENT_RUNTIME_ARN>" `
    --runtime-session-id "<SESSION_ID_AT_LEAST_33_CHARACTERS>" `
    --content-type "application/json" `
    --accept "application/json" `
    --payload fileb://payload.json `
    response.json `
    --region $env:AWS_REGION
```

The session ID must satisfy the API's length and character constraints. Use a fresh unique ID when appropriate, and don't treat a session ID as an authentication secret.

Inspect the response:

```powershell
Get-Content .\response.json
```

A typical response body has this shape:

```json
{
  "response": "A generated answer from the agent."
}
```

The CLI's metadata should report a successful status code, such as `200`. If the request fails, inspect the exact error before changing policies or rebuilding the image.

### What the successful test proves

A successful end-to-end invocation demonstrates that:

1. The caller was authorized to invoke the runtime.
2. The runtime endpoint received the request.
3. The container and entry point processed the payload.
4. The graph executed.
5. The application could call the selected Bedrock model.
6. The response was returned to the caller.

It does not prove production readiness, high availability, load handling, or correctness for every possible prompt.

## 15. What the important files do

| File | Responsibility | Usually commit? |
|---|---|---|
| `agent.py` | LangGraph graph and model integration | Yes, after reviewing for secrets |
| `runtime.py` | AgentCore entry point and payload handling | Yes |
| `Requirement.txt` | Python dependencies | Yes |
| `Dockerfile` | Container build instructions | Yes |
| `create-runtime.json` | Deployment settings, including account-specific identifiers | Prefer a sanitized template |
| `payload.json` | Smoke-test input | Optional; only safe sample data |
| `response.json` | Captured runtime output | Usually no |
| `.venv/` | Local Python environment | No |
| `.env` / credentials files | Potential secrets | Never commit |

A sanitized file such as `create-runtime.example.json` can document the required shape while replacing ARNs, account IDs, repository URIs, and runtime names with placeholders.

## 16. Troubleshooting

### Docker cannot build or the architecture is wrong

- Confirm Docker Desktop is running.
- Verify the target platform is supported.
- Rebuild the image after changing the Dockerfile or dependencies.
- Check that the image was pushed to the expected ECR repository.

### AgentCore cannot pull the ECR image

Check the **execution role**, not only the developer IAM user. Verify `ecr:GetAuthorizationToken` uses `"Resource": "*"`, and ensure the repository pull actions are granted for the correct repository.

### `CreateAgentRuntime` is denied

Check the deployment identity's effective permission for `bedrock-agentcore:CreateAgentRuntime` on the resource ARN named by AWS. Also verify `iam:PassRole` for the selected execution role and any required related-resource permissions.

### `GetAgentRuntime` or invocation is denied

Check the exact action and resource ARN in the error. The runtime ARN and default endpoint ARN can be different. Confirm the policy was saved and is attached to the identity actually used by the CLI.

### The runtime is `READY` but model calls fail

Check:

- The model ID or inference profile is correct for the chosen region.
- The account is permitted to use the model.
- The execution role can invoke the model/profile.
- The container logs for startup, dependency, or model invocation errors.

### The runtime returns a payload validation error

Ensure the request is valid JSON and includes a non-empty `prompt` or `input` field. The request's `--content-type` must match the payload format.

### The runtime uses an older image after a push

A pushed image tag does not necessarily update an existing runtime. Deploy an updated runtime version using the supported AgentCore workflow and verify the active version before testing again.

## 17. Security checklist

Before publishing the repository or sharing it with others:

- [ ] Remove all access keys, secret keys, session tokens, passwords, and private tokens.
- [ ] Replace real AWS account IDs and resource ARNs with placeholders in examples.
- [ ] Replace private ECR repository URIs and runtime IDs with placeholders.
- [ ] Do not commit `.env`, AWS credentials files, or the local `.venv`.
- [ ] Avoid putting credentials in Docker build arguments or image layers.
- [ ] Use IAM roles for runtime access instead of embedding long-lived AWS keys.
- [ ] Keep deployment permissions and runtime execution permissions separate.
- [ ] Scope permissions to the resources and actions required.
- [ ] Review and remove temporary diagnostic/full-access policies after troubleshooting.
- [ ] Use sanitized logs and payloads; do not publish personal, customer, or business-sensitive content.
- [ ] Avoid committing raw `response.json` files if their content could be sensitive.
- [ ] Use a secret scanner before publishing the repository.

**Important:** AWS account IDs and ARNs are not credentials in the same sense as secret access keys, but they expose infrastructure identifiers. This guide uses placeholders so readers can adapt it without copying account-specific configuration. Never share AWS secret access keys or session tokens.

## 18. Updating and cleaning up

### Updating the agent

When code or dependencies change:

1. Run tests and syntax checks locally.
2. Rebuild the Docker image.
3. Tag and push the updated image to ECR.
4. Deploy an updated AgentCore runtime version using the supported update/versioning workflow.
5. Check the active runtime version and status.
6. Invoke the deployed agent with a smoke-test payload.
7. Review logs and errors before promoting the change.

Do not assume that replacing the `latest` tag automatically updates the container already deployed.

### Avoid unexpected charges

Review ECR storage, AgentCore runtime usage, model invocation/token costs, and CloudWatch log retention. When the deployment is no longer needed, use the AWS-supported deletion workflow for the runtime, and then remove the ECR repository and related IAM resources only if they are no longer used. Check dependencies before deleting shared roles or repositories.

---

## Summary

The deployment process is:

1. Build the Python/LangGraph application.
2. Expose it through the AgentCore SDK entry point.
3. Define dependencies and package the code with Docker.
4. Push the container image to Amazon ECR.
5. Configure IAM trust and permissions.
6. Create the AgentCore runtime from the ECR image.
7. Wait for the runtime to become `READY`.
8. Invoke it with a JSON payload and verify the response.

The key principle is to separate **application code**, **container packaging**, **image storage**, **runtime deployment**, and **IAM authorization**. Each has a different responsibility, and all must be configured correctly for the end-to-end agent invocation to work.
'''
path = "/mnt/data/README_AgentCore_LangGraph_Deployment.md"
pypandoc.convert_text(readme, 'md', format='md', outputfile=path, extra_args=['--standalone'])
print(f"Created: {path}")
print(f"Size: {os.path.getsize(path)} bytes")
