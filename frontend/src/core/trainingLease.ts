const leases = new Map<string, string>();

export function rememberTrainingLease(id: string, lease: string) {
  leases.set(id, lease);
}

export function forgetTrainingLease(id: string, lease: string) {
  if (leases.get(id) === lease) leases.delete(id);
}

export function trainingLeaseHeaders(path: string): Record<string, string> {
  const id = /^\/training\/sessions\/([^/?]+)/.exec(path)?.[1];
  const lease = id && leases.get(id);
  return lease ? { "X-Training-Lease": lease } : {};
}
