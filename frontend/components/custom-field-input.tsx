"use client";

/**
 * Type-specific input control for a custom field value (text/number/date/
 * boolean/select). Shared by the document detail page and the upload-time
 * predefined-fields popup so the two never drift on how a field type renders.
 */
interface CustomFieldInputProps {
  fieldType: string; // text | number | date | boolean | select
  options: string[];
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

const DEFAULT_CLASSNAME =
  "flex-1 px-2 py-0.5 border border-slate-200 rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 bg-white";

export function CustomFieldInput({
  fieldType,
  options,
  value,
  onChange,
  className,
}: CustomFieldInputProps) {
  const cls = className ?? DEFAULT_CLASSNAME;

  if (fieldType === "boolean") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }

  if (fieldType === "select") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
        <option value="">— pick one —</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    );
  }

  return (
    <input
      type={fieldType === "number" ? "number" : fieldType === "date" ? "date" : "text"}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cls}
    />
  );
}

/** Parses a raw string draft into the typed value the API expects. */
export function parseCustomFieldValue(fieldType: string, draft: string): unknown {
  if (fieldType === "number") return parseFloat(draft);
  if (fieldType === "boolean") return draft === "true";
  return draft;
}
