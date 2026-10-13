import { MESSAGES, type Reason } from "../api/messages";
import { followLink } from "../routing";

/** A reason's mapped text, with the server's own words as detail when there are any. */
export function Failure({ reason, detail }: { reason: Reason; detail?: string }) {
  const message = MESSAGES[reason];
  return (
    <div className="failure" role="alert">
      <p className="headline">{message.headline}</p>
      <p>{message.action}</p>
      {detail !== undefined && <p className="detail">{detail}</p>}
    </div>
  );
}

export function UploadAnother({ label = "Upload another song" }: { label?: string }) {
  return (
    <a href="/" onClick={followLink}>
      {label}
    </a>
  );
}
