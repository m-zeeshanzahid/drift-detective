import boto3
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def get_desired_state(bucket: str, region: str) -> dict:
    s3 = boto3.client('s3', region_name=region)
    obj = s3.get_object(Bucket=bucket, Key='desired_state.json')
    return json.loads(obj['Body'].read())


def check_ec2_drift(desired_instances: dict, region: str) -> list:
    ec2 = boto3.client('ec2', region_name=region)
    drifts = []

    if not desired_instances:
        return drifts

    instance_ids = list(desired_instances.keys())
    try:
        response = ec2.describe_instances(InstanceIds=instance_ids)
    except Exception as e:
        logger.error(f"Error describing instances: {e}")
        return [{
            "resource_type": "ec2_instance",
            "resource_id": iid,
            "attribute": "existence",
            "desired": "present",
            "actual": "not_found_or_error",
            "severity": "critical"
        } for iid in instance_ids]

    actual_instances = {}
    for reservation in response.get('Reservations', []):
        for inst in reservation.get('Instances', []):
            actual_instances[inst['InstanceId']] = {
                "instance_type": inst.get('InstanceType'),
                "state": inst.get('State', {}).get('Name'),
                "tags": {t['Key']: t['Value'] for t in inst.get('Tags', [])}
            }

    for instance_id, desired_attrs in desired_instances.items():
        if instance_id not in actual_instances:
            drifts.append({
                "resource_type": "aws_instance",
                "resource_id": instance_id,
                "attribute": "existence",
                "desired": "present",
                "actual": "missing",
                "severity": "critical"
            })
            continue

        actual = actual_instances[instance_id]
        for attr in ['instance_type', 'state']:
            if attr in desired_attrs and actual.get(attr) != desired_attrs[attr]:
                severity = "critical" if attr == "state" else "suspicious"
                drifts.append({
                    "resource_type": "aws_instance",
                    "resource_id": instance_id,
                    "attribute": attr,
                    "desired": desired_attrs[attr],
                    "actual": actual.get(attr),
                    "severity": severity
                })

    return drifts


def check_security_group_drift(desired_sgs: dict, region: str) -> list:
    ec2 = boto3.client('ec2', region_name=region)
    drifts = []

    if not desired_sgs:
        return drifts

    sg_ids = list(desired_sgs.keys())
    try:
        response = ec2.describe_security_groups(GroupIds=sg_ids)
    except Exception as e:
        logger.error(f"Error describing security groups: {e}")
        return []

    for sg in response.get('SecurityGroups', []):
        sg_id = sg['GroupId']
        if sg_id not in desired_sgs:
            continue

        desired = desired_sgs[sg_id]
        actual_ingress_count = len(sg.get('IpPermissions', []))
        desired_ingress_count = len(desired.get('ingress_rules', []))

        if actual_ingress_count != desired_ingress_count:
            drifts.append({
                "resource_type": "aws_security_group",
                "resource_id": sg_id,
                "attribute": "ingress_rule_count",
                "desired": desired_ingress_count,
                "actual": actual_ingress_count,
                "severity": "critical",
                "detail": (
                    f"Security group has {actual_ingress_count} ingress rules, "
                    f"expected {desired_ingress_count}"
                )
            })

    return drifts


def format_drift_summary(drifts: list) -> str:
    if not drifts:
        return "No drift detected."

    lines = []
    for d in drifts:
        lines.append(
            f"- [{d['resource_type']}] {d['resource_id']}: "
            f"{d['attribute']} — desired '{d['desired']}', actual '{d['actual']}'"
        )
    return "\n".join(lines)


def lambda_handler(event, context):
    environment = os.environ.get('ENVIRONMENT', event.get('environment', 'unknown'))
    region = os.environ.get('AWS_REGION_TARGET', event.get('region', 'us-east-1'))
    bucket = os.environ.get('STATE_BUCKET', event.get('state_bucket'))

    logger.info(f"Starting drift detection: env={environment} region={region} bucket={bucket}")

    try:
        desired_state = get_desired_state(bucket, region)
    except Exception as e:
        return {
            "environment": environment,
            "region": region,
            "status": "error",
            "error": str(e),
            "drift_count": 0,
            "drifts": [],
            "has_drift": False
        }

    resources = desired_state.get('resources', {})
    all_drifts = []
    all_drifts.extend(check_ec2_drift(resources.get('ec2_instances', {}), region))
    all_drifts.extend(check_security_group_drift(resources.get('security_groups', {}), region))

    has_critical   = any(d.get('severity') == 'critical' for d in all_drifts)
    has_suspicious = any(d.get('severity') == 'suspicious' for d in all_drifts)

    if has_critical:
        classification = "critical"
    elif has_suspicious:
        classification = "suspicious"
    elif all_drifts:
        classification = "suspicious"
    else:
        classification = "safe"

    result = {
        "environment": environment,
        "region": region,
        "has_drift": len(all_drifts) > 0,
        "drift_count": len(all_drifts),
        "classification": classification,
        "drifts": all_drifts,
        "drift_summary": format_drift_summary(all_drifts),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "state_bucket": bucket
    }

    logger.info(f"Drift detection complete: {json.dumps(result)}")
    return result
