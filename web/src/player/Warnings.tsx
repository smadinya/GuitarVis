/** The document's warnings. A tab the user cannot tell is degraded is worse
 * than one labelled as such. */
export function Warnings({ warnings }: { warnings: readonly string[] }) {
  if (warnings.length === 0) return null;
  return (
    <aside className="warnings" aria-label="Warnings">
      <ul>
        {warnings.map((warning, index) => (
          <li key={index}>{warning}</li>
        ))}
      </ul>
    </aside>
  );
}
