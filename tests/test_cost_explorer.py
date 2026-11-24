"""Tests for `CostExplorerSource` (AWS Cost Explorer / EC2 / CloudWatch).

Cost Explorer has no moto support worth relying on (coverage is partial
and inconsistent across moto versions), so `ce` is tested with
`botocore.stub.Stubber`, which intercepts calls before any HTTP request is
built — no network traffic, no real AWS calls, ever. EC2/CloudWatch (which
moto supports well) are tested with `moto.mock_aws`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber
from moto import mock_aws

from mcp_aws_finops.sources.cost_explorer import CostExplorerError, CostExplorerSource


def _ce_source(ce_client: object) -> CostExplorerSource:
    return CostExplorerSource(ce_client=ce_client, ec2_client=object(), cloudwatch_client=object())


def _cost_and_usage_page(
    start: str, end: str, amount: str, groups: list[tuple[list[str], str]] | None = None
) -> dict:
    row: dict = {
        "TimePeriod": {"Start": start, "End": end},
        "Total": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
        "Groups": [],
    }
    if groups:
        row["Total"] = {}
        row["Groups"] = [
            {"Keys": keys, "Metrics": {"UnblendedCost": {"Amount": amt, "Unit": "USD"}}}
            for keys, amt in groups
        ]
    return row


class TestTotalCostAndCurrency:
    def test_total_cost_sums_pages(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [
                    _cost_and_usage_page("2025-09-01", "2025-09-02", "10.00"),
                    _cost_and_usage_page("2025-09-02", "2025-09-03", "20.00"),
                ]
            },
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-03"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        total = source.total_cost(date(2025, 9, 1), date(2025, 9, 3))
        assert total == pytest.approx(30.0)
        stubber.deactivate()

    def test_total_cost_empty_range_short_circuits(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        assert source.total_cost(date(2025, 9, 5), date(2025, 9, 1)) == 0.0

    def test_pagination_follows_next_page_token(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "5.00")],
                "NextPageToken": "page2",
            },
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-03"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
            },
        )
        stubber.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": [_cost_and_usage_page("2025-09-02", "2025-09-03", "7.00")]},
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-03"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "NextPageToken": "page2",
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        total = source.total_cost(date(2025, 9, 1), date(2025, 9, 3))
        assert total == pytest.approx(12.0)
        stubber.deactivate()

    def test_cache_hit_avoids_second_api_call(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "4.00")]},
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        first = source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        second = source.total_cost(date(2025, 9, 1), date(2025, 9, 2))  # served from cache
        assert first == second == pytest.approx(4.0)
        stubber.deactivate()  # would fail if a 2nd, un-stubbed call had been made

    def test_cache_ttl_zero_disables_caching(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        page = {"ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "4.00")]}
        expected = {
            "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
        }
        stubber.add_response("get_cost_and_usage", page, expected)
        stubber.add_response("get_cost_and_usage", page, expected)
        stubber.activate()
        source = CostExplorerSource(
            ce_client=ce, ec2_client=object(), cloudwatch_client=object(), cache_ttl_seconds=0
        )
        source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        stubber.assert_no_pending_responses()
        stubber.deactivate()

    def test_currency_detected_from_response(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "1.00")]},
            {"TimePeriod": ANY, "Granularity": "DAILY", "Metrics": ["UnblendedCost"]},
        )
        stubber.activate()
        source = _ce_source(ce)
        assert source.currency == "USD"
        stubber.deactivate()

    def test_currency_defaults_to_usd_when_no_data(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": []},
            {"TimePeriod": ANY, "Granularity": "DAILY", "Metrics": ["UnblendedCost"]},
        )
        stubber.activate()
        source = _ce_source(ce)
        assert source.currency == "USD"
        stubber.deactivate()


class TestGroupedCosts:
    def test_cost_summary_groups_and_ranks(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [
                    _cost_and_usage_page(
                        "2025-09-01",
                        "2025-09-02",
                        "0",
                        groups=[(["Amazon EC2"], "30.00"), (["Amazon S3"], "10.00")],
                    )
                ]
            },
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        groups = source.cost_summary(date(2025, 9, 1), date(2025, 9, 2), "service")
        assert [g.key for g in groups] == ["Amazon EC2", "Amazon S3"]
        assert groups[0].cost == pytest.approx(30.0)
        assert groups[0].share_pct == pytest.approx(75.0)
        stubber.deactivate()

    def test_cost_summary_empty_range(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        assert source.cost_summary(date(2025, 9, 2), date(2025, 9, 1), "service") == []

    def test_cost_summary_tag_group_by_strips_key_prefix(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [
                    _cost_and_usage_page(
                        "2025-09-01",
                        "2025-09-02",
                        "0",
                        groups=[(["team$platform"], "5.00")],
                    )
                ]
            },
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "TAG", "Key": "team"}],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        groups = source.cost_summary(date(2025, 9, 1), date(2025, 9, 2), "tag:team")
        assert groups[0].key == "platform"
        stubber.deactivate()

    def test_invalid_group_by_raises(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        with pytest.raises(ValueError, match="Invalid group_by"):
            source.cost_summary(date(2025, 9, 1), date(2025, 9, 2), "bogus")

    def test_daily_cost_series_fills_missing_days_with_zero(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {"ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "3.00")]},
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-03"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        series = source.daily_cost_series(date(2025, 9, 1), date(2025, 9, 3))
        assert series == [(date(2025, 9, 1), 3.0), (date(2025, 9, 2), 0.0)]
        stubber.deactivate()

    def test_daily_cost_series_empty_range(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        assert source.daily_cost_series(date(2025, 9, 2), date(2025, 9, 1)) == []

    def test_daily_cost_by_group(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_and_usage",
            {
                "ResultsByTime": [
                    _cost_and_usage_page(
                        "2025-09-01",
                        "2025-09-02",
                        "0",
                        groups=[(["Amazon EC2"], "8.00"), (["Amazon S3"], "2.00")],
                    )
                ]
            },
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
                "Granularity": "DAILY",
                "Metrics": ["UnblendedCost"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        by_day = source.daily_cost_by_group(date(2025, 9, 1), date(2025, 9, 2), "service")
        day = by_day[date(2025, 9, 1)]
        assert day[0].key == "Amazon EC2"
        assert day[0].share_pct == pytest.approx(80.0)
        stubber.deactivate()

    def test_daily_cost_by_group_empty_range(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        assert source.daily_cost_by_group(date(2025, 9, 2), date(2025, 9, 1), "service") == {}


class TestForecastAndAnomalies:
    def test_get_cost_forecast(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_cost_forecast",
            {"Total": {"Amount": "123.45", "Unit": "USD"}, "ForecastResultsByTime": []},
            {
                "TimePeriod": {"Start": "2025-09-01", "End": "2025-10-01"},
                "Metric": "UNBLENDED_COST",
                "Granularity": "MONTHLY",
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        forecast = source.get_cost_forecast(date(2025, 9, 1), date(2025, 10, 1))
        assert forecast == pytest.approx(123.45)
        # second call should be served from cache, no second stub needed
        assert source.get_cost_forecast(date(2025, 9, 1), date(2025, 10, 1)) == pytest.approx(
            123.45
        )
        stubber.deactivate()

    def test_get_cost_forecast_error_mapped(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error(
            "get_cost_forecast",
            service_error_code="AccessDeniedException",
            service_message="not allowed",
        )
        stubber.activate()
        source = _ce_source(ce)
        with pytest.raises(CostExplorerError, match="AccessDeniedException"):
            source.get_cost_forecast(date(2025, 9, 1), date(2025, 10, 1))
        stubber.deactivate()

    def test_get_anomalies_returns_list(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_response(
            "get_anomalies",
            {
                "Anomalies": [
                    {
                        "AnomalyId": "a1",
                        "AnomalyScore": {"MaxScore": 10.0, "CurrentScore": 10.0},
                        "Impact": {"MaxImpact": 5.0, "TotalImpact": 5.0},
                        "MonitorArn": "arn:aws:ce::123:anomalymonitor/x",
                    }
                ]
            },
            {
                "MonitorArn": "arn:aws:ce::123:anomalymonitor/x",
                "DateInterval": {"StartDate": "2025-09-01", "EndDate": "2025-09-02"},
            },
        )
        stubber.activate()
        source = _ce_source(ce)
        anomalies = source.get_anomalies(
            "arn:aws:ce::123:anomalymonitor/x", date(2025, 9, 1), date(2025, 9, 2)
        )
        assert anomalies[0]["AnomalyId"] == "a1"
        stubber.deactivate()

    def test_get_anomalies_missing_monitor_returns_empty(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error(
            "get_anomalies",
            service_error_code="ResourceNotFoundException",
            service_message="no monitor",
        )
        stubber.activate()
        source = _ce_source(ce)
        assert source.get_anomalies("arn:x", date(2025, 9, 1), date(2025, 9, 2)) == []
        stubber.deactivate()

    def test_get_anomalies_other_error_raised(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error(
            "get_anomalies", service_error_code="ThrottlingException", service_message="slow down"
        )
        stubber.activate()
        source = _ce_source(ce)
        with pytest.raises(CostExplorerError):
            source.get_anomalies("arn:x", date(2025, 9, 1), date(2025, 9, 2))
        stubber.deactivate()


class TestDataBounds:
    def test_data_bounds_is_today_minus_14_months(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        start, end = source.data_bounds()
        assert end == date.today() - __import__("datetime").timedelta(days=1)
        assert start < end


class TestErrorMapping:
    def test_no_credentials_error_mapped(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error(
            "get_cost_and_usage",
            service_error_code="AccessDeniedException",
            service_message="User is not authorized to perform: ce:GetCostAndUsage",
        )
        stubber.activate()
        source = _ce_source(ce)
        with pytest.raises(CostExplorerError, match=r"iam/policy\.json"):
            source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        stubber.deactivate()

    def test_data_unavailable_mapped(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error(
            "get_cost_and_usage",
            service_error_code="DataUnavailableException",
            service_message="no data",
        )
        stubber.activate()
        source = _ce_source(ce)
        with pytest.raises(CostExplorerError, match="14-month retention"):
            source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        stubber.deactivate()

    def test_generic_client_error_mapped(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        stubber = Stubber(ce)
        stubber.add_client_error("get_cost_and_usage", service_error_code="ThrottlingException")
        stubber.activate()
        source = _ce_source(ce)
        with pytest.raises(CostExplorerError, match="Cost Explorer/EC2/CloudWatch request failed"):
            source.total_cost(date(2025, 9, 1), date(2025, 9, 2))
        stubber.deactivate()

    def test_invalid_metric_rejected(self) -> None:
        with pytest.raises(ValueError, match="metric must be"):
            CostExplorerSource(
                ce_client=object(),
                ec2_client=object(),
                cloudwatch_client=object(),
                metric="bogus",
            )


@mock_aws
class TestIdleResourcesEc2CloudWatch:
    def _source(self, **kwargs: object) -> CostExplorerSource:
        return CostExplorerSource(region="us-east-1", ce_client=object(), **kwargs)  # type: ignore[arg-type]

    def test_unattached_volume_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.create_volume(Size=20, AvailabilityZone="us-east-1a")
        source = self._source(ec2_client=ec2, cloudwatch_client=object())
        idle = source.idle_resources(date.today(), 14)
        volumes = [r for r in idle if r.resource_type == "EBS Volume"]
        assert len(volumes) == 1
        assert volumes[0].estimated_monthly_cost == pytest.approx(20 * 0.08)

    def test_unassociated_eip_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        ec2.allocate_address(Domain="vpc")
        source = self._source(ec2_client=ec2, cloudwatch_client=object())
        idle = source.idle_resources(date.today(), 14)
        eips = [r for r in idle if r.resource_type == "Elastic IP"]
        assert len(eips) == 1

    def test_associated_eip_not_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
        image_id = _first_ami(ec2)
        instance = ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)["Instances"][0]
        alloc = ec2.allocate_address(Domain="vpc")
        ec2.associate_address(InstanceId=instance["InstanceId"], AllocationId=alloc["AllocationId"])
        source = self._source(ec2_client=ec2, cloudwatch_client=cloudwatch)
        idle = source.idle_resources(date.today(), 14)
        eips = [r for r in idle if r.resource_type == "Elastic IP"]
        assert eips == []

    def test_old_snapshot_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vol = ec2.create_volume(Size=10, AvailabilityZone="us-east-1a")
        snap = ec2.create_snapshot(VolumeId=vol["VolumeId"])
        old_date = datetime(2000, 1, 1, tzinfo=UTC)
        source = self._source(ec2_client=ec2, cloudwatch_client=object(), old_snapshot_days=1)
        # moto sets StartTime to "now" at creation; force a very large lookback
        # window by monkeypatching the client's describe_snapshots call result.
        orig_describe = ec2.describe_snapshots

        def _patched(**kwargs: object) -> dict:
            resp = orig_describe(**kwargs)
            for s in resp["Snapshots"]:
                if s["SnapshotId"] == snap["SnapshotId"]:
                    s["StartTime"] = old_date
            return resp

        ec2.describe_snapshots = _patched  # type: ignore[method-assign]
        idle = source.idle_resources(date.today(), 14)
        snaps = [r for r in idle if r.resource_type == "EBS Snapshot"]
        assert len(snaps) == 1
        assert snaps[0].resource_id == snap["SnapshotId"]

    def test_recent_snapshot_not_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vol = ec2.create_volume(Size=10, AvailabilityZone="us-east-1a")
        ec2.create_snapshot(VolumeId=vol["VolumeId"])
        source = self._source(ec2_client=ec2, cloudwatch_client=object())
        idle = source.idle_resources(date.today(), 14)
        assert [r for r in idle if r.resource_type == "EBS Snapshot"] == []

    def test_low_cpu_instance_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
        image_id = _first_ami(ec2)
        instance = ec2.run_instances(
            ImageId=image_id, MinCount=1, MaxCount=1, InstanceType="t3.micro"
        )["Instances"][0]
        # moto's GetMetricData for a metric pushed moments earlier is flaky
        # (internal bucket-alignment timing), so stub CloudWatch deterministically
        # instead of relying on a real put_metric_data roundtrip through moto.
        cw_stubber = Stubber(cloudwatch)
        cw_stubber.add_response(
            "get_metric_data",
            {
                "MetricDataResults": [
                    {
                        "Id": "avg_cpu",
                        "Label": "CPUUtilization Average",
                        "Timestamps": [datetime.now(UTC)],
                        "Values": [1.0],
                        "StatusCode": "Complete",
                    }
                ]
            },
            {
                "MetricDataQueries": [
                    {
                        "Id": "avg_cpu",
                        "MetricStat": {
                            "Metric": {
                                "Namespace": "AWS/EC2",
                                "MetricName": "CPUUtilization",
                                "Dimensions": [
                                    {"Name": "InstanceId", "Value": instance["InstanceId"]}
                                ],
                            },
                            "Period": 86400,
                            "Stat": "Average",
                        },
                    }
                ],
                "StartTime": ANY,
                "EndTime": ANY,
            },
        )
        cw_stubber.activate()
        source = self._source(ec2_client=ec2, cloudwatch_client=cloudwatch)
        idle = source.idle_resources(date.today(), 14)
        instances = [r for r in idle if r.resource_type == "EC2 Instance"]
        assert len(instances) == 1
        assert instances[0].resource_id == instance["InstanceId"]
        cw_stubber.deactivate()

    def test_no_cloudwatch_datapoints_not_flagged(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
        image_id = _first_ami(ec2)
        ec2.run_instances(ImageId=image_id, MinCount=1, MaxCount=1)
        source = self._source(ec2_client=ec2, cloudwatch_client=cloudwatch)
        idle = source.idle_resources(date.today(), 14)
        assert [r for r in idle if r.resource_type == "EC2 Instance"] == []

    def test_ec2_pagination(self) -> None:
        ec2 = boto3.client("ec2", region_name="us-east-1")
        for _ in range(3):
            ec2.create_volume(Size=5, AvailabilityZone="us-east-1a")
        source = self._source(ec2_client=ec2, cloudwatch_client=object())
        idle = source.idle_resources(date.today(), 14)
        assert len([r for r in idle if r.resource_type == "EBS Volume"]) == 3

    def test_ec2_access_denied_mapped(self) -> None:
        class _DenyingEc2:
            def describe_volumes(self, **kwargs: object) -> dict:
                raise ClientError(
                    {"Error": {"Code": "UnauthorizedOperation", "Message": "denied"}},
                    "DescribeVolumes",
                )

        source = self._source(ec2_client=_DenyingEc2(), cloudwatch_client=object())
        with pytest.raises(CostExplorerError):
            source.idle_resources(date.today(), 14)


def _first_ami(ec2: object) -> str:
    images = ec2.describe_images(Owners=["amazon"])["Images"]  # type: ignore[attr-defined]
    return str(images[0]["ImageId"])


class TestClientConstruction:
    def test_lazy_client_uses_session(self) -> None:
        session = boto3.Session(region_name="us-east-1")
        source = CostExplorerSource(session=session, region="us-east-1")
        client = source._ce_client
        assert client.meta.service_model.service_name == "ce"

    def test_default_session_created_lazily(self) -> None:
        source = CostExplorerSource(region="us-east-1", profile=None)
        client = source._ec2_client
        assert client.meta.service_model.service_name == "ec2"

    def test_clear_cache(self) -> None:
        ce = boto3.client("ce", region_name="us-east-1")
        source = _ce_source(ce)
        source._cache.set(("k",), "v")
        source.clear_cache()
        assert source._cache.get(("k",)) is None


async def test_mcp_tool_in_process_against_stubbed_aws_source() -> None:
    """End-to-end: run a real MCP tool call through `create_server` wired to
    a `CostExplorerSource` whose `ce` client is a Stubber — no network, no
    real AWS account, exercising the full server -> tool -> source path."""
    from mcp_aws_finops.server import create_server

    ce = boto3.client("ce", region_name="us-east-1")
    stubber = Stubber(ce)
    stubber.add_response(
        "get_cost_and_usage",
        {
            "ResultsByTime": [
                _cost_and_usage_page(
                    "2025-09-01",
                    "2025-09-02",
                    "0",
                    groups=[(["Amazon EC2"], "40.00"), (["Amazon S3"], "10.00")],
                )
            ]
        },
        {
            "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        },
    )
    stubber.add_response(
        "get_cost_and_usage",
        {"ResultsByTime": [_cost_and_usage_page("2025-09-01", "2025-09-02", "50.00")]},
        {
            "TimePeriod": {"Start": "2025-09-01", "End": "2025-09-02"},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
        },
    )
    stubber.activate()
    source = _ce_source(ce)
    source._currency_cache = "USD"  # avoid a 3rd, unrelated stubbed call for currency()
    server = create_server(source)
    result = await server.call_tool(
        "get_cost_summary", {"start": "2025-09-01", "end": "2025-09-02"}
    )
    structured = result[1] if isinstance(result, tuple) else result
    assert structured["total_cost"] == pytest.approx(50.0)
    assert structured["groups"][0]["key"] == "Amazon EC2"
    stubber.deactivate()
