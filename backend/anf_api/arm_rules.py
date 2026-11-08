"""ARM 앞단 규칙: api-version, 이름 규칙, 리소스 ID, 오류 형식 (계정 설계 §4).

실제 Azure에서는 이 검사 일부를 ARM이 리소스 공급자(ANF) 앞에서 한다.
클론에는 ARM이 없으므로 anf-api가 맡는다.
"""

import re

API_VERSION = "2026-08-01"
PROVIDER = "Microsoft.NetApp"
ACCOUNT_TYPE = f"{PROVIDER}/netAppAccounts"
POOL_TYPE = f"{ACCOUNT_TYPE}/capacityPools"
VOLUME_TYPE = f"{POOL_TYPE}/volumes"

# 계정 이름: 영숫자로 시작, 영숫자·`-`·`_`, 1~128자 [스펙 3]
_ACCOUNT_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-_]{0,127}")
# 풀 이름: 계정과 같은 문자, 1~64자 [풀 브리프, 스펙]
_POOL_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9\-_]{0,63}")
# 볼륨 이름: 영문자로 시작, 1~64자 [볼륨 브리프, 스펙 2]
_VOLUME_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_]{0,63}")
# 리소스 그룹 이름: 1~90자, 문자·숫자·`-`·`_`·`.`·`(`·`)` [스펙 8, common-types]
_RESOURCE_GROUP_NAME = re.compile(r"[-\w._()]{1,90}")


class ArmError(Exception):
    """ARM 오류 응답 `{"error": {"code", "message"}}`으로 바뀌는 예외."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def check_api_version(value: str | None) -> None:
    if value is None:
        raise ArmError(
            400,
            "MissingApiVersionParameter",
            "The api-version query parameter (?api-version=) is required for all requests.",
        )
    if value != API_VERSION:
        raise ArmError(
            400,
            "NoRegisteredProviderFound",
            f"No registered resource provider found for API version '{value}'. "
            f"The supported api-versions are '{API_VERSION}'.",
        )


def check_account_name(name: str) -> None:
    if not _ACCOUNT_NAME.fullmatch(name):
        raise ArmError(
            400,
            "InvalidResourceName",
            f"The NetApp account name '{name}' is invalid. It must start with an alphanumeric "
            "character, contain only alphanumerics, '-' or '_', and be 1 to 128 characters long.",
        )


def check_pool_name(name: str) -> None:
    if not _POOL_NAME.fullmatch(name):
        raise ArmError(
            400,
            "InvalidResourceName",
            f"The capacity pool name '{name}' is invalid. It must start with an alphanumeric "
            "character, contain only alphanumerics, '-' or '_', and be 1 to 64 characters long.",
        )


def check_volume_name(name: str) -> None:
    if not _VOLUME_NAME.fullmatch(name):
        raise ArmError(
            400,
            "InvalidResourceName",
            f"The volume name '{name}' is invalid. It must start with a letter, contain only "
            "alphanumerics, '-' or '_', and be 1 to 64 characters long.",
        )


def check_resource_group_name(name: str) -> None:
    if not _RESOURCE_GROUP_NAME.fullmatch(name):
        raise ArmError(
            400,
            "InvalidResourceName",
            f"The resource group name '{name}' is invalid. It must be 1 to 90 characters of "
            "letters, digits, '-', '_', '.', '(' or ')'.",
        )


def account_id(subscription_id: str, resource_group: str, name: str) -> str:
    return (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/{ACCOUNT_TYPE}/{name}"
    )


def pool_id(subscription_id: str, resource_group: str, account: str, name: str) -> str:
    return f"{account_id(subscription_id, resource_group, account)}/capacityPools/{name}"


def volume_id(subscription_id: str, resource_group: str, account: str, pool: str, name: str) -> str:
    return f"{pool_id(subscription_id, resource_group, account, pool)}/volumes/{name}"


def invalid_content(message: str) -> ArmError:
    """요청 본문 형식 오류. 코드는 ARM 오류 목록에서 가져왔다 (계정 설계 §4.3)."""
    return ArmError(400, "InvalidRequestContent", message)


def unknown_property(name: str) -> ArmError:
    # ANF RP 오류 문서의 문구 [계정 브리프 문서 12]
    return invalid_content(f"Value received for an unknown property '{name}'.")


def unsupported_property(name: str) -> ArmError:
    """실제 ANF에는 있지만 이 클론이 미룬 속성. 받으면 무시하지 않고 거절한다."""
    return invalid_content(f"The property '{name}' is not supported by this ANF clone.")


def check_tags(tags) -> dict:
    if not isinstance(tags, dict) or not all(isinstance(v, str) for v in tags.values()):
        raise invalid_content("The 'tags' property must be an object of string values.")
    return tags


def not_found(resource_id: str) -> ArmError:
    # 리소스 공급자가 낸 404의 문구 (계정 녹화 R1, 풀 녹화 N1)
    return ArmError(404, "ResourceNotFound", f"The resource with identifier '{resource_id}' is not found.")


def location_conflict(name: str, resource_group: str, existing: str, requested: str) -> ArmError:
    """location은 생성 뒤 바꿀 수 없다 [계정 스펙 7]. 코드는 ARM 오류 목록, HTTP 409는 클론의 선택."""
    return ArmError(
        409, "InvalidResourceLocation",
        f"The resource '{name}' already exists in location '{existing}' in resource group "
        f"'{resource_group}'. A resource with the same name cannot be created in location "
        f"'{requested}'. Please select a new resource name.",
    )


def operation_path(subscription_id: str, location: str, operation_id: str) -> str:
    """작업 상태 URL의 경로. 리소스가 지워진 뒤에도 조회할 수 있게 구독·리전 범위에 둔다 [문서 24]."""
    return (
        f"/subscriptions/{subscription_id}/providers/{PROVIDER}"
        f"/locations/{location}/operationResults/{operation_id}"
    )
