/* Bounded same-origin JSON requests; never leave a screen waiting indefinitely. */
window.hkRequest = async function(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, {...options, cache:'no-store', signal:controller.signal,
      headers:{Accept:'application/json', ...options.headers}});
    let data;
    try { data = await response.json(); }
    catch (error) {
      if (controller.signal.aborted) throw error;
      throw new Error('The server returned an invalid response. Please retry.');
    }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
    return data;
  } catch(error) {
    if (controller.signal.aborted) throw new Error('Connection interrupted. Please retry; no live prediction is available.');
    if (error instanceof TypeError) throw new Error('Cannot reach the server. Check your connection and retry.');
    throw error;
  } finally { clearTimeout(timer); }
};
