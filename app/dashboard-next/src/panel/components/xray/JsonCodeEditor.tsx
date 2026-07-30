import { ChangeEvent, FC, useEffect, useRef } from "react";

/** JSON editor with line numbers — 3x-ui style. */
export const JsonCodeEditor: FC<{
  value: string;
  onChange: (v: string) => void;
  minLines?: number;
}> = ({ value, onChange, minLines = 22 }) => {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const lineCount = Math.max(value.split("\n").length, minLines);

  const syncScroll = () => {
    if (gutterRef.current && taRef.current) {
      gutterRef.current.scrollTop = taRef.current.scrollTop;
    }
  };

  useEffect(() => {
    syncScroll();
  }, [value]);

  return (
    <div className="sk-json-editor">
      <div className="sk-json-editor-gutter" ref={gutterRef} aria-hidden>
        {Array.from({ length: lineCount }, (_, i) => (
          <div key={i} className="sk-json-editor-ln">{i + 1}</div>
        ))}
      </div>
      <textarea
        ref={taRef}
        className="sk-json-editor-code"
        value={value}
        onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
        onScroll={syncScroll}
        spellCheck={false}
        dir="ltr"
      />
    </div>
  );
};
