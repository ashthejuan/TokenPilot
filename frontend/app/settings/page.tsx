import { PageHeader } from "@/components/PageHeader";
import { PricingSection } from "@/components/settings/PricingSection";
import { PrivacySection } from "@/components/settings/PrivacySection";
import { RetentionSection } from "@/components/settings/RetentionSection";
import { ThresholdsSection } from "@/components/settings/ThresholdsSection";
import { PAGE_SHELL_NARROW } from "@/lib/layout";

export default function SettingsPage() {
  return (
    <div className={PAGE_SHELL_NARROW}>
      <PageHeader
        title="Settings"
        description="Privacy status, detector thresholds, pricing catalogue, and data retention."
      />
      <PrivacySection />
      <ThresholdsSection />
      <PricingSection />
      <RetentionSection />
    </div>
  );
}
