import { useEffect, useRef } from "react";

export const ASSISTANT_MUTATE = "assistant-mutate";

export type AssistantCreated = {
  accounts?: number[];
  proxies?: number[];
};

export function emitAssistantMutate(detail?: AssistantCreated) {
  window.dispatchEvent(new CustomEvent(ASSISTANT_MUTATE, { detail: detail ?? {} }));
}

export function useAssistantMutate(
  reload: (detail?: AssistantCreated) => void | Promise<void>
) {
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  useEffect(() => {
    const onMutate = (event: Event) => {
      const detail = (event as CustomEvent<AssistantCreated>).detail;
      void reloadRef.current(detail);
    };
    window.addEventListener(ASSISTANT_MUTATE, onMutate);
    return () => window.removeEventListener(ASSISTANT_MUTATE, onMutate);
  }, []);
}
