import type { Session } from "../types";

type SessionListProps = {
  sessions: Session[];
  selectedSessionId: number | null;
  onSelect: (sessionId: number) => void;
};

export function SessionList({
  sessions,
  selectedSessionId,
  onSelect,
}: SessionListProps): JSX.Element {
  return (
    <section className="panel panel-sidebar">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Sessions</p>
          <h2>Factory Queue</h2>
        </div>
        <span className="badge badge-muted">{sessions.length}</span>
      </div>
      <div className="session-list">
        {sessions.map((session) => {
          const isSelected = session.id === selectedSessionId;
          return (
            <button
              className={`session-card ${isSelected ? "selected" : ""}`}
              key={session.id}
              onClick={() => onSelect(session.id)}
              type="button"
            >
              <div className="session-card-top">
                <strong>{session.task_key}</strong>
                <span className={`status-pill status-${session.status}`}>
                  {session.status}
                </span>
              </div>
              <p>{session.workflow_profile}</p>
              <small>{session.current_stage}</small>
              <small>{session.current_owner ?? "unowned"}</small>
            </button>
          );
        })}
      </div>
    </section>
  );
}
