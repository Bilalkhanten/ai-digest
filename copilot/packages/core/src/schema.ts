import { z } from "zod";

export const SeveritySchema = z.enum(["info", "warning", "critical"]);

export const EvidenceSchema = z.object({
  id: z.string().min(1).max(200),
  source: z.enum(["kubernetes", "prometheus"]),
  kind: z.string().min(1).max(80),
  at: z.iso.datetime({ offset: true }),
  subject: z.string().min(1).max(200),
  severity: SeveritySchema,
  summary: z.string().min(1).max(500),
});

/** Kubernetes object names (RFC 1123 labels). Used before a name is placed in a query. */
export const K8sNameSchema = z
  .string()
  .min(1)
  .max(63)
  .regex(/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/, "not a valid Kubernetes name");

export function parseEvidence(input: unknown) {
  return EvidenceSchema.safeParse(input);
}
