export function Brand({ label = "Global Trade Intelligence" }: { label?: string }) {
  return (
    <a className="brand" href="/trade" aria-label={`${label} — home`}>
      <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
        <circle cx="16" cy="16" r="12.5" fill="none" stroke="currentColor" strokeWidth="1.1" />
        <path d="M3.5 16h25" fill="none" stroke="currentColor" strokeWidth="1.1" />
        <path d="M16 3.5c4.2 4 4.2 21 0 25M16 3.5c-4.2 4-4.2 21 0 25" fill="none" stroke="currentColor" strokeWidth="1.1" />
        <circle cx="23.5" cy="10" r="2.1" fill="currentColor" stroke="none" />
      </svg>
      <span>
        <strong>TRADE INTELLIGENCE</strong>
        <small>UN COMTRADE</small>
      </span>
    </a>
  );
}
