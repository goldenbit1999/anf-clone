"""ARM 앞단 규칙: api-version, 이름, 리소스 ID (계정 설계 §4)."""

import pytest

from anf_api.arm_rules import (
    ACCOUNT_TYPE,
    API_VERSION,
    ArmError,
    account_id,
    check_account_name,
    check_api_version,
    check_resource_group_name,
    operation_path,
)


def test_supported_api_version_passes():
    assert API_VERSION == "2026-08-01"
    check_api_version("2026-08-01")


def test_missing_api_version_is_400_missing_parameter():
    with pytest.raises(ArmError) as e:
        check_api_version(None)
    assert (e.value.status, e.value.code) == (400, "MissingApiVersionParameter")


@pytest.mark.parametrize("version", ["2026-08-15-preview", "2025-01-01", ""])
def test_other_api_version_is_400_no_registered_provider(version):
    with pytest.raises(ArmError) as e:
        check_api_version(version)
    assert (e.value.status, e.value.code) == (400, "NoRegisteredProviderFound")
    assert "2026-08-01" in e.value.message


@pytest.mark.parametrize("name", ["a", "acc1", "my-account_01", "A" * 128, "0abc"])
def test_valid_account_names_pass(name):
    check_account_name(name)


@pytest.mark.parametrize("name", ["", "-abc", "_abc", "a.b", "a b", "A" * 129, "abc\n"])
def test_invalid_account_names_are_400_invalid_resource_name(name):
    with pytest.raises(ArmError) as e:
        check_account_name(name)
    assert (e.value.status, e.value.code) == (400, "InvalidResourceName")


@pytest.mark.parametrize("name", ["rg", "my-rg.1", "rg_(test)", "r" * 90])
def test_valid_resource_group_names_pass(name):
    check_resource_group_name(name)


@pytest.mark.parametrize("name", ["", "r" * 91, "rg/x", "rg x"])
def test_invalid_resource_group_names_are_400(name):
    with pytest.raises(ArmError) as e:
        check_resource_group_name(name)
    assert (e.value.status, e.value.code) == (400, "InvalidResourceName")


def test_account_id_follows_arm_path():
    assert ACCOUNT_TYPE == "Microsoft.NetApp/netAppAccounts"
    assert account_id("sub1", "rg1", "acc1") == (
        "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
    )


def test_operation_path_is_subscription_and_region_scoped():
    assert operation_path("sub1", "westus2", "op-1") == (
        "/subscriptions/sub1/providers/Microsoft.NetApp/locations/westus2/operationResults/op-1"
    )


def test_arm_error_renders_error_body():
    err = ArmError(404, "ResourceNotFound", "not found")
    assert err.body() == {"error": {"code": "ResourceNotFound", "message": "not found"}}
