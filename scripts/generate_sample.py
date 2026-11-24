"""Deterministic generator for the bundled FOCUS sample dataset.

Produces ~3 months of synthetic but realistic-looking AWS billing data in
FOCUS format, covering EC2, EKS, RDS, S3, Lambda, CloudWatch, NAT Gateway,
EBS (including unattached volumes and old snapshots), Elastic IPs, and
tagged with team/project/env (some resources deliberately left untagged).
One day gets a deliberate cost spike (an EC2 scale-out) for the
`explain_anomaly` tool to find.

Usage:
    uv run python scripts/generate_sample.py [output_path]

The output defaults to src/mcp_aws_finops/data/sample_focus.parquet.
Re-running with the same code always produces byte-identical data because
every random draw goes through a single seeded `random.Random(42)`.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

SEED = 42
START_DATE = date(2025, 7, 1)
NUM_DAYS = 92  # ~3 months
ACCOUNTS = [
    ("111111111111", "platform-prod"),
    ("222222222222", "platform-staging"),
    ("333333333333", "data-prod"),
]
REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]
TEAMS = ["payments", "search", "data-platform", "growth"]
PROJECTS = ["checkout", "catalog", "etl-pipeline", "web-frontend"]
ENVS = ["prod", "staging", "dev"]
SPIKE_DATE = START_DATE + timedelta(days=55)


@dataclass
class Row:
    billed_cost: float
    effective_cost: float
    billing_currency: str
    service_name: str
    service_category: str
    charge_category: str
    charge_period_start: str
    charge_period_end: str
    region_id: str | None
    sub_account_id: str
    sub_account_name: str
    resource_id: str
    resource_type: str
    pricing_unit: str
    consumed_quantity: float
    usage_amount: float
    tags: str
    x_attached: bool | None
    x_associated_instance_id: str | None
    x_age_days: int | None
    x_avg_cpu_utilization: float | None


def _tags(rng: random.Random, *, untagged: bool = False) -> str:
    if untagged:
        return "{}"
    return json.dumps(
        {
            "team": rng.choice(TEAMS),
            "project": rng.choice(PROJECTS),
            "env": rng.choice(ENVS),
        }
    )


def _charge_window(day: date) -> tuple[str, str]:
    start = f"{day.isoformat()}T00:00:00Z"
    end = f"{(day + timedelta(days=1)).isoformat()}T00:00:00Z"
    return start, end


def _base_row(
    day: date,
    *,
    account: tuple[str, str],
    region: str | None,
    service_name: str,
    service_category: str,
    charge_category: str,
    resource_id: str,
    resource_type: str,
    pricing_unit: str,
    cost: float,
    quantity: float,
    tags: str,
) -> Row:
    start, end = _charge_window(day)
    return Row(
        billed_cost=round(cost, 6),
        effective_cost=round(cost, 6),
        billing_currency="USD",
        service_name=service_name,
        service_category=service_category,
        charge_category=charge_category,
        charge_period_start=start,
        charge_period_end=end,
        region_id=region,
        sub_account_id=account[0],
        sub_account_name=account[1],
        resource_id=resource_id,
        resource_type=resource_type,
        pricing_unit=pricing_unit,
        consumed_quantity=round(quantity, 4),
        usage_amount=round(quantity, 4),
        tags=tags,
        x_attached=None,
        x_associated_instance_id=None,
        x_age_days=None,
        x_avg_cpu_utilization=None,
    )


def generate_rows() -> list[Row]:
    rng = random.Random(SEED)
    rows: list[Row] = []

    # Stable fleets of resources per account/region so costs are coherent day to day.
    ec2_fleet = [
        {
            "id": f"i-{rng.randrange(16**12):012x}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "hourly": rng.uniform(0.05, 1.2),
            "cpu": rng.uniform(1.0, 60.0),
            "untagged": rng.random() < 0.15,
        }
        for _ in range(14)
    ]
    rds_fleet = [
        {
            "id": f"db-{rng.randrange(16**10):010x}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "hourly": rng.uniform(0.2, 1.8),
            "cpu": rng.uniform(1.0, 50.0),
            "untagged": rng.random() < 0.1,
        }
        for _ in range(5)
    ]
    eks_clusters = [
        {
            "id": f"eks-cluster-{i}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "daily": rng.uniform(15.0, 40.0),
        }
        for i in range(3)
    ]
    s3_buckets = [
        {
            "id": f"s3-bucket-{name}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "gb": rng.uniform(500, 8000),
            "untagged": rng.random() < 0.2,
        }
        for name in ["logs", "data-lake", "backups", "static-assets"]
    ]
    nat_gateways = [
        {
            "id": f"nat-{rng.randrange(16**8):08x}",
            "account": a,
            "region": r,
        }
        for a in ACCOUNTS
        for r in rng.sample(REGIONS, 2)
    ]
    ebs_volumes = [
        {
            "id": f"vol-{rng.randrange(16**12):012x}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "gb": rng.choice([50, 100, 200, 500]),
            "attached": rng.random() > 0.2,  # ~20% unattached -> idle
            "untagged": rng.random() < 0.3,
        }
        for _ in range(10)
    ]
    snapshots = [
        {
            "id": f"snap-{rng.randrange(16**12):012x}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "gb": rng.choice([20, 50, 100]),
            "created_offset": rng.randint(5, 400),
        }
        for _ in range(8)
    ]
    elastic_ips = [
        {
            "id": f"eipalloc-{rng.randrange(16**8):08x}",
            "account": rng.choice(ACCOUNTS),
            "region": rng.choice(REGIONS),
            "associated": rng.random() > 0.3,  # ~30% idle
        }
        for _ in range(6)
    ]

    for i in range(NUM_DAYS):
        day = START_DATE + timedelta(days=i)
        spike = day == SPIKE_DATE

        for ec2 in ec2_fleet:
            hours = 24.0
            hourly = ec2["hourly"] * (4.0 if spike else 1.0)
            tags = _tags(rng, untagged=ec2["untagged"])
            row = _base_row(
                day,
                account=ec2["account"],
                region=ec2["region"],
                service_name="Amazon EC2",
                service_category="Compute",
                charge_category="Usage",
                resource_id=ec2["id"],
                resource_type="EC2 Instance",
                pricing_unit="Hour",
                cost=hourly * hours,
                quantity=hours,
                tags=tags,
            )
            row.x_avg_cpu_utilization = round(ec2["cpu"] + rng.uniform(-2, 2), 2)
            rows.append(row)

        for rds in rds_fleet:
            hours = 24.0
            tags = _tags(rng, untagged=rds["untagged"])
            row = _base_row(
                day,
                account=rds["account"],
                region=rds["region"],
                service_name="Amazon RDS",
                service_category="Database",
                charge_category="Usage",
                resource_id=rds["id"],
                resource_type="RDS Instance",
                pricing_unit="Hour",
                cost=rds["hourly"] * hours,
                quantity=hours,
                tags=tags,
            )
            row.x_avg_cpu_utilization = round(rds["cpu"] + rng.uniform(-2, 2), 2)
            rows.append(row)

        for eks in eks_clusters:
            rows.append(
                _base_row(
                    day,
                    account=eks["account"],
                    region=eks["region"],
                    service_name="Amazon EKS",
                    service_category="Compute",
                    charge_category="Usage",
                    resource_id=eks["id"],
                    resource_type="EKS Cluster",
                    pricing_unit="Hour",
                    cost=eks["daily"],
                    quantity=24.0,
                    tags=_tags(rng),
                )
            )

        for bucket in s3_buckets:
            tags = _tags(rng, untagged=bucket["untagged"])
            cost = bucket["gb"] * 0.023 / 30.0
            rows.append(
                _base_row(
                    day,
                    account=bucket["account"],
                    region=bucket["region"],
                    service_name="Amazon S3",
                    service_category="Storage",
                    charge_category="Usage",
                    resource_id=bucket["id"],
                    resource_type="S3 Bucket",
                    pricing_unit="GB-Month",
                    cost=cost,
                    quantity=bucket["gb"] / 30.0,
                    tags=tags,
                )
            )

        # Lambda: lots of small invocations
        lambda_cost = rng.uniform(3.0, 9.0)
        rows.append(
            _base_row(
                day,
                account=rng.choice(ACCOUNTS),
                region=rng.choice(REGIONS),
                service_name="AWS Lambda",
                service_category="Compute",
                charge_category="Usage",
                resource_id="lambda-functions-aggregate",
                resource_type="Lambda Function",
                pricing_unit="Request",
                cost=lambda_cost,
                quantity=rng.uniform(1_000_000, 4_000_000),
                tags=_tags(rng),
            )
        )

        # CloudWatch: logs + metrics, small steady cost
        rows.append(
            _base_row(
                day,
                account=rng.choice(ACCOUNTS),
                region=rng.choice(REGIONS),
                service_name="Amazon CloudWatch",
                service_category="Management",
                charge_category="Usage",
                resource_id="cloudwatch-logs-aggregate",
                resource_type="CloudWatch Logs",
                pricing_unit="GB",
                cost=rng.uniform(1.0, 4.0),
                quantity=rng.uniform(5, 20),
                tags=_tags(rng),
            )
        )

        for nat in nat_gateways:
            rows.append(
                _base_row(
                    day,
                    account=nat["account"],
                    region=nat["region"],
                    service_name="Amazon VPC",
                    service_category="Networking",
                    charge_category="Usage",
                    resource_id=nat["id"],
                    resource_type="NAT Gateway",
                    pricing_unit="Hour",
                    cost=0.045 * 24.0 + rng.uniform(0.5, 3.0),
                    quantity=24.0,
                    tags=_tags(rng),
                )
            )

        for vol in ebs_volumes:
            tags = _tags(rng, untagged=vol["untagged"])
            cost = vol["gb"] * 0.10 / 30.0
            row = _base_row(
                day,
                account=vol["account"],
                region=vol["region"],
                service_name="Amazon EBS",
                service_category="Storage",
                charge_category="Usage",
                resource_id=vol["id"],
                resource_type="EBS Volume",
                pricing_unit="GB-Month",
                cost=cost,
                quantity=vol["gb"] / 30.0,
                tags=tags,
            )
            row.x_attached = vol["attached"]
            rows.append(row)

        for snap in snapshots:
            age = (day - START_DATE).days + snap["created_offset"]
            cost = snap["gb"] * 0.05 / 30.0
            row = _base_row(
                day,
                account=snap["account"],
                region=snap["region"],
                service_name="Amazon EBS",
                service_category="Storage",
                charge_category="Usage",
                resource_id=snap["id"],
                resource_type="EBS Snapshot",
                pricing_unit="GB-Month",
                cost=cost,
                quantity=snap["gb"] / 30.0,
                tags=_tags(rng),
            )
            row.x_age_days = age
            rows.append(row)

        for eip in elastic_ips:
            cost = 0.0 if eip["associated"] else (0.005 * 24.0)
            row = _base_row(
                day,
                account=eip["account"],
                region=eip["region"],
                service_name="Amazon VPC",
                service_category="Networking",
                charge_category="Usage",
                resource_id=eip["id"],
                resource_type="Elastic IP",
                pricing_unit="Hour",
                cost=cost,
                quantity=24.0,
                tags=_tags(rng),
            )
            row.x_associated_instance_id = ec2_fleet[0]["id"] if eip["associated"] else None
            rows.append(row)

    return rows


def main(output_path: str | None = None) -> None:
    out = (
        Path(output_path)
        if output_path
        else Path(__file__).parent.parent / ("src/mcp_aws_finops/data/sample_focus.parquet")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = generate_rows()
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE costs AS SELECT * FROM (SELECT "
        "unnest(rows, recursive := true) FROM (SELECT $rows AS rows))",
        {"rows": [r.__dict__ for r in rows]},
    )
    # Rename columns to FOCUS PascalCase names.
    rename_map = {
        "billed_cost": "BilledCost",
        "effective_cost": "EffectiveCost",
        "billing_currency": "BillingCurrency",
        "service_name": "ServiceName",
        "service_category": "ServiceCategory",
        "charge_category": "ChargeCategory",
        "charge_period_start": "ChargePeriodStart",
        "charge_period_end": "ChargePeriodEnd",
        "region_id": "RegionId",
        "sub_account_id": "SubAccountId",
        "sub_account_name": "SubAccountName",
        "resource_id": "ResourceId",
        "resource_type": "ResourceType",
        "pricing_unit": "PricingUnit",
        "consumed_quantity": "ConsumedQuantity",
        "usage_amount": "UsageAmount",
        "tags": "Tags",
        "x_attached": "x_Attached",
        "x_associated_instance_id": "x_AssociatedInstanceId",
        "x_age_days": "x_AgeDays",
        "x_avg_cpu_utilization": "x_AvgCpuUtilization",
    }
    for old, new in rename_map.items():
        con.execute(f'ALTER TABLE costs RENAME COLUMN "{old}" TO "{new}"')
    con.execute(f"COPY costs TO '{out}' (FORMAT parquet)")
    n = con.execute("SELECT COUNT(*) FROM costs").fetchone()
    size_kb = out.stat().st_size / 1024
    print(f"Wrote {n[0] if n else 0} rows to {out} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
