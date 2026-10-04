import { SillyTavern_API_ACU } from '../../shared/host-api';

const FALLBACK_CHARS_PER_TOKEN_ACU = 1.5;

/** Counts text with the host tokenizer and falls back to the established character estimate. */
export async function countTextTokens_ACU(text: string): Promise<number> {
  const content = String(text ?? '');
  if (!content) return 0;
  const counter = SillyTavern_API_ACU?.getTokenCountAsync;
  if (typeof counter === 'function') {
    try {
      const counted = await counter.call(SillyTavern_API_ACU, content);
      if (typeof counted === 'number' && Number.isFinite(counted) && counted >= 0) return Math.ceil(counted);
    } catch {
      // Token counting only informs budgeting; retain the existing estimate on host failures.
    }
  }
  return Math.ceil(content.length / FALLBACK_CHARS_PER_TOKEN_ACU);
}
