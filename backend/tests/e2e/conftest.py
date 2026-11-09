import pytest

from live_api import Server

# 볼륨 e2e(test_volume_*_live.py)의 픽스처. 도우미 모듈에 두고 여기서 등록한다
from dataplane_live import agent, api, clients, manual_data  # noqa: F401


@pytest.fixture
def start_server(tmp_path):
    """anf-api 프로세스를 띄우는 팩토리. 테스트가 끝나면 남은 프로세스를 모두 멈춘다."""
    servers = []

    def start(db_path=None, faults=None, raw_faults=None, wait=True):
        srv = Server(db_path or tmp_path / "anf.db", faults=faults, raw_faults=raw_faults)
        servers.append(srv)
        if wait:
            srv.start()
        else:
            srv.launch()
        return srv

    yield start
    for srv in reversed(servers):
        srv.stop()
