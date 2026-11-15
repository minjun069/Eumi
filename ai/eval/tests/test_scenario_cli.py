"""기존 명령으로 시나리오를 선택하고 관측용 출처·단가를 전달한다."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from eval.__main__ import main

INDEX = Path(__file__).resolve().parents[2] / "eval/scenarios/nodes/scenarios.json"


@pytest.mark.parametrize(
    ("options", "count"),
    [
        ([], 21),
        (["--target", "interpretation"], 4),
        (["--unit", "workflow", "--target", "report"], 3),
        (["--case", "basic-request-revision"], 1),
    ],
)
def test_validate_scenario_selection_without_model_or_output(
    options, count, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        pytest.fail("input validation must not create a model or run a suite")

    monkeypatch.setattr("eval.runner.create_model", forbidden)
    monkeypatch.setattr("eval.__main__.run_suite", forbidden)
    assert main(["validate", str(INDEX), *options]) == 0
    assert f"({count} cases)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "options",
    [
        ["--case", "missing-scenario"],
        ["--unit", "node"],
        ["--unit", "workflow", "--case", "basic-request-none"],
        ["--unit", "agent", "--target", "report"],
    ],
)
def test_invalid_selection_stops_before_running(options, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid selection must not run")

    monkeypatch.setattr("eval.__main__.run_suite", forbidden)
    output = tmp_path / "output"
    assert main(["run", str(INDEX), "--output", str(output), *options]) == 2
    assert not output.exists()


def test_run_dispatch_preserves_origin_and_prices_without_intermediate_input(
    tmp_path, monkeypatch
):
    prices = {
        "version": "test-only",
        "currency": "USD",
        "models": {"test-model": {"input_per_million": 1.0, "output_per_million": 2.0}},
        "tools": {"query_data": {"per_call": 0.0}},
    }
    price_path = tmp_path / "prices.json"
    price_path.write_text(json.dumps(prices), encoding="utf-8")
    output = tmp_path / "output"
    calls = []

    async def execute(suite, settings, folder, **kwargs):
        calls.append((suite, kwargs))
        assert folder == output
        assert suite["execution_prices"] == prices
        assert [c["target"] for c in suite["cases"]] == ["report"]
        assert [r["decision"] for r in suite["cases"][0]["initial"]["results"]] == [
            "report_input",
            "report_source",
        ]
        assert kwargs["source_path"] == INDEX
        assert (
            kwargs["source_selection"][0]["entry_state"]
            == "entry_transition.before_state"
        )
        assert kwargs["source_files_sha256"][str(price_path.resolve())] == (
            sha256(price_path.read_bytes()).hexdigest()
        )
        assert kwargs["repeat"] == 2
        assert sorted(p.name for p in tmp_path.iterdir()) == ["prices.json"]
        folder.mkdir()
        (folder / "batch.json").write_text(
            json.dumps({"status": "returned", "runs": [{}, {}], "planned_runs": 2}),
            encoding="utf-8",
        )
        return folder

    monkeypatch.setattr("eval.__main__.run_suite", execute)
    assert (
        main(
            [
                "run",
                str(INDEX),
                "--unit",
                "workflow",
                "--target",
                "report",
                "--case",
                "basic-report_selection-1168065500",
                "--prices",
                str(price_path),
                "--output",
                str(output),
                "--repeat",
                "2",
                "--env-file",
                str(tmp_path / "none.env"),
            ]
        )
        == 0
    )
    assert len(calls) == 1


def test_invalid_prices_stop_before_execution(tmp_path, monkeypatch):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"version": "invalid", "models": {}}), encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid prices must not run")

    monkeypatch.setattr("eval.__main__.run_suite", forbidden)
    assert (
        main(
            [
                "run",
                str(INDEX),
                "--case",
                "basic-request-revision",
                "--prices",
                str(path),
            ]
        )
        == 2
    )


@pytest.mark.parametrize("failed", [False, True])
def test_cli_prints_all_node_batches_and_combines_exit_status(
    tmp_path, monkeypatch, capsys, failed
):
    from eval.tests.test_evaluation_runner import node_case, suite

    source = tmp_path / "suite.json"
    source.write_text(
        json.dumps(suite(node_case("decide"), node_case("interpret"))), encoding="utf-8"
    )
    folders = [tmp_path / node / "batch" for node in ("decide", "interpret")]

    async def execute(*args, **kwargs):
        for index, folder in enumerate(folders):
            folder.mkdir(parents=True)
            (folder / "batch.json").write_text(
                json.dumps(
                    {
                        "status": "error" if failed and index == 0 else "returned",
                        "runs": [{}],
                        "planned_runs": 1,
                    }
                ),
                encoding="utf-8",
            )
        return folders

    monkeypatch.setattr("eval.__main__.run_suite", execute)
    assert main(["run", str(source), "--env-file", str(tmp_path / "none.env")]) == int(
        failed
    )
    output = capsys.readouterr().out
    assert all(str(folder) in output for folder in folders)
