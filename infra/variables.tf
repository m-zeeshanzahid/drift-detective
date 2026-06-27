variable "aws_region_prod"    { default = "us-east-1" }
variable "aws_region_staging" { default = "us-west-2" } # staging removed; provider kept only for clean destroy
variable "aws_region_dev"     { default = "us-east-1" } # moved from eu-west-1 → us-east-1
variable "project"            { default = "drift-detective" }
variable "environment"        { default = "dev" }
