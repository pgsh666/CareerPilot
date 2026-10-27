// Preview builds and standalone files never provide backend authorization.
export const isPreviewMode =
  window.location.protocol === "file:" ||
  import.meta.env.VITE_PREVIEW_MODE === "true";
