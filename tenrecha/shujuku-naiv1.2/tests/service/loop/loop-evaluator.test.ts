/**
 * tests/service/loop/loop-evaluator.test.ts
 * 循环生成结果评估 单元测试
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('../../../src/shared/utils', () => ({
  logDebug_ACU: vi.fn(),
  logWarn_ACU: vi.fn(),
}));

vi.mock('../../../src/service/host/host-state-service', () => ({
  getCurrentCharacterFallback_ACU: vi.fn(() => ({ name: '勇者' })),
}));

import { validateLoopTags_ACU, evaluateLoopGenerationResult_ACU } from '../../../src/service/loop/loop-evaluator';

describe('validateLoopTags_ACU', () => {
  it('空标签返回 true', () => {
    expect(validateLoopTags_ACU('任意内容', '')).toBe(true);
  });
  it('null 标签返回 true', () => {
    expect(validateLoopTags_ACU('任意内容', null as any)).toBe(true);
  });
  it('所有标签都存在返回 true', () => {
    expect(validateLoopTags_ACU('<plot>剧情</plot><action>动作</action>', 'plot,action')).toBe(true);
  });
  it('部分标签缺失返回 false', () => {
    expect(validateLoopTags_ACU('<plot>剧情</plot>', 'plot,action')).toBe(false);
  });
  it('中文逗号分隔', () => {
    expect(validateLoopTags_ACU('<plot>剧情</plot><action>动作</action>', 'plot，action')).toBe(true);
  });
  it('标签前后空格被 trim', () => {
    expect(validateLoopTags_ACU('<plot>剧情</plot>', '  plot  ')).toBe(true);
  });
  it('空内容返回 false', () => {
    expect(validateLoopTags_ACU('', 'plot')).toBe(false);
  });
});

describe('evaluateLoopGenerationResult_ACU', () => {
  const defaultGuard = { inProgress: false, ignoreNextGenerationEndedCount: 0 };
  const loopSettings = { loopTags: 'plot' };

  it('空聊天记录返回 ignore', () => {
    expect(evaluateLoopGenerationResult_ACU([], loopSettings, defaultGuard).action).toBe('ignore');
  });
  it('null 聊天记录返回 ignore', () => {
    expect(evaluateLoopGenerationResult_ACU(null as any, loopSettings, defaultGuard).action).toBe('ignore');
  });
  it('规划守卫进行中返回 ignore', () => {
    const guard = { inProgress: true, ignoreNextGenerationEndedCount: 0 };
    const chat = [{ is_user: false, mes: '<plot>内容</plot>', name: '勇者' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, guard).action).toBe('ignore');
  });
  it('忽略计数 > 0 返回 ignore', () => {
    const guard = { inProgress: false, ignoreNextGenerationEndedCount: 1 };
    const chat = [{ is_user: false, mes: '<plot>内容</plot>', name: '勇者' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, guard).action).toBe('ignore');
  });
  it('最后一条是用户消息（规划层）返回 wait', () => {
    const chat = [{ is_user: true, _qrf_from_planning: true, mes: '' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, defaultGuard).action).toBe('wait');
  });
  it('最后一条是用户消息（非规划）返回 wait', () => {
    const chat = [{ is_user: true, mes: '' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, defaultGuard).action).toBe('wait');
  });
  it('标签验证通过返回 continue', () => {
    const chat = [{ is_user: false, mes: '<plot>内容</plot>', name: '勇者' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, defaultGuard).action).toBe('continue');
  });
  it('标签验证失败返回 retry_delete', () => {
    const chat = [{ is_user: false, mes: '没有标签', name: '勇者' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, defaultGuard).action).toBe('retry_delete');
  });
  it('不同角色返回 ignore', () => {
    const chat = [{ is_user: false, mes: '<plot>内容</plot>', name: '其他角色' }];
    expect(evaluateLoopGenerationResult_ACU(chat, loopSettings, defaultGuard).action).toBe('ignore');
  });
});
