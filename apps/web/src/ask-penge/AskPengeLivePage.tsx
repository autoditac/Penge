import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AskPengePage } from "./AskPengePage";
import { AskChatClientError, createAskChatClient } from "./liveClient";
import type { AskAuthStatus, AskChatClient, FetchLike } from "./liveClient";

type AskPengeLivePageProps = {
  readonly configuredBaseUrl?: string;
  readonly fetchFn?: FetchLike;
  readonly navigate?: (url: string) => void;
};

type ClientResolution =
  | { readonly client: AskChatClient; readonly error: null }
  | { readonly client: null; readonly error: string };

export function AskPengeLivePage({
  configuredBaseUrl = import.meta.env.VITE_PENGE_CHAT_BASE_URL,
  fetchFn = fetch,
  navigate = (url) => window.location.assign(url),
}: AskPengeLivePageProps): React.JSX.Element {
  const resolution = useMemo<ClientResolution | null>(() => {
    if (configuredBaseUrl === undefined || configuredBaseUrl.trim() === "") {
      return null;
    }
    try {
      return {
        client: createAskChatClient(configuredBaseUrl, fetchFn),
        error: null,
      };
    } catch (error) {
      return {
        client: null,
        error:
          error instanceof AskChatClientError
            ? error.message
            : "Ask Penge chat configuration is invalid.",
      };
    }
  }, [configuredBaseUrl, fetchFn]);

  if (resolution === null) {
    return <AskPengePage />;
  }
  if (resolution.client === null) {
    return <AskPengePage serviceState="error" serviceError={resolution.error} />;
  }

  return <ConfiguredAskPengePage client={resolution.client} navigate={navigate} />;
}

function ConfiguredAskPengePage({
  client,
  navigate,
}: {
  readonly client: AskChatClient;
  readonly navigate: (url: string) => void;
}): React.JSX.Element {
  const [status, setStatus] = useState<AskAuthStatus | null>(null);
  const [serviceState, setServiceState] = useState<"loading" | "ready" | "error">("loading");
  const [serviceError, setServiceError] = useState<string | null>(null);
  const statusRequestId = useRef(0);
  const unlinkPending = useRef(false);

  const refreshStatus = useCallback(async (): Promise<void> => {
    const requestId = ++statusRequestId.current;
    setServiceState("loading");
    setServiceError(null);
    try {
      const nextStatus = await client.getStatus();
      if (requestId !== statusRequestId.current) {
        return;
      }
      setStatus(nextStatus);
      setServiceState("ready");
    } catch {
      if (requestId !== statusRequestId.current) {
        return;
      }
      setStatus(null);
      setServiceError(
        "The trusted GitHub, feature, and model status could not be loaded. No request will be sent.",
      );
      setServiceState("error");
    }
  }, [client]);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const refreshStatusUnlessUnlinking = (): void => {
    if (!unlinkPending.current) {
      void refreshStatus();
    }
  };

  const unlinkGitHub = (): void => {
    if (unlinkPending.current) {
      return;
    }
    unlinkPending.current = true;
    statusRequestId.current += 1;
    void (async () => {
      setServiceState("loading");
      setServiceError(null);
      try {
        await client.unlinkGitHub();
        await refreshStatus();
      } catch {
        setServiceError(
          "The GitHub account could not be unlinked. Refresh status before asking again.",
        );
        setServiceState("error");
      } finally {
        unlinkPending.current = false;
      }
    })();
  };

  return (
    <AskPengePage
      transport={client.transport}
      authState={status?.github.state ?? "not-configured"}
      githubLogin={status?.github.login ?? null}
      modelAvailable={status?.model.available ?? false}
      featureEnabled={status?.featureEnabled ?? false}
      serviceState={serviceState}
      serviceError={serviceError}
      onLinkGitHub={() => navigate(client.githubStartUrl)}
      onRetryStatus={refreshStatusUnlessUnlinking}
      onAuthExpired={refreshStatusUnlessUnlinking}
      onModelUnavailable={refreshStatusUnlessUnlinking}
      {...(status?.github.state === "linked" || status?.github.state === "expired"
        ? { onUnlinkGitHub: unlinkGitHub }
        : {})}
    />
  );
}
