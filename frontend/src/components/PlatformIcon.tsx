import clsx from "clsx";
import { FaInstagram, FaYoutube, FaTiktok } from "react-icons/fa";

export type PanelPlatform = "instagram" | "youtube" | "tiktok";

const META: Record<
  PanelPlatform,
  { Icon: typeof FaInstagram; color: string; label: string }
> = {
  instagram: { Icon: FaInstagram, color: "#E4405F", label: "Instagram" },
  youtube: { Icon: FaYoutube, color: "#FF0000", label: "YouTube" },
  tiktok: { Icon: FaTiktok, color: "#69C9D0", label: "TikTok" },
};

export function normalizePlatform(platform: string | null | undefined): PanelPlatform {
  const key = (platform || "instagram").trim().toLowerCase();
  if (key === "youtube" || key === "tiktok") return key;
  return "instagram";
}

export function platformLabel(platform: string | null | undefined): string {
  return META[normalizePlatform(platform)].label;
}

export function PlatformIcon({
  platform,
  size = 16,
  className,
  colored = true,
}: {
  platform: string | null | undefined;
  size?: number;
  className?: string;
  colored?: boolean;
}) {
  const key = normalizePlatform(platform);
  const { Icon, color, label } = META[key];
  return (
    <Icon
      size={size}
      className={clsx("shrink-0", className)}
      style={colored ? { color } : undefined}
      aria-label={label}
      data-testid={`platform-icon-${key}`}
    />
  );
}
