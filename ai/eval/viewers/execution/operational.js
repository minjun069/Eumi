/* Read-only summaries of selected individual operational measurements.
 * Population and statistics follow eval/execution/metrics.py _group/_statistics. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.ExecutionOperational = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const FILTER_KEYS = Object.freeze(["situation", "entry", "environment", "data_size", "dependencies"]);
  const MEASURES = Object.freeze(["elapsed_seconds", "model_calls", "tool_calls", "agent_calls", "node_entries", "retries", "input_tokens", "output_tokens", "cost"]);
  const normalize = value => value == null ? null : String(value);
  const agentKey = run => JSON.stringify([normalize(run.unit), normalize(run.target)]);
  const rate = (numerator, denominator) => ({numerator, denominator, rate: denominator ? numerator / denominator : null});

  function agents(runs) {
    const found = new Map();
    for (const run of runs) {
      const key = agentKey(run);
      if (!found.has(key)) found.set(key, {key, unit: normalize(run.unit), target: normalize(run.target)});
    }
    return [...found.values()];
  }

  function options(runs, key) {
    return FILTER_KEYS.includes(key) ? [...new Set(runs.map(run => normalize(run[key])))] : [];
  }

  function select(runs, selectedAgent, filters = {}) {
    const choices = FILTER_KEYS.map(key => [key, new Set((filters[key] || []).map(normalize))]);
    return runs.filter(run => (selectedAgent == null || selectedAgent === "all" || agentKey(run) === selectedAgent) &&
      choices.every(([key, values]) => !values.size || values.has(normalize(run[key]))));
  }

  function statistics(values) {
    const ordered = values.filter(value => typeof value === "number" && Number.isFinite(value) && value >= 0).sort((a, b) => a - b);
    const count = ordered.length, middle = Math.floor(count / 2);
    // Averaging incrementally also keeps finite, very large observations finite.
    const mean = count ? ordered.reduce((average, value, index) => average + (value - average) / (index + 1), 0) : null;
    const median = !count ? null : count % 2 ? ordered[middle] : ordered[middle - 1] + (ordered[middle] - ordered[middle - 1]) / 2;
    return {sample_count: count, missing_count: values.length - count, mean, median,
      p95: count ? ordered[Math.ceil(count * 0.95) - 1] : null,
      minimum: count ? ordered[0] : null, maximum: count ? ordered[count - 1] : null};
  }

  function summarize(runs) {
    const started = runs.filter(run => run.started === true);
    const ended = started.filter(run => run.ended === true);
    const measured = ended.filter(run => run.outcome !== "evaluation_failure");
    const counts = new Map();
    for (const run of started) counts.set(run.outcome, (counts.get(run.outcome) || 0) + 1);
    const count = outcome => counts.get(outcome) || 0;
    const failure = rate(count("technical_failure"), measured.length);
    if (count("unclassified")) failure.rate = null;
    return {
      started: started.length, ended: ended.length, unfinished: started.length - ended.length,
      outcomes: Object.fromEntries([...counts].map(([outcome, count]) => [outcome, rate(count, started.length)])),
      failure_rate: {...failure, unclassified_count: count("unclassified"), evaluation_failure_count: count("evaluation_failure"), unfinished_count: count("unfinished")},
      measurements: Object.fromEntries(MEASURES.map(key => [key, statistics(measured.map(run => run[key]))])),
      elapsed_by_outcome: Object.fromEntries([...new Set(measured.map(run => run.outcome))].sort().map(outcome =>
        [outcome, statistics(measured.filter(run => run.outcome === outcome).map(run => run.elapsed_seconds))])),
      runs: [...runs],
    };
  }

  return {FILTER_KEYS, MEASURES, agentKey, agents, options, select, summarize};
});
