import boto3
import json
import os
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    environment  = os.environ.get('ENVIRONMENT', event.get('environment', 'unknown'))
    region       = os.environ.get('AWS_REGION_TARGET', event.get('region', 'us-east-1'))
    drifts       = event.get('drifts', [])
    approved_by  = event.get('approved_by', 'superplane-workflow')

    logger.info(f"Starting remediation: env={environment} approved_by={approved_by}")

    ec2 = boto3.client('ec2', region_name=region)
    results = []

    for drift in drifts:
        resource_type  = drift.get('resource_type')
        resource_id    = drift.get('resource_id')
        attribute      = drift.get('attribute')
        desired_value  = drift.get('desired')

        try:
            if resource_type == 'aws_instance' and attribute == 'instance_type':
                ec2.stop_instances(InstanceIds=[resource_id])
                waiter = ec2.get_waiter('instance_stopped')
                waiter.wait(InstanceIds=[resource_id])
                ec2.modify_instance_attribute(
                    InstanceId=resource_id,
                    InstanceType={'Value': desired_value}
                )
                ec2.start_instances(InstanceIds=[resource_id])
                results.append({
                    "resource_id": resource_id,
                    "attribute": attribute,
                    "action": "instance_type_restored",
                    "restored_to": desired_value,
                    "status": "success"
                })

            elif resource_type == 'aws_security_group' and attribute == 'ingress_rule_count':
                sg_response = ec2.describe_security_groups(GroupIds=[resource_id])
                sg = sg_response['SecurityGroups'][0]
                if sg['IpPermissions']:
                    ec2.revoke_security_group_ingress(
                        GroupId=resource_id,
                        IpPermissions=sg['IpPermissions']
                    )
                results.append({
                    "resource_id": resource_id,
                    "attribute": attribute,
                    "action": "ingress_rules_revoked",
                    "status": "success"
                })

            else:
                results.append({
                    "resource_id": resource_id,
                    "attribute": attribute,
                    "action": "no_remediation_available",
                    "status": "skipped"
                })

        except Exception as e:
            logger.error(f"Remediation failed for {resource_id}: {e}")
            results.append({
                "resource_id": resource_id,
                "attribute": attribute,
                "action": "remediation_failed",
                "error": str(e),
                "status": "error"
            })

    return {
        "environment": environment,
        "region": region,
        "approved_by": approved_by,
        "remediation_results": results,
        "success_count": len([r for r in results if r['status'] == 'success']),
        "error_count":   len([r for r in results if r['status'] == 'error'])
    }
