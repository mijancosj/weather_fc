import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

export function SourceFilter() {
  const sourcesQuery = useQuery({ queryKey: ["sources"], queryFn: api.sources });

  return (
    <div className="flex gap-2">
      {sourcesQuery.data?.map((source) => (
        <span
          key={source.id}
          className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300"
        >
          {source.name}
        </span>
      ))}
    </div>
  );
}
