/**
 * tests/service/loop/loop-controller.test.ts
 * 循环控制状态机 单元测试
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { mockLoopState, mockSettings } = vi.hoisted(() => {
  const mockLoopState: any = {
    isLooping: false,
    isRetrying: false,
    awaitingReply: false,
    startTime: 0,
    totalDuration: 0,
    retryCount: 0,
    timerId: null,
    tickInterval: null,
  };
  const mockSettings: any = {
    plotSettings: {
      loopSettings: {
        quickReplyContent: ['提示词1', '提示词2'],
        loopTotalDuration: 5,
        loopDelay: 5,
        retryDelay: 3,
        maxRetries: 3,
        currentPromptIndex: 0,
        loopTags: 'plot',
      },
      plotPromptGroups: [{ name: '默认', prompts: [] }],
    },
  };
  return { mockLoopState, mockSettings };
});

vi.mock('../../../src/service/runtime/state-manager', () => ({
  loopState_ACU: mockLoopState,
  planningGuard_ACU: { inProgress: false, ignoreNextGenerationEndedCount: 0 },
  settings_ACU: mockSettings,
}));

vi.mock('../../../src/shared/utils', () => ({
  logDebug_ACU: vi.fn(),
  logError_ACU: vi.fn(),
  logWarn_ACU: vi.fn(),
}));

vi.mock('../../../src/service/chat/chat-service', () => ({
  getChatArray_ACU: vi.fn(() => [
    { is_user: false, mes: '<plot>内容</plot>', name: '勇者' },
  ]),
  deleteLastMessage_ACU: vi.fn(),
}));

vi.mock('../../../src/service/plot/plot-logic', () => ({
  ensureLoopPromptsArray_ACU: vi.fn(),
}));

vi.mock('../../../src/service/loop/loop-evaluator', () => ({
  evaluateLoopGenerationResult_ACU: vi.fn(() => ({ action: 'continue', reason: 'Tags ok' })),
}));

vi.mock('../../../src/shared/defaults-json.js', () => ({
  DEFAULT_PLOT_SETTINGS_ACU: {
    loopSettings: { maxRetries: 3, retryDelay: 3, loopDelay: 5 },
  },
}));

import {
  validateLoopStartParams_ACU,
  initLoopState_ACU,
  stopLoopState_ACU,
  getNextLoopPrompt_ACU,
  handleRetryLogic_ACU,
  evaluateLoopEnd_ACU,
} from '../../../src/service/loop/loop-controller';

beforeEach(() => {
  mockLoopState.isLooping = false;
  mockLoopState.isRetrying = false;
  mockLoopState.awaitingReply = false;
  mockLoopState.startTime = 0;
  mockLoopState.totalDuration = 0;
  mockLoopState.retryCount = 0;
  mockLoopState.timerId = null;
  mockLoopState.tickInterval = null;
  mockSettings.plotSettings.loopSettings.quickReplyContent = ['提示词1', '提示词2'];
  mockSettings.plotSettings.loopSettings.loopTotalDuration = 5;
  mockSettings.plotSettings.loopSettings.currentPromptIndex = 0;
  mockSettings.plotSettings.loopSettings.maxRetries = 3;
});

describe('validateLoopStartParams_ACU', () => {
  it('参数有效返回 null', () => {
    expect(validateLoopStartParams_ACU()).toBeNull();
  });
  it('无提示词返回错误信息', () => {
    mockSettings.plotSettings.loopSettings.quickReplyContent = [];
    expect(validateLoopStartParams_ACU()).toContain('提示词');
  });
  it('提示词为 null 返回错误信息', () => {
    mockSettings.plotSettings.loopSettings.quickReplyContent = null;
    expect(validateLoopStartParams_ACU()).toContain('提示词');
  });
  it('倒计时为 0 返回错误信息', () => {
    mockSettings.plotSettings.loopSettings.loopTotalDuration = 0;
    expect(validateLoopStartParams_ACU()).toContain('倒计时');
  });
  it('倒计时为负数返回错误信息', () => {
    mockSettings.plotSettings.loopSettings.loopTotalDuration = -1;
    expect(validateLoopStartParams_ACU()).toContain('倒计时');
  });
});

describe('initLoopState_ACU', () => {
  it('初始化循环状态', () => {
    const result = initLoopState_ACU();
    expect(mockLoopState.isLooping).toBe(true);
    expect(mockLoopState.isRetrying).toBe(false);
    expect(result.loopDuration).toBe(5 * 60 * 1000);
  });
  it('重置重试计数', () => {
    mockLoopState.retryCount = 5;
    initLoopState_ACU();
    expect(mockLoopState.retryCount).toBe(0);
  });
  it('记录开始时间', () => {
    const before = Date.now();
    initLoopState_ACU();
    expect(mockLoopState.startTime).toBeGreaterThanOrEqual(before);
  });
});

describe('stopLoopState_ACU', () => {
  it('停止循环状态', () => {
    mockLoopState.isLooping = true;
    mockLoopState.isRetrying = true;
    mockLoopState.awaitingReply = true;
    stopLoopState_ACU();
    expect(mockLoopState.isLooping).toBe(false);
    expect(mockLoopState.isRetrying).toBe(false);
    expect(mockLoopState.awaitingReply).toBe(false);
  });
  it('清除定时器', () => {
    mockLoopState.timerId = setTimeout(() => {}, 10000);
    mockLoopState.tickInterval = setInterval(() => {}, 10000);
    stopLoopState_ACU();
    expect(mockLoopState.timerId).toBeNull();
    expect(mockLoopState.tickInterval).toBeNull();
  });
});

describe('getNextLoopPrompt_ACU', () => {
  it('循环未启动返回 null', () => {
    mockLoopState.isLooping = false;
    expect(getNextLoopPrompt_ACU()).toBeNull();
  });
  it('返回当前索引的提示词', () => {
    mockLoopState.isLooping = true;
    expect(getNextLoopPrompt_ACU()).toBe('提示词1');
  });
  it('索引自动递增并循环', () => {
    mockLoopState.isLooping = true;
    getNextLoopPrompt_ACU(); // 返回提示词1，索引变为1
    expect(getNextLoopPrompt_ACU()).toBe('提示词2'); // 返回提示词2，索引变为0
    expect(getNextLoopPrompt_ACU()).toBe('提示词1'); // 循环回来
  });
  it('设置 awaitingReply 为 true', () => {
    mockLoopState.isLooping = true;
    getNextLoopPrompt_ACU();
    expect(mockLoopState.awaitingReply).toBe(true);
  });
  it('提示词为空返回 null', () => {
    mockLoopState.isLooping = true;
    mockSettings.plotSettings.loopSettings.quickReplyContent = [];
    expect(getNextLoopPrompt_ACU()).toBeNull();
  });
  it('提示词内容为空字符串返回 null', () => {
    mockLoopState.isLooping = true;
    mockSettings.plotSettings.loopSettings.quickReplyContent = [''];
    expect(getNextLoopPrompt_ACU()).toBeNull();
  });
});

describe('handleRetryLogic_ACU', () => {
  it('重试计数递增', async () => {
    mockLoopState.retryCount = 0;
    await handleRetryLogic_ACU(false);
    expect(mockLoopState.retryCount).toBe(1);
  });
  it('设置 isRetrying 为 true', async () => {
    await handleRetryLogic_ACU(false);
    expect(mockLoopState.isRetrying).toBe(true);
  });
  it('未超过最大重试次数返回 true', async () => {
    mockLoopState.retryCount = 0;
    expect(await handleRetryLogic_ACU(false)).toBe(true);
  });
  it('超过最大重试次数返回 false', async () => {
    mockLoopState.retryCount = 3; // maxRetries = 3，retryCount++ 后变为 4 > 3
    expect(await handleRetryLogic_ACU(false)).toBe(false);
  });
  it('shouldDeleteAiReply=true 时删除最后一条消息', async () => {
    const { deleteLastMessage_ACU } = await import('../../../src/service/chat/chat-service');
    mockLoopState.retryCount = 0;
    await handleRetryLogic_ACU(true);
    expect(deleteLastMessage_ACU).toHaveBeenCalled();
  });
});

// ═══ evaluateLoopEnd_ACU ═══
describe('evaluateLoopEnd_ACU', () => {
  it('未在循环中时返回 ignore', async () => {
    mockLoopState.isLooping = false;
    const result = await evaluateLoopEnd_ACU();
    expect(result.action).toBe('ignore');
  });
  it('未等待回复时返回 ignore', async () => {
    mockLoopState.isLooping = true;
    mockLoopState.awaitingReply = false;
    const result = await evaluateLoopEnd_ACU();
    expect(result.action).toBe('ignore');
  });
  it('正常循环中且等待回复时返回 continue', async () => {
    mockLoopState.isLooping = true;
    mockLoopState.awaitingReply = true;
    const { evaluateLoopGenerationResult_ACU } = await import('../../../src/service/loop/loop-evaluator');
    vi.mocked(evaluateLoopGenerationResult_ACU).mockReturnValue({ action: 'continue', reason: 'Tags ok' });
    const result = await evaluateLoopEnd_ACU();
    expect(result.action).toBe('continue');
    expect(result.loopDelay).toBeGreaterThan(0);
  });
  it('标签检测未通过时返回 retry_delete', async () => {
    mockLoopState.isLooping = true;
    mockLoopState.awaitingReply = true;
    const { evaluateLoopGenerationResult_ACU } = await import('../../../src/service/loop/loop-evaluator');
    vi.mocked(evaluateLoopGenerationResult_ACU).mockReturnValue({ action: 'retry_delete', reason: 'Tags missing' });
    const result = await evaluateLoopEnd_ACU();
    expect(result.action).toBe('retry_delete');
    expect(result.retryDelay).toBeGreaterThan(0);
  });
});
