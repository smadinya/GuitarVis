import { followLink } from "./routing";

/**
 * The way back to the upload page, followed in place. The song page's header
 * and its failure states both offer it, so it lives apart from either: the
 * player may not import from pages, whose song page imports the player.
 * `className` is for the header's styling of it as a back link.
 */
export function UploadAnother({
  label = "Upload another song",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <a href="/" onClick={followLink} className={className}>
      {label}
    </a>
  );
}
