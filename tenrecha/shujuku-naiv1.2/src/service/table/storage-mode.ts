/**
 * shared/storage-mode.ts — 存储模式工具函数
 *
 * 提供当前存储模式的读取和判断。
 * 从 settings_ACU 中读取 storageMode 字段。
 */

import type { StorageMode } from '../../shared/table-storage-provider';
import { settings_ACU } from '../runtime/state-manager';

/**
 * 获取当前存储模式
 * 从 settings_ACU.storageMode 读取，默认 'native'
 */
export function getCurrentStorageMode(): StorageMode {
  const mode = settings_ACU?.storageMode;
  if (mode === 'sqlite') return 'sqlite';
  return 'native';
}

/**
 * 判断当前是否为 SQLite 模式
 */
export function isSqliteMode(): boolean {
  return getCurrentStorageMode() === 'sqlite';
}

/**
 * 判断当前是否为原生模式
 */
export function isNativeMode(): boolean {
  return getCurrentStorageMode() === 'native';
}
