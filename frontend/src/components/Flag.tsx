import "flag-icons/css/flag-icons.min.css";

/**
 * Small country flag. `flag-icons` ships self-hosted SVGs, so this renders
 * identically on every platform (emoji flags do not render on Windows) and
 * needs no external request.
 *
 * The flag is decorative: every place it appears, the country name is next to
 * it, so it carries no information on its own.
 */
export function Flag({ iso2, size = 14 }: { iso2?: string | null; size?: number }) {
  if (!iso2) {
    return <span className="flag-placeholder" style={{ width: size * 1.34, height: size }} aria-hidden="true" />;
  }
  return (
    <span
      className={`fi fi-${iso2.toLowerCase()} flag`}
      style={{ width: size * 1.34, height: size }}
      aria-hidden="true"
    />
  );
}
