terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

provider "aws" {
  region = var.aws_region_prod
  alias  = "prod"
}
provider "aws" {
  region = var.aws_region_staging
  alias  = "staging"
}
provider "aws" {
  region = var.aws_region_dev
  alias  = "dev"
}

locals {
  tags = {
    Project   = var.project
    ManagedBy = "terraform"
  }
}

# ─── S3 STATE BUCKETS ──────────────────────────────────────────────────────────
resource "aws_s3_bucket" "state_prod" {
  provider = aws.prod
  bucket   = "${var.project}-desired-state-prod-${data.aws_caller_identity.current.account_id}"
  tags     = merge(local.tags, { Environment = "prod" })
}

resource "aws_s3_bucket" "state_dev" {
  provider = aws.dev
  # New name (region moved to us-east-1); avoids global-namespace collision with the old eu-west-1 bucket
  bucket = "${var.project}-desired-state-dev-ue1-${data.aws_caller_identity.current.account_id}"
  tags   = merge(local.tags, { Environment = "dev" })
}

resource "aws_s3_bucket_versioning" "state_prod" {
  provider = aws.prod
  bucket   = aws_s3_bucket.state_prod.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_versioning" "state_dev" {
  provider = aws.dev
  bucket   = aws_s3_bucket.state_dev.id
  versioning_configuration { status = "Enabled" }
}

# ─── IAM ROLE FOR LAMBDA ───────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_role" {
  name = "${var.project}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags = local.tags
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project}-lambda-policy"
  role = aws_iam_role.lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "${aws_s3_bucket.state_prod.arn}/*", "${aws_s3_bucket.state_prod.arn}",
          "${aws_s3_bucket.state_dev.arn}/*", "${aws_s3_bucket.state_dev.arn}"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances", "ec2:DescribeSecurityGroups",
          "ec2:DescribeSecurityGroupRules", "ec2:ModifyInstanceAttribute",
          "ec2:StartInstances", "ec2:StopInstances",
          "ec2:RevokeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupIngress",
          "ecs:DescribeServices", "ecs:ListServices", "ecs:UpdateService",
          "s3:ListAllMyBuckets", "s3:GetBucketPublicAccessBlock"
        ]
        Resource = "*"
      },
      {
        # Cross-region inference profile (us.anthropic.claude-haiku-4-5-*) routes the
        # call to multiple regions, so we must allow both the inference-profile ARN
        # and the underlying foundation-model ARNs in any region.
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:*:*:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      },
      {
        # status Lambda invokes the detector + classifier Lambdas
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.aws_region_prod}:${data.aws_caller_identity.current.account_id}:function:${var.project}-*"
      }
    ]
  })
}

# ─── IAM USER FOR SUPERPLANE ───────────────────────────────────────────────────
resource "aws_iam_user" "superplane" {
  name = "${var.project}-superplane-user"
  tags = local.tags
}

resource "aws_iam_user_policy" "superplane_policy" {
  name = "${var.project}-superplane-policy"
  user = aws_iam_user.superplane.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["lambda:InvokeFunction", "lambda:GetFunction", "lambda:ListFunctions"]
        Resource = [
          aws_lambda_function.drift_detector_prod.arn,
          aws_lambda_function.drift_detector_dev.arn,
          aws_lambda_function.drift_classifier.arn,
          aws_lambda_function.drift_remediator_prod.arn,
          aws_lambda_function.drift_remediator_dev.arn
        ]
      }
    ]
  })
}

resource "aws_iam_access_key" "superplane" {
  user = aws_iam_user.superplane.name
}

# ─── LAMBDA ZIP PACKAGES ───────────────────────────────────────────────────────
data "archive_file" "drift_detector_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/drift_detector"
  output_path = "${path.module}/../lambda/drift_detector.zip"
}

data "archive_file" "drift_classifier_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/drift_classifier"
  output_path = "${path.module}/../lambda/drift_classifier.zip"
}



data "archive_file" "drift_remediator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/drift_remediator"
  output_path = "${path.module}/../lambda/drift_remediator.zip"
}

data "archive_file" "drift_status_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/drift_status"
  output_path = "${path.module}/../lambda/drift_status.zip"
}

data "archive_file" "drift_code_generator_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/drift_code_generator"
  output_path = "${path.module}/../lambda/drift_code_generator.zip"
}

# ─── LAMBDA FUNCTION — DRIFT CLASSIFIER (Bedrock, us-east-1 only) ─────────────
# Runs only in us-east-1 where Bedrock Claude Haiku 4.5 is available.
# Replace BEDROCK_MODEL_ID value with exact ID from:
#   aws bedrock list-foundation-models --region us-east-1 \
#     --query "modelSummaries[?contains(modelId,'haiku')].[modelId]" --output text
resource "aws_lambda_function" "drift_classifier" {
  provider         = aws.prod
  function_name    = "${var.project}-drift-classifier"
  filename         = data.archive_file.drift_classifier_zip.output_path
  source_code_hash = data.archive_file.drift_classifier_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 60
  memory_size      = 256
  environment {
    variables = {
      BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      BEDROCK_REGION   = "us-east-1"
    }
  }
  tags = local.tags
}

# ─── LAMBDA FUNCTION — CODE GENERATOR (Bedrock writes remediation code at runtime) ──
resource "aws_lambda_function" "drift_code_generator" {
  provider         = aws.prod
  function_name    = "${var.project}-code-generator"
  filename         = data.archive_file.drift_code_generator_zip.output_path
  source_code_hash = data.archive_file.drift_code_generator_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 60
  memory_size      = 256
  environment {
    variables = {
      BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      BEDROCK_REGION   = "us-east-1"
    }
  }
  tags = local.tags
}

