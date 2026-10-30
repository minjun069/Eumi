import {
  useCurrentDevScenario,
  type DevScenarioAction,
} from "@/devtools/devScenarioStore"

/** 개발용 영역 '예외 상황': 지금 보고 있는 화면이 등록한 상황 재현 도구 */
export function DevScenarioPanel() {
  const scenario = useCurrentDevScenario()

  return (
    <section className="dev-section">
      <h2 className="dev-title">
        예외 상황
        {scenario && <span className="dev-count">{scenario.screen}</span>}
      </h2>
      {!scenario ? (
        <p className="dev-hint dev-hint-muted">
          이 화면에는 예외 상황 도구가 없습니다.
        </p>
      ) : (
        <>
          <ActionGrid actions={scenario.actions} />
          {scenario.groups?.map((group) => (
            <div key={group.title} className="dev-group">
              <span className="dev-group-title">{group.title}</span>
              <ActionGrid actions={group.actions} />
            </div>
          ))}
          {scenario.infos?.map((info) => (
            <div key={info.label} className="dev-info">
              <span className="dev-info-label">{info.label}</span>
              <span className="dev-info-value">{info.value}</span>
              {info.action && (
                <button
                  type="button"
                  className="dev-button dev-button-small"
                  onClick={info.action.run}
                >
                  {info.action.label}
                </button>
              )}
            </div>
          ))}
          {scenario.hint && <p className="dev-hint">{scenario.hint}</p>}
        </>
      )}
    </section>
  )
}

function ActionGrid({ actions }: { actions: DevScenarioAction[] }) {
  if (actions.length === 0) return null
  return (
    <div className="dev-scenario-actions">
      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          className="dev-button"
          onClick={action.run}
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}
