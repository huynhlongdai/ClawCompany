import type {ReactNode} from "react";

/* Khối nội dung có tiêu đề. Dùng tiết kiệm: danh sách dày dùng List, không bọc mọi thứ trong thẻ. */
export function Panel({title, desc, actions, children, flush, className, id, testId}: {
  title?: ReactNode; desc?: ReactNode; actions?: ReactNode; children?: ReactNode; flush?: boolean; className?: string; id?: string; testId?: string;
}) {
  return <section className={"ui-panel" + (className ? " " + className : "")} aria-labelledby={id && title ? id + "-t" : undefined} data-testid={testId}>
    {(title || actions) && <header className="ui-panel-head">
      <div className="ui-grow">{title && <h2 id={id ? id + "-t" : undefined}>{title}</h2>}{desc && <p>{desc}</p>}</div>
      {actions}
    </header>}
    {flush ? children : <div className="ui-panel-body">{children}</div>}
  </section>;
}

export function Section({title, link, children, testId}: {title: ReactNode; link?: ReactNode; children: ReactNode; testId?: string}) {
  return <section className="ui-section" data-testid={testId}>
    <div className="ui-section-head"><h2>{title}</h2>{link}</div>
    {children}
  </section>;
}
