type Option<T extends string> = { value: T; label: string; disabled?: boolean; title?: string };

type Props<T extends string> = {
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
  label: string;
};

/** Keyboard-operable segmented control; every option is a real button. */
export function Segment<T extends string>({ value, options, onChange, label }: Props<T>) {
  return (
    <div className="segment" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={option.disabled}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
