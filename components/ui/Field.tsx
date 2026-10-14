"use client";
import {cloneElement, isValidElement, ReactElement, ReactNode, useId} from "react";

/* Ô nhập có nhãn, gợi ý và lỗi gắn đúng aria. Truyền control là con duy nhất:
   <Field label="Email" hint="…"><input type="email" autoComplete="email"/></Field> */
export function Field({label, hint, error, children, className}: {
  label: ReactNode; hint?: ReactNode; error?: ReactNode; children: ReactElement; className?: string;
}) {
  const id = useId();
  const describedBy = [hint ? `${id}-h` : "", error ? `${id}-e` : ""].filter(Boolean).join(" ") || undefined;
  const control = isValidElement(children)
    ? cloneElement(children as ReactElement<any>, {id: (children.props as any).id || id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined})
    : children;
  return <div className={"ui-field" + (error ? " has-error" : "") + (className ? " " + className : "")}>
    <label className="ui-field-label" htmlFor={(children.props as any)?.id || id}>{label}</label>
    {control}
    {hint && !error && <span className="ui-field-hint" id={`${id}-h`}>{hint}</span>}
    {error && <span className="ui-field-error" id={`${id}-e`} role="alert">{error}</span>}
  </div>;
}

export function FormRow({children}: {children: ReactNode}) { return <div className="ui-form-row">{children}</div>; }
