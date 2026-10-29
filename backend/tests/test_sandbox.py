import asyncio
import json
from threading import Event
from pathlib import Path
from unittest.mock import Mock, patch

import docker
import pytest

from backend.sandbox import ExecutionSandbox, RESULT_MARKER


def xml_output(exit_code, xml):
    return f"__TESTFORGE_PYTEST_EXIT_CODE__={exit_code}\n{xml}".encode()


class FakeContainer:
    def __init__(self, output, exit_code=0, status="exited"):
        self.output = output
        self.status = status
        self.attrs = {"State": {"ExitCode": exit_code}}
        self.removed = False
        self.stopped = False
        self.started = False

    def start(self):
        self.started = True

    def reload(self):
        return None

    def logs(self, stdout=True, stderr=True):
        return self.output

    def stop(self, timeout=2):
        self.stopped = True
        self.status = "exited"

    def kill(self):
        self.status = "exited"

    def remove(self, force=True):
        self.removed = True


class FakeDockerClient:
    def __init__(self, container):
        self.container = container
        self.images = Mock()
        self.images.get.return_value = object()
        self.containers = Mock()
        self.containers.create.side_effect = self.create
        self.run_kwargs = None
        self.closed = False

    def create(self, *args, **kwargs):
        self.run_kwargs = kwargs
        return self.container

    def close(self):
        self.closed = True

    def ping(self):
        return True


def parse_result(logs):
    marker_index = logs.rfind(RESULT_MARKER)
    assert marker_index >= 0
    return json.loads(logs[marker_index + len(RESULT_MARKER) :])


def test_pytest_pass_requires_nonzero_collection_and_real_exit_zero():
    report = (
        '<testsuites tests="2" failures="0" errors="0" skipped="0">'
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase/><testcase/></testsuite></testsuites>'
    )
    container = FakeContainer(xml_output(0, report))
    client = FakeDockerClient(container)
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is True
    assert result["exit_code"] == 0
    assert result["collected"] == 2
    assert result["passed"] == 2
    assert container.removed is True
    assert client.closed is True
    mount = client.run_kwargs["volumes"]
    workspace = Path(next(iter(mount)))
    assert not workspace.exists()


