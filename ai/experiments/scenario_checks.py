"""명세 예시의 실행 증거 검사. 업무 노드 판단이나 실행 경로를 바꾸지 않는다."""

from math import isclose


def calls(state):
    for item in state["results"]:
        if item["decision"] == "call" and item["outcome"] == "success":
            yield item
            output = item["output"] or {}
            if "results" in output:
                yield from calls(output)


def evaluate(name, state, previous=None):
    history = list(calls(state))
    names = [item["action"]["name"] for item in history]
    artifacts = (state["response"] or {}).get("artifacts", [])
    checks = {"completed": state["execution"]["status"] == "completed"}
    if name == "S1":
        checks["event_without_user_turn"] = not any(
            m.type == "human" for m in state["messages"]
        )
        checks["definition_queried"] = any(
            item["action"]["name"] == "query_data"
            and item["action"]["arguments"].get("target") == "D2"
            for item in history
        )
        expected = {
            (region, year): value
            for year in (2025, 2026)
            for region, value in (("A동", -10), ("B동", -8), ("C동", -10))
        }
        observed = {}
        for item in history:
            output = item["output"] or {}
            for op in output.get("operations", []):
                if op.get("method") != "percent_change":
                    continue
                for row in output["data"]["rows"]:
                    observed[(row.get("region"), row.get("year"))] = row.get(
                        op["output"]
                    )
        checks["six_changes_calculated_by_tool"] = all(
            isinstance(observed.get(key), (int, float))
            and isclose(observed[key], value, abs_tol=0.01)
            for key, value in expected.items()
        )
        checks["actual_comparison_table"] = any(a["type"] == "table" for a in artifacts)
    elif name == "S2":
        checks["visualization_agent_called"] = "visualization_agent" in names
        expected = [
            ("C동", 14.4),
            ("A동", 12.5),
            ("E동", 11.2),
            ("B동", 9.6),
            ("D동", 7.1),
        ]
        valid_chart = False
        for item in history:
            if item["action"]["name"] != "render_visualization":
                continue
            output = item["output"]
            spec, data = output["applied"], output["data"]
            if spec["type"] != "bar" or len(data["rows"]) != len(expected):
                continue
            valid_chart |= (
                spec.get("orientation") == "horizontal"
                and spec["unit"] == "%"
                and spec["value_range"] == {"minimum": 0, "maximum": 20}
                and all(
                    row[spec["x"]] == region
                    and isclose(row[spec["y"]], value, abs_tol=0.01)
                    for row, (region, value) in zip(data["rows"], expected, strict=True)
                )
                and output["artifact"] in artifacts
            )
        checks["actual_sorted_percentage_chart"] = valid_chart
        checks["percentage_calculated_by_tool"] = any(
            op.get("method") == "percentage"
            for item in history
            for op in (item["output"] or {}).get("operations", [])
        )
    elif name == "S3":
        checks["interpretation_agent_called"] = "interpretation_agent" in names
        prior_charts = [
            a
            for a in ((previous or {}).get("response") or {}).get("artifacts", [])
            if a["type"] == "chart"
        ]
        checks["selected_chart_preserved"] = bool(prior_charts) and all(
            a in artifacts for a in prior_charts
        )
        checks["no_unnecessary_chart_regeneration"] = (
            "render_visualization" not in names
        )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "scope": "호출·수치·산출물 검사. 자연어 의미·화면 품질의 완전한 평가가 아님.",
    }
