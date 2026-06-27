# 🕵️ Drift Detective

> An AI-powered Terraform state drift detection, triage, and remediation system.

Drift Detective turns scattered, manual console firefighting into a **supervised,
AI-classified, approval-gated workflow**. It continuously compares your declared
desired state against what's actually running in AWS, uses **Claude Haiku 4.5 (via
AWS Bedrock)** to triage each finding as Safe / Suspicious / Critical, routes alerts
to Slack, and remediates only after a human approves.

---

## 🎯 The Problem

Production infrastructure drifts every day. Security groups get manually changed,
instance types get resized outside of Terraform, resources get deleted in a panic at
2am. Today that drift is **invisible until it causes an outage** — and finding the
cause means digging through CloudTrail and relying on tribal knowledge.

**Drift Detective makes drift visible, triaged, and supervised:**

- 🔍 **Detects** drift across multiple environments in parallel
- 🧠 **Classifies** each drift with an LLM, not just a static rule engine
- 🚦 **Routes** by severity — safe is logged; suspicious & critical post to Slack for review
- ✅ **Gates** every remediation behind a human approval step
- 🔁 **Remediates** automatically once approved, restoring the desired state
- 📊 **Visualizes** live status per environment on a hosted dashboard

---

## 🏗️ Architecture

```
TRIGGER       → SuperPlane scheduled (every 15 min) or manual trigger
FAN-OUT       → Parallel Lambda invocations (one per environment)
LAMBDA        → Reads desired_state.json from S3, calls AWS APIs, returns drift report
AI STEP       → Claude Haiku 4.5 (Bedrock) classifies each drift: Safe / Suspicious / Critical
ROUTING       → If overall != "safe" → Slack alert; else end (safe is just logged via run history)
APPROVAL GATE → Engineer reviews in SuperPlane Console, approves remediation
REMEDIATION   → Lambda apply function restores desired state
RENDER WEB    → React + Express dashboard showing live drift status per environment
RENDER WORKER → Python worker triggers scheduled scans via the SuperPlane API
```

### Two simulated environments (single AWS account, all in us-east-1)

| Environment | Region      | Example demo role                           |
|-------------|-------------|---------------------------------------------|
| `prod`      | us-east-1   | Critical drift (unauthorized SSH ingress)   |
| `dev`       | us-east-1   | Suspicious drift (instance type changed)    |

> Single-region by design: SuperPlane invokes Lambdas in its integration's region, so
> keeping everything in `us-east-1` (where Bedrock Claude Haiku 4.5 also lives) avoids
> cross-region invocation issues. Add more environments by replicating the per-env
> resources in `infra/main.tf`.

> **Why no Anthropic API key?** The classifier Lambda calls Claude **directly via AWS
> Bedrock using IAM-role authentication** (`bedrock:InvokeModel`). There is no Anthropic
> API key to manage and no SuperPlane Claude component to configure.

---

## 🧰 Tech Stack

| Layer              | Technology                                |
|--------------------|-------------------------------------------|
| Orchestration      | SuperPlane Cloud (app.superplane.com)     |
| Infrastructure     | Terraform (flat `main.tf`, no modules)    |
| Drift detection    | Python 3.12 Lambda + boto3                |
| AI classification  | AWS Bedrock — Claude Haiku 4.5            |
| Dashboard backend  | Node.js 20 + Express                      |
| Dashboard frontend | React 18 + Vite                           |
| Worker             | Python 3.12                               |
| Hosting            | Render (Web Service + Background Worker)   |
| State storage      | AWS S3 (desired-state JSON)               |
| Notifications      | Slack (via SuperPlane integration)        |
| Version control    | GitHub                                     |

---

## 📁 Repository Structure

