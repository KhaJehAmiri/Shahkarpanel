"use client";

import { Plus } from "lucide-react";
import { btnSecondaryClass, btnDangerClass } from "./FieldRow";

interface UserRepeaterProps<T> {
  users: T[];
  onChange: (users: T[]) => void;
  min?: number;
  createEmpty: () => T;
  renderUser: (user: T, index: number, update: (patch: Partial<T>) => void) => React.ReactNode;
}

export function UserRepeater<T>({
  users,
  onChange,
  min = 1,
  createEmpty,
  renderUser,
}: UserRepeaterProps<T>) {
  return (
    <div className="w-full">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-[var(--text)]">Users</span>
        <button
          type="button"
          className={btnSecondaryClass}
          onClick={() => onChange([...users, createEmpty()])}
        >
          <Plus className="mr-1 inline h-3.5 w-3.5" /> Add User
        </button>
      </div>
      {users.map((user, i) => (
        <div key={i} className="mb-3 rounded-lg border border-[var(--border)] p-3">
          {renderUser(user, i, (patch) => {
            const next = [...users];
            next[i] = { ...next[i], ...patch };
            onChange(next);
          })}
          {users.length > min && (
            <button
              type="button"
              className={`${btnDangerClass} mt-2`}
              onClick={() => onChange(users.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
