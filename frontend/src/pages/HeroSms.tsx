import { Smartphone } from "lucide-react";

import { HeroSmsPanel } from "../components/HeroSmsPanel";
import { PageHeader } from "../components/PageHeader";
import { PageShell } from "../components/PageShell";

export function HeroSms() {
  return (
    <PageShell>
      <PageHeader
        title="Hero SMS"
        description="Покупка виртуальных номеров и приём SMS для регистрации аккаунтов."
        icon={Smartphone}
      />
      <HeroSmsPanel />
    </PageShell>
  );
}