def test_container_uses_isolated_read_only_limited_configuration():
    report = (
        '<testsuites tests="1" failures="0" errors="0" skipped="0">'
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase/></testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(0, report)))
    sandbox = ExecutionSandbox(timeout_seconds=7)
    route_code = "ROUTE_MARKER = 'not an argument'"
    test_code = "def test_safe(): assert True # TEST_MARKER"

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, _ = asyncio.run(sandbox.run_test_in_docker(test_code, route_code))

    kwargs = client.run_kwargs
    assert passed is True
    assert kwargs["network_disabled"] is True
    assert kwargs["read_only"] is True
    assert kwargs["user"] == "65534:65534"
    assert kwargs["log_config"] == {
        "Type": "local",
        "Config": {
            "max-size": "4m",
            "max-file": "1",
            "compress": "false",
        },
    }
    assert kwargs["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in kwargs["security_opt"]
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["nano_cpus"] == 1_000_000_000
    assert kwargs["pids_limit"] == 64
    assert kwargs["tmpfs"].keys() == {"/tmp"}
    assert kwargs["environment"] == {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "TMPDIR": "/tmp",
    }
    assert len(kwargs["volumes"]) == 1
    mount = next(iter(kwargs["volumes"].values()))
    assert mount == {"bind": "/workspace", "mode": "ro"}
    assert "docker.sock" not in str(kwargs["volumes"]).lower()
    assert "ROUTE_MARKER" not in str(kwargs["command"])
    assert "TEST_MARKER" not in str(kwargs["command"])
    assert container_removed_and_client_closed(client)


def test_container_created_before_start_is_removed_when_start_fails():
    container = FakeContainer(b"", status="created")
    container.start = Mock(
        side_effect=docker.errors.APIError("container startup rejected")
    )
    client = FakeDockerClient(container)
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "docker_error"
    assert container.removed is True
    assert client.closed is True


def container_removed_and_client_closed(client):
    return client.container.removed and client.closed


@pytest.mark.parametrize(
    ("test_code", "route_code", "expected_size_label"),
    [
        ("ok", "r" * 9, "source is 9 bytes"),
        ("t" * 17, "ok", "generated tests are 17 bytes"),
    ],
)
def test_oversized_inputs_are_rejected_before_workspace_or_docker(
    test_code, route_code, expected_size_label
):
    sandbox = ExecutionSandbox(max_source_bytes=8, max_test_bytes=16)
    with (
        patch("backend.sandbox.docker.from_env") as from_env,
        patch("backend.sandbox.tempfile.TemporaryDirectory") as temporary_directory,
    ):
        passed, logs = asyncio.run(sandbox.run_test_in_docker(test_code, route_code))

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "sandbox_error"
    assert expected_size_label in logs
    from_env.assert_not_called()
    temporary_directory.assert_not_called()


def test_explicit_zero_resource_limits_are_rejected():
    with pytest.raises(ValueError):
        ExecutionSandbox(timeout_seconds=0)
    with pytest.raises(ValueError):
        ExecutionSandbox(nano_cpus=0)
    with pytest.raises(ValueError):
        ExecutionSandbox(pids_limit=0)


def test_cancellation_waits_for_executor_before_removing_workspace():
    worker_started = Event()
    worker_release = Event()
    worker_observation = {}
    sandbox = ExecutionSandbox(timeout_seconds=2)

    def blocked_worker(workspace, started):
        path = Path(workspace)
        worker_observation["path"] = path
        worker_started.set()
        worker_release.wait(timeout=3)
        worker_observation["workspace_existed_until_worker_exit"] = path.exists()
        worker_observation["test_file_existed_until_worker_exit"] = (
            path / "test_app.py"
        ).exists()
        return False, sandbox._encode_result(
            "worker finished", {"error_type": "sandbox_error"}
        )

    async def exercise_cancellation():
        with patch.object(sandbox, "_run_container_sync", side_effect=blocked_worker):
            task = asyncio.create_task(
                sandbox.run_test_in_docker("def test_ok(): assert True", "app = None")
            )
            assert await asyncio.to_thread(worker_started.wait, 2)
            path = worker_observation["path"]
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert path.exists()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert path.exists()
            worker_release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not path.exists()

    asyncio.run(exercise_cancellation())
    assert worker_observation["workspace_existed_until_worker_exit"] is True
    assert worker_observation["test_file_existed_until_worker_exit"] is True


def test_pytest_assertion_failure_is_returned_as_failure_with_counts():
    report = (
        '<testsuites tests="1" failures="1" errors="0" skipped="0">'
        '<testsuite tests="1" failures="1" errors="0" skipped="0">'
        '<testcase><failure message="expected 400">AssertionError</failure>'
        '</testcase></testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(1, report), exit_code=1))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert False", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "assertion_failure"
    assert result["failures"] == 1
    assert result["passed"] == 0


def test_zero_collected_tests_is_never_success():
    report = (
        '<testsuites tests="0" failures="0" errors="0" skipped="0">'
        '<testsuite tests="0" failures="0" errors="0" skipped="0">'
        '</testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(5, report), exit_code=5))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["collected"] == 0
    assert result["error_type"] == "no_tests_collected"
    assert result["diagnosis"]["category"] == "no_tests_collected"


def test_fastapi_error_for_non_pydantic_route_model_is_application_initialization_error():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="FastAPIError" message="Invalid args for response field">'
        'FastAPIError: Invalid args for response field</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\n"
        b"/workspace/test_app.py:1: in <module>\n    from main import app\n"
        b"/workspace/main.py:6: in <module>\n    @app.post('/register')\n"
        b"fastapi.exceptions.FastAPIError: Invalid args for response field!\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n"
        + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)
    route_code = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "class RegistrationRequest():\n"
        "    username: str\n"
        "@app.post('/register')\n"
        "def register_user(user: RegistrationRequest):\n"
        "    return {'username': user.username}\n"
    )

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("from fastapi.testclient import TestClient", route_code)
        )

    result = parse_result(logs)
    diagnosis = result["diagnosis"]
    assert passed is False
    assert result["exit_code"] == 2
    assert result["error_type"] == "application_error"
    assert result["collected"] == 0
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert diagnosis["category"] == "application_error"
    assert diagnosis["title"] == "Application Initialization Error"
    assert diagnosis["endpoint_assertions_ran"] is False
    assert "RegistrationRequest" in diagnosis["likely_cause"]
    assert "BaseModel" in diagnosis["suggestion"]
    assert "username: str" in diagnosis["suggestion"]
    assert "no endpoint assertions were executed" in diagnosis["message"]
    assert diagnosis["exception_type"] == "FastAPIError"
    assert diagnosis["exception_message"] == "Invalid args for response field!"
    assert client.container.removed is True
    assert client.closed is True


