import { useMemo } from "react";

import { AskPengePage } from "./AskPengePage";
import { createMockAskTransport } from "./mockTransport";

export function AskPengeE2EEntry(): React.JSX.Element {
  const transport = useMemo(() => createMockAskTransport(), []);

  return (
    <AskPengePage
      authState="linked"
      modelAvailable
      featureEnabled
      serviceState="ready"
      transport={transport}
    />
  );
}
