"""ARM 앞단 규칙: api-version, 이름, 리소스 ID, 공통 오류 (계정 설계 §4, 풀 설계 §4)."""

import pytest

from anf_api.arm_rules import (
    ACCOUNT_TYPE,
    API_VERSION,
    POOL_TYPE,
    ArmError,
    account_id,
    check_account_name,
    check_api_version,
    check_pool_name,
    check_resource_group_name,
    check_tags,
    invalid_content,
    location_conflict,
    not_found,
    operation_path,
    pool_id,
    unknown_property,
    unsupported_property,
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


# --- 용량 풀 (풀 설계 §4) ---

@pytest.mark.parametrize("name", ["p", "pool1", "my-pool_01", "P" * 64, "0p"])
def test_valid_pool_names_pass(name):
    check_pool_name(name)


@pytest.mark.parametrize("name", ["", "-p", "_p", "a.b", "a b", "P" * 65])
def test_invalid_pool_names_are_400_invalid_resource_name(name):
    with pytest.raises(ArmError) as e:
        check_pool_name(name)
    assert (e.value.status, e.value.code) == (400, "InvalidResourceName")
    assert "capacity pool" in e.value.message


def test_pool_id_nests_under_account():
    assert POOL_TYPE == "Microsoft.NetApp/netAppAccounts/capacityPools"
    assert pool_id("sub1", "rg1", "acc1", "pool1") == (
        "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.NetApp/netAppAccounts/acc1"
        "/capacityPools/pool1"
    )


def test_not_found_uses_rp_message():
    err = not_found("/subscriptions/s/x")
    assert (err.status, err.code) == (404, "ResourceNotFound")
    assert err.message == "The resource with identifier '/subscriptions/s/x' is not found."


def test_location_conflict_is_409_invalid_resource_location():
    err = location_conflict("acc1", "rg1", "westus2", "eastus")
    assert (err.status, err.code) == (409, "InvalidResourceLocation")
    assert "'westus2'" in err.message and "'eastus'" in err.message


# --- 본문 검사 공통 오류 (계정 설계 §4.3, 풀 설계 §4.3) ---

def test_body_errors_are_400_invalid_request_content():
    assert (invalid_content("bad").status, invalid_content("bad").code) == (400, "InvalidRequestContent")
    # ANF RP 오류 문서의 문구 [계정 브리프 문서 12]
    assert unknown_property("properties.x").message == (
        "Value received for an unknown property 'properties.x'.")
    err = unsupported_property("properties.coolAccess")
    assert err.code == "InvalidRequestContent"
    assert err.message == "The property 'properties.coolAccess' is not supported by this ANF clone."


def test_check_tags_accepts_string_map():
    assert check_tags({"a": "1"}) == {"a": "1"}


@pytest.mark.parametrize("tags", [None, [], {"a": 1}, "x"])
def test_check_tags_rejects_non_string_map(tags):
    with pytest.raises(ArmError) as e:
        check_tags(tags)
    assert e.value.code == "InvalidRequestContent"
