import { PricingSection } from "@/components/settings/PricingSection";
import { PrivacySection } from "@/components/settings/PrivacySection";
import { RetentionSection } from "@/components/settings/RetentionSection";
import { ThresholdsSection } from "@/components/settings/ThresholdsSection";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Privacy status, detector thresholds, pricing catalogue, and data retention.
        </p>
      </div>
      <PrivacySection />
      <ThresholdsSection />
      <PricingSection />
      <RetentionSection />
    </div>
  );
}
