/**
 * tests/service/table/storage-mode.test.ts
 * 存储模式工具函数单元测试
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// mock state-manager
let mockSettings: any = {};
vi.mock('../../../src/service/runtime/state-manager', () => ({
  get settings_ACU() { return mockSettings; },
}));

import {
  getCurrentStorageMode,
  isSqliteMode,
  isNativeMode,
} from '../../../src/service/table/storage-mode';

describe('storage-mode', () => {
  beforeEach(() => {
    mockSettings = {};
  });

  // ═══════════════════════════════════════════════════════════════
  // getCurrentStorageMode
  // ═══════════════════════════════════════════════════════════════
  describe('getCurrentStorageMode', () => {
    it('storageMode 为 "sqlite" 时返回 "sqlite"', () => {
      mockSettings = { storageMode: 'sqlite' };
      expect(getCurrentStorageMode()).toBe('sqlite');
    });

    it('storageMode 为 "native" 时返回 "native"', () => {
      mockSettings = { storageMode: 'native' };
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('storageMode 未设置时默认返回 "native"', () => {
      mockSettings = {};
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('storageMode 为 undefined 时返回 "native"', () => {
      mockSettings = { storageMode: undefined };
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('storageMode 为 null 时返回 "native"', () => {
      mockSettings = { storageMode: null };
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('storageMode 为非法字符串时返回 "native"', () => {
      mockSettings = { storageMode: 'invalid_mode' };
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('storageMode 为空字符串时返回 "native"', () => {
      mockSettings = { storageMode: '' };
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('settings_ACU 为 null 时返回 "native"', () => {
      mockSettings = null;
      expect(getCurrentStorageMode()).toBe('native');
    });

    it('settings_ACU 为 undefined 时返回 "native"', () => {
      mockSettings = undefined;
      expect(getCurrentStorageMode()).toBe('native');
    });
  });

  // ═══════════════════════════════════════════════════════════════
  // isSqliteMode
  // ═══════════════════════════════════════════════════════════════
  describe('isSqliteMode', () => {
    it('sqlite 模式下返回 true', () => {
      mockSettings = { storageMode: 'sqlite' };
      expect(isSqliteMode()).toBe(true);
    });

    it('native 模式下返回 false', () => {
      mockSettings = { storageMode: 'native' };
      expect(isSqliteMode()).toBe(false);
    });

    it('未设置时返回 false（默认 native）', () => {
      mockSettings = {};
      expect(isSqliteMode()).toBe(false);
    });
  });

  // ═══════════════════════════════════════════════════════════════
  // isNativeMode
  // ═══════════════════════════════════════════════════════════════
  describe('isNativeMode', () => {
    it('native 模式下返回 true', () => {
      mockSettings = { storageMode: 'native' };
      expect(isNativeMode()).toBe(true);
    });

    it('sqlite 模式下返回 false', () => {
      mockSettings = { storageMode: 'sqlite' };
      expect(isNativeMode()).toBe(false);
    });

    it('未设置时返回 true（默认 native）', () => {
      mockSettings = {};
      expect(isNativeMode()).toBe(true);
    });

    it('非法模式时返回 true（fallback 到 native）', () => {
      mockSettings = { storageMode: 'invalid' };
      expect(isNativeMode()).toBe(true);
    });
  });
});
