import { roleDisplayName } from "../roleDisplay";
import { sessionStatusDisplayName, workflowProfileDisplayName } from "../sessionDisplay";
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
    <section className="panel panel-sidebar">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Sessions</p>
          <h2>Factory Queue</h2>
        </div>
        <span className="badge badge-muted">{sessions.length}</span>
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
                    {isSelected ? <span className="session-card-current">Selected</span> : null}
                  </div>
                  <span className={`status-pill status-${session.status}`}>
                    {sessionStatusDisplayName(session.status)}
                  </span>
                </div>
                {session.task_title ? (
                  <p className="session-card-title">{session.task_title}</p>
                ) : (
                  <p className="session-card-title">{workflowProfileDisplayName(session.workflow_profile)}</p>
                )}
                <div className="session-card-meta">
                  <small>{workflowProfileDisplayName(session.workflow_profile)}</small>
                  <small>Stage: {stageDisplayName(session.current_stage)}</small>
                  <small>Owner: {session.current_owner ? roleDisplayName(session.current_owner) : "Not assigned yet"}</small>
                </div>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="inline-summary-card">
          <div className="inline-summary-header">
            <strong>No workflow runs yet</strong>
          </div>
          <p className="form-help">
            Start a new run below to populate the queue.
          </p>
        </div>
      )}
    </section>
  );
}
