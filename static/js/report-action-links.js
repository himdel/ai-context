/** Match the shared local report link convention without requesting its target. */
export function isReportActionLink(ref) {
  try {
    const url = new URL(ref);
    return (
      ['http:', 'https:'].includes(url.protocol) &&
      ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) &&
      !url.username &&
      !url.password &&
      /^\/actions\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/?$/i.test(
        url.pathname,
      )
    );
  } catch {
    return false;
  }
}
