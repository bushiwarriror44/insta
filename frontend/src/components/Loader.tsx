import { Loader2 } from "lucide-react";

export function Loader({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 text-slate-400 py-12">
      <Loader2 size={20} className="animate-spin" />
      <span className="text-sm">{label}</span>
    </div>
  );
}
