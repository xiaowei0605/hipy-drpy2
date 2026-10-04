import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildTavernHelperCompat_ACU } from '../../src/shared/host-compat/tavern-helper-compat';
import { _set_TavernHelper_API_ACU } from '../../src/shared/host-api';
import { getCurrentCharacterWorldbookBinding_ACU } from '../../src/data/gateways/character-gateway';
import { getLorebookEntriesStrict_ACU } from '../../src/service/worldbook/pipeline';

function makeNativeContext(loadWorldInfo = vi.fn()) {
  return {
    loadWorldInfo,
    saveWorldInfo: vi.fn(),
    executeSlashCommandsWithOptions: vi.fn(),
    chat: [],
    characters: [],
  };
}

afterEach(() => {
  _set_TavernHelper_API_ACU(undefined as any);
});

describe('世界书统一宿主链路', () => {
  it('raw TavernHelper 的绑定与严格读取使用同一来源，native 世界书后端不参与', async () => {
    const nativeLoadWorldInfo = vi.fn().mockResolvedValue(null);
    const rawTH = {
      getCharWorldbookNames: vi.fn().mockResolvedValue({ primary: '目标书', additional: [] }),
      getLorebookEntries: vi.fn().mockResolvedValue([{ uid: 1, content: '来自 raw TavernHelper' }]),
    };
    const { api } = buildTavernHelperCompat_ACU(rawTH, () => makeNativeContext(nativeLoadWorldInfo));
    _set_TavernHelper_API_ACU(api as any);

    await expect(getCurrentCharacterWorldbookBinding_ACU()).resolves.toMatchObject({
      orderedNames: ['目标书'],
      apiSource: 'getCharWorldbookNames',
    });
    await expect(getLorebookEntriesStrict_ACU(['目标书'], {
      source: 'agent_runtime', validationPolicy: 'trusted_direct', runId: 'raw-host-chain',
    })).resolves.toMatchObject({
      status: 'success',
      entriesByBook: { '目标书': [{ uid: 1, content: '来自 raw TavernHelper' }] },
    });
    expect(rawTH.getLorebookEntries).toHaveBeenCalledWith('目标书');
    expect(nativeLoadWorldInfo).not.toHaveBeenCalled();
  });

  it('raw TavernHelper 缺少条目读取时严格链路报告 API 不可用，不切换到 native', async () => {
    const nativeLoadWorldInfo = vi.fn().mockResolvedValue({ entries: { 1: { uid: 1 } } });
    const rawTH = {
      getCharWorldbookNames: vi.fn().mockResolvedValue({ primary: '目标书', additional: [] }),
    };
    const { api } = buildTavernHelperCompat_ACU(rawTH, () => makeNativeContext(nativeLoadWorldInfo));
    _set_TavernHelper_API_ACU(api as any);

    const result = await getLorebookEntriesStrict_ACU(['目标书'], {
      source: 'agent_runtime', validationPolicy: 'trusted_direct', runId: 'missing-raw-read',
    });

    expect(result.status).toBe('read_failed');
    expect(result.failedBooks).toEqual([{ bookName: '目标书', errorCategory: 'api_unavailable' }]);
    expect(nativeLoadWorldInfo).not.toHaveBeenCalled();
  });
});
