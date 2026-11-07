import { lazy, Suspense, type ComponentProps } from "react";

import { Loader } from "./Loader";

const InstagramBrowserPanel = lazy(() =>
  import("./InstagramBrowserPanel").then((m) => ({ default: m.InstagramBrowserPanel }))
);

export type LazyInstagramBrowserPanelProps = ComponentProps<typeof InstagramBrowserPanel>;

export function LazyInstagramBrowserPanel(props: LazyInstagramBrowserPanelProps) {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[12rem] items-center justify-center">
          <Loader label="Подключаю браузер…" />
        </div>
      }
    >
      <InstagramBrowserPanel {...props} />
    </Suspense>
  );
}