def test_fastapi_error_in_generated_test_module_is_not_assigned_to_application():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="FastAPIError" message="Invalid args for response field">'
        'FastAPIError: Invalid args for response field</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\n"
        b"/workspace/test_app.py:4: in <module>\n    @test_app.post('/health')\n"
        b"fastapi.exceptions.FastAPIError: Invalid args for response field!\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker(
                "from fastapi import FastAPI\ntest_app = FastAPI()",
                "from fastapi import FastAPI\napp = FastAPI()",
            )
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "test_collection_error"
    assert result["collected"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["category"] == "test_collection_error"


def test_application_import_error_in_main_is_not_mislabeled_as_test_collection_error():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="ImportError" message="missing app dependency">'
        'ImportError: missing app dependency</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\n"
        b"/workspace/test_app.py:1: in <module>\n    from main import app\n"
        b"/workspace/main.py:1: in <module>\n    from broken_dependency import value\n"
        b"E ImportError: missing app dependency\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker(
                "from main import app\n\ndef test_health(): assert app is not None",
                "from broken_dependency import value",
            )
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "application_error"
    assert result["exit_code"] == 2
    assert result["collected"] == 0
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False
    assert result["diagnosis"]["exception_type"] == "ImportError"


def test_collection_error_with_junit_test_error_is_not_counted_as_executed_test():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="ImportError">ImportError</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR collecting test_app.py\nImportError while importing test module\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=2\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=2))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "test_collection_error"
    assert result["exit_code"] == 2
    assert result["collected"] == 0
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False


def test_fixture_setup_error_stays_distinct_from_collection_and_assertion_errors():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="FixtureLookupError">fixture error</error></testcase>'
        '</testsuite></testsuites>'
    )
    output = (
        b"ERROR at setup of test_health\nfixture 'client' not found\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=1\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=1))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_health(client): assert True", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "test_setup_error"
    assert result["collected"] == 1
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["endpoint_assertions_ran"] is False


def test_test_execution_error_without_setup_or_assertion_evidence_is_inconclusive():
    report = (
        '<testsuites tests="1" failures="0" errors="1" skipped="0">'
        '<testsuite tests="1" failures="0" errors="1" skipped="0">'
        '<testcase><error type="RuntimeError">application handler raised</error>'
        '</testcase></testsuite></testsuites>'
    )
    output = (
        b"ERROR test_app.py::test_health - RuntimeError: application handler raised\n"
        b"__TESTFORGE_PYTEST_EXIT_CODE__=1\n" + report.encode()
    )
    client = FakeDockerClient(FakeContainer(output, exit_code=1))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker(
                "def test_health(): raise RuntimeError('application handler raised')",
                "app = None",
            )
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "inconclusive"
    assert result["collected"] == 1
    assert result["passed"] == 0
    assert result["failures"] == 0
    assert result["errors"] == 1
    assert result["diagnosis"]["category"] == "inconclusive"
    assert "does not confirm an API defect" in result["diagnosis"]["message"]


def test_all_skipped_tests_have_distinct_non_passing_classification():
    report = (
        '<testsuites tests="2" failures="0" errors="0" skipped="2">'
        '<testsuite tests="2" failures="0" errors="0" skipped="2">'
        '<testcase><skipped/></testcase><testcase><skipped/></testcase>'
        '</testsuite></testsuites>'
    )
    client = FakeDockerClient(FakeContainer(xml_output(0, report)))
    sandbox = ExecutionSandbox(timeout_seconds=2)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "all_tests_skipped"


def test_docker_unavailable_returns_explicit_error_without_host_execution():
    sandbox = ExecutionSandbox(timeout_seconds=2)
    with patch(
        "backend.sandbox.docker.from_env",
        side_effect=docker.errors.DockerException("daemon unavailable"),
    ):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["error_type"] == "docker_unavailable"
    assert "Docker is unavailable" in logs


def test_execution_timeout_stops_and_removes_container():
    report = '<testsuites tests="0" failures="0" errors="0" skipped="0"></testsuites>'
    container = FakeContainer(xml_output(137, report), exit_code=137, status="running")
    client = FakeDockerClient(container)
    sandbox = ExecutionSandbox(timeout_seconds=0.01)

    with patch("backend.sandbox.docker.from_env", return_value=client):
        passed, logs = asyncio.run(
            sandbox.run_test_in_docker("def test_one(): pass", "app = None")
        )

    result = parse_result(logs)
    assert passed is False
    assert result["timed_out"] is True
    assert container.stopped is True
    assert container.removed is True
