import { roleDisplayName } from "../roleDisplay";
import { sessionStatusDisplayName } from "../sessionDisplay";
import { stageDisplayName } from "../stageDisplay";
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
    <section className="panel panel-sidebar sidebar-zone sidebar-zone-queue">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Sessions</p>
          <h2>Session Queue</h2>
        </div>
        {sessions.length > 0 ? <span className="badge badge-muted">{sessions.length}</span> : null}
      </div>
      {sessions.length > 0 ? (
        <div className="session-list limited-list queue-list">
          {sessions.map((session) => {
            const isSelected = session.id === selectedSessionId;
            return (
              <button
                className={`session-card ${isSelected ? "selected" : ""}`}
                key={session.id}
                onClick={() => onSelect(session.id)}
                title={`Open ${session.task_key} at stage ${stageDisplayName(session.current_stage)}${session.current_owner ? ` owned by ${roleDisplayName(session.current_owner)}` : ""}.`}
                type="button"
              >
                <div className="session-card-top">
                  <div className="session-card-keyline">
                    <strong>{session.task_key}</strong>
                  </div>
                  <span className={`status-pill status-${session.status}`}>
                    {sessionStatusDisplayName(session.status)}
                  </span>
                </div>
                {session.task_title ? <p className="session-card-title" title={session.task_title}>{session.task_title}</p> : null}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="inline-summary-card">
          <div className="inline-summary-header">
            <strong>No runs yet</strong>
          </div>
          <p className="form-help">Start your first workflow below.</p>
        </div>
      )}
    </section>
  );
}