```
drift-detective/
├── infra/                      # Terraform (flat, single-region us-east-1)
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── dev.tfvars
│   └── prod.tfvars
├── lambda/
│   ├── drift_detector/         # Reads desired state, diffs against live AWS
│   ├── drift_classifier/       # Calls Bedrock Claude Haiku 4.5 to triage
│   ├── drift_remediator/       # Restores desired state after approval
│   └── build.sh                # Optional manual ZIP packaging
├── desired_states/             # Per-env desired_state.json (fill IDs after apply)
│   ├── prod/  dev/
├── dashboard/                  # Render Web Service (Express + React/Vite)
│   ├── server.js
│   ├── vite.config.js
│   ├── index.html
│   └── src/ (App.jsx, components/, index.css)
├── worker/                     # Render Background Worker (Python scheduler)
│   ├── main.py
│   ├── requirements.txt
│   └── Procfile
├── .env.example
├── .gitignore
└── README.md
```

---

## 🔑 Bring Your Own Accounts & Credentials

This project uses **no shared/owner credentials** — everything runs on **your own**
accounts. You will need:

| What | Where you create it | Where it's used |
|------|---------------------|-----------------|
| **AWS account + IAM credentials** | AWS Console → IAM (an admin user/role) | `aws configure` locally for Terraform |
| **Bedrock model access** (Claude Haiku 4.5) | AWS Console → Bedrock → Model access (us-east-1) | Used by the classifier Lambda via IAM |
| **SuperPlane account + service-account token + org slug** | app.superplane.com → Settings → Service Accounts | Render env vars; dashboard/worker auth |
| **Render account** | dashboard.render.com | Hosts the dashboard + worker |
| **Slack workspace + app** | slack.com / api.slack.com | SuperPlane Slack integration (#drift-alerts) |
| **GitHub account** | github.com | Hosts your fork; SuperPlane + Render deploy from it |

> SuperPlane's AWS integration uses **OIDC web-identity** — during setup it gives you a
> provider URL + audience; you create an IAM OIDC provider and a role that trusts it,
> then paste the **role ARN**. (No long-lived AWS keys for SuperPlane.)
>
> Secrets live only in your local `.env` (git-ignored) and in Terraform state
> (git-ignored). Never commit real keys. `.env.example` shows the variable names.

---

## 🚀 Setup Guide

### 1. Prerequisites
- AWS account with the CLI installed and configured (`aws configure`)
- Terraform ≥ 1.5, Node.js 20, Python 3.12
- Accounts: SuperPlane, Render, Slack, GitHub

### 2. Fork & clone
```bash
git clone https://github.com/<your-username>/drift-detective.git
cd drift-detective
```

### 3. Enable Bedrock & confirm the model ID
In the AWS Console → **Bedrock → Model access** (region **us-east-1**), enable
**Claude Haiku 4.5**. Then confirm the exact model ID:
```bash
aws bedrock list-foundation-models --region us-east-1 \
  --query "modelSummaries[?contains(modelId,'haiku')].[modelId,modelName]" \
  --output table
```
Claude Haiku 4.5 requires the **cross-region inference profile** ID
(`us.anthropic.claude-haiku-4-5-...`). If yours differs from the value already in
[infra/main.tf](infra/main.tf) (`BEDROCK_MODEL_ID`), update it there.

### 4. Provision AWS infrastructure
```bash
cd infra
terraform init
terraform plan  -var-file=dev.tfvars
terraform apply -var-file=dev.tfvars            # creates S3, IAM, 2 EC2, 5 Lambdas (all us-east-1)
terraform output -json > ../terraform_outputs.json
```
Note the outputs — you'll need the demo instance/SG IDs and the bucket names:
```bash
terraform output                                    # instance + SG IDs, bucket names
```

### 5. Fill desired states & upload to S3
Replace the `REPLACE_WITH_*` placeholders in `desired_states/*/desired_state.json`
with the instance/SG IDs from `terraform output`, then upload each to its bucket:
```bash
aws s3 cp desired_states/prod/desired_state.json s3://$(terraform -chdir=infra output -raw state_bucket_prod)/desired_state.json --region us-east-1
aws s3 cp desired_states/dev/desired_state.json  s3://$(terraform -chdir=infra output -raw state_bucket_dev)/desired_state.json  --region us-east-1
```

### 6. Configure SuperPlane
1. Create an organization (note the **org slug**) at app.superplane.com.
2. **Integrations → GitHub** → connect and select your `drift-detective` repo.
3. **Integrations → AWS** → OIDC web-identity: create the IAM OIDC provider + role it
   describes, then paste the **role ARN** (STS region `us-east-1`).
4. **Integrations → Slack** → authorize your workspace + Slack app, select `#drift-alerts`.
5. **Apps → Create New App** → name it `drift-detective`.
6. Build the **Canvas**:
   `Schedule trigger (*/15 * * * *)` → 2 parallel **detector** Lambda nodes → **classifier**
   Lambda → **If** (`$['drift-detector-classifier'].data.payload.overall != "safe"`) →
   true: **Slack** message → **Approval** → 2 parallel **remediator** Lambda nodes →
   final Slack; false: end (safe).
7. **Settings → Service Accounts** → create a service account + token (used by Render).

> Lambda function names follow `drift-detective-drift-{detector,classifier,remediator}-{env}`.
> Reference a node's output with `$['node-name'].data.payload.<field>` — the Lambda's
> return value is under `.data.payload`. Use `{{ }}` braces in payload/Slack fields, but
> **no braces** in the `If` condition (it's a raw CEL expression).

### 7. Deploy the dashboard + worker on Render
Both connect to your GitHub repo. Add the env vars to each service.

**Web Service** (`dashboard/`): build `npm install && npm run build`, start `node server.js`
**Background Worker** (`worker/`): build `pip install -r requirements.txt`, start `python main.py`

```
SUPERPLANE_API_URL  = https://api.superplane.com
SUPERPLANE_API_KEY  = <your SuperPlane API key>
SUPERPLANE_ORG      = <your org slug>
SUPERPLANE_APP_NAME = drift-detective
PORT                = 3000          # web service only
POLL_INTERVAL_SECONDS = 300         # worker only
```

### 8. Simulate drift (demo)
Introduce real drift outside Terraform to see the classify-and-route flow:
- **prod** → add unauthorized SSH ingress `0.0.0.0/0:22` (→ Critical)
- **dev** → change instance type `t3.nano → t3.micro` (→ Suspicious)
- (leave an env untouched to see a Safe / green result)

Trigger a scan (dashboard button, or the SuperPlane manual trigger) and watch the
classification, Slack alerts, approval gate, and remediation.

### 9. Tear down
```bash
# empty the versioned S3 buckets first, then:
cd infra && terraform destroy -var-file=dev.tfvars
```

---

## 🤖 How the AI Classification Works

The `drift_classifier` Lambda receives the environment reports, builds a single
prompt, and invokes Claude Haiku 4.5 on Bedrock. Claude returns **structured JSON
only** (no prose, no fences):

```json
{
  "environments": {
    "prod": { "classification": "critical", "reason": "...", "immediate_action": "..." },
    "dev":  { "classification": "safe",     "reason": "...", "immediate_action": "..." }
  },
  "overall": "critical",
  "summary": "2-3 sentence executive summary for the on-call engineer"
}
```

If parsing ever fails, the Lambda **fails safe** — it returns `suspicious` so a human
reviews rather than silently ignoring potential drift.

---

## 💰 Cost

Runs for well under **$1/day**: the only meaningful hourly charge is 2× `t3.nano` EC2
instances; Bedrock is billed per token (~50 scans ≈ a few cents), and Lambda and S3
fall within free-tier/negligible usage. Render's free tier and SuperPlane Cloud cover
hosting and orchestration. Run `terraform destroy` when you're done to stop the EC2
charges.

| Resource | Approx. cost |
|----------|--------------|
| 2× t3.nano EC2 (~8h) | ~$0.10 |
| Bedrock — Claude Haiku 4.5 (~50 scans) | ~$0.28 |
| Lambda / S3 / CloudWatch | < $0.10 |
| **Total** | **~$0.50** |

---

## 📜 License

MIT — use freely.
