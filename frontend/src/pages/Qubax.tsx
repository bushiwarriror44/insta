import { Film } from "lucide-react";

import { QubaxPanel } from "../components/QubaxPanel";
import { PageHeader } from "../components/PageHeader";
import { PageShell } from "../components/PageShell";

export function Qubax() {
  return (
    <PageShell>
      <PageHeader
        title="Qubax"
        description="Генерация видео через Qubax: модели Kling, Seedance и другие — прямо из панели."
        icon={Film}
      />
      <QubaxPanel />
    </PageShell>
  );
}
