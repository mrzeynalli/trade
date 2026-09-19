import type { ReactNode } from "react";

type Props = {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
  footnote?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
};

export function Panel({
  eyebrow,
  title,
  description,
  action,
  footnote,
  children,
  className = "",
  bodyClassName = "",
}: Props) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div className="panel-heading">
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action && <div className="panel-action">{action}</div>}
      </header>
      <div className={`panel-body ${bodyClassName}`}>{children}</div>
      {footnote && <p className="panel-footnote">{footnote}</p>}
    </section>
  );
}
