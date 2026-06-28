output "state_bucket_prod" { value = aws_s3_bucket.state_prod.bucket }
output "state_bucket_dev"  { value = aws_s3_bucket.state_dev.bucket }

output "lambda_detector_prod_arn"   { value = aws_lambda_function.drift_detector_prod.arn }
output "lambda_detector_dev_arn"    { value = aws_lambda_function.drift_detector_dev.arn }
output "lambda_classifier_arn"      { value = aws_lambda_function.drift_classifier.arn }
output "status_function_url"        { value = aws_lambda_function_url.drift_status.function_url }
output "lambda_remediator_prod_arn" { value = aws_lambda_function.drift_remediator_prod.arn }
output "lambda_remediator_dev_arn"  { value = aws_lambda_function.drift_remediator_dev.arn }

output "demo_instance_id_prod" { value = aws_instance.demo_prod.id }
output "demo_instance_id_dev"  { value = aws_instance.demo_dev.id }

output "demo_sg_id_prod" { value = aws_security_group.demo_prod.id }
output "demo_sg_id_dev"  { value = aws_security_group.demo_dev.id }

output "superplane_aws_access_key_id" { value = aws_iam_access_key.superplane.id }
output "superplane_aws_secret_access_key" {
  value     = aws_iam_access_key.superplane.secret
  sensitive = true
}