# ─── LAMBDA FUNCTION — STATUS (live drift for the dashboard, via Function URL) ──
resource "aws_lambda_function" "drift_status" {
  provider         = aws.prod
  function_name    = "${var.project}-status"
  filename         = data.archive_file.drift_status_zip.output_path
  source_code_hash = data.archive_file.drift_status_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 60
  memory_size      = 256
  environment {
    variables = {
      PROJECT           = var.project
      AWS_REGION_TARGET = var.aws_region_prod
    }
  }
  tags = local.tags
}

# Public Function URL — the Render dashboard's backend calls this to read live status.
# Returns drift details (resource IDs); lock down with auth if that's sensitive for you.
resource "aws_lambda_function_url" "drift_status" {
  provider           = aws.prod
  function_name      = aws_lambda_function.drift_status.function_name
  authorization_type = "NONE"
  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
  }
}

resource "aws_lambda_permission" "status_url_public" {
  provider               = aws.prod
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.drift_status.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# ─── LAMBDA FUNCTIONS — DRIFT DETECTOR ────────────────────────────────────────
resource "aws_lambda_function" "drift_detector_prod" {
  provider         = aws.prod
  function_name    = "${var.project}-drift-detector-prod"
  filename         = data.archive_file.drift_detector_zip.output_path
  source_code_hash = data.archive_file.drift_detector_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      ENVIRONMENT       = "prod"
      STATE_BUCKET      = aws_s3_bucket.state_prod.bucket
      AWS_REGION_TARGET = var.aws_region_prod
    }
  }
  tags = merge(local.tags, { Environment = "prod" })
}

resource "aws_lambda_function" "drift_detector_dev" {
  provider         = aws.dev
  function_name    = "${var.project}-drift-detector-dev"
  filename         = data.archive_file.drift_detector_zip.output_path
  source_code_hash = data.archive_file.drift_detector_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      ENVIRONMENT       = "dev"
      STATE_BUCKET      = aws_s3_bucket.state_dev.bucket
      AWS_REGION_TARGET = var.aws_region_dev
    }
  }
  tags = merge(local.tags, { Environment = "dev" })
}

# ─── LAMBDA FUNCTIONS — DRIFT REMEDIATOR ──────────────────────────────────────
resource "aws_lambda_function" "drift_remediator_prod" {
  provider         = aws.prod
  function_name    = "${var.project}-drift-remediator-prod"
  filename         = data.archive_file.drift_remediator_zip.output_path
  source_code_hash = data.archive_file.drift_remediator_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 300
  memory_size      = 256
  environment {
    variables = {
      ENVIRONMENT       = "prod"
      PROJECT           = var.project
      STATE_BUCKET      = aws_s3_bucket.state_prod.bucket
      AWS_REGION_TARGET = var.aws_region_prod
    }
  }
  tags = merge(local.tags, { Environment = "prod" })
}

resource "aws_lambda_function" "drift_remediator_dev" {
  provider         = aws.dev
  function_name    = "${var.project}-drift-remediator-dev"
  filename         = data.archive_file.drift_remediator_zip.output_path
  source_code_hash = data.archive_file.drift_remediator_zip.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  role             = aws_iam_role.lambda_role.arn
  timeout          = 300
  memory_size      = 256
  environment {
    variables = {
      ENVIRONMENT       = "dev"
      PROJECT           = var.project
      STATE_BUCKET      = aws_s3_bucket.state_dev.bucket
      AWS_REGION_TARGET = var.aws_region_dev
    }
  }
  tags = merge(local.tags, { Environment = "dev" })
}

# ─── DEMO EC2 INSTANCES (t3.nano, one per region, for drift demos) ─────────────
resource "aws_instance" "demo_prod" {
  provider               = aws.prod
  ami                    = data.aws_ami.amazon_linux_prod.id
  instance_type          = "t3.nano"
  vpc_security_group_ids = [aws_security_group.demo_prod.id]
  tags                   = merge(local.tags, { Name = "drift-demo-prod", Environment = "prod" })
}

resource "aws_instance" "demo_dev" {
  provider               = aws.dev
  ami                    = data.aws_ami.amazon_linux_dev.id
  instance_type          = "t3.nano"
  vpc_security_group_ids = [aws_security_group.demo_dev.id]
  tags                   = merge(local.tags, { Name = "drift-demo-dev", Environment = "dev" })
}

# ─── SECURITY GROUPS FOR DEMO INSTANCES ───────────────────────────────────────
resource "aws_security_group" "demo_prod" {
  provider    = aws.prod
  name        = "${var.project}-demo-sg-prod"
  description = "Drift demo security group prod"
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.project}-demo-sg-prod", Environment = "prod" })
}

resource "aws_security_group" "demo_dev" {
  provider    = aws.dev
  name        = "${var.project}-demo-sg-dev"
  description = "Drift demo security group dev"
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = merge(local.tags, { Name = "${var.project}-demo-sg-dev", Environment = "dev" })
}

# ─── AMI DATA SOURCES ──────────────────────────────────────────────────────────
data "aws_ami" "amazon_linux_prod" {
  provider    = aws.prod
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "aws_ami" "amazon_linux_dev" {
  provider    = aws.dev
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "aws_caller_identity" "current" {}
