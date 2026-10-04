/**
 * @vitest-environment jsdom
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useDialogStore } from '../../../src/presentation-v2/stores/dialog-store';

describe('useDialogStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('按确认弹窗语义解析确认与取消', async () => {
    const dialog = useDialogStore();
    const confirmed = dialog.confirm({
      title: '删除',
      message: '确定删除？',
    });

    expect(dialog.active?.kind).toBe('confirm');
    dialog.cancelActive();

    await expect(confirmed).resolves.toBe(false);
  });

  it('队列中的 prompt 激活时保留自己的默认值', async () => {
    const dialog = useDialogStore();
    const first = dialog.confirm({
      title: '先确认',
      message: '先处理确认。',
    });
    const second = dialog.prompt({
      title: '再输入',
      message: '请输入名称。',
      label: '名称',
      defaultValue: '默认名称',
    });

    expect(dialog.active?.kind).toBe('confirm');
    expect(dialog.queue).toHaveLength(1);

    dialog.submitActive();
    await expect(first).resolves.toBe(true);

    expect(dialog.active?.kind).toBe('prompt');
    expect(dialog.inputValue).toBe('默认名称');

    dialog.submitActive();
    await expect(second).resolves.toBe('默认名称');
  });

  it('多选弹窗返回已勾选项目并要求至少选择一项', async () => {
    const dialog = useDialogStore();
    const selected = dialog.selectMany({
      title: '选择清理项目',
      message: '请选择本次要清理的项目。',
      options: [
        { value: 'template', label: '模板快照', defaultChecked: true },
        { value: 'plot', label: '剧情快照', defaultChecked: true },
        { value: 'locks', label: '表格锁', defaultChecked: false },
      ],
    });

    expect(dialog.active?.kind).toBe('multiselect');
    expect(dialog.checkedValues).toEqual({
      template: true,
      plot: true,
      locks: false,
    });

    dialog.setCheckedValue('template', false);
    dialog.setCheckedValue('plot', false);
    expect(dialog.confirmDisabled).toBe(true);

    dialog.submitActive();
    expect(dialog.active?.kind).toBe('multiselect');

    dialog.setCheckedValue('locks', true);
    expect(dialog.confirmDisabled).toBe(false);
    dialog.submitActive();

    await expect(selected).resolves.toEqual(['locks']);
  });

  it('confirm 倒计时归零前硬性拒绝提交，归零后才能确认', async () => {
    vi.useFakeTimers();
    try {
      const dialog = useDialogStore();
      const confirmed = dialog.confirm({
        title: '高风险操作',
        message: '请阅读完整提示后再确认。',
        confirmCountdownSeconds: 5,
      });

      expect(dialog.confirmCountdownRemaining).toBe(5);
      expect(dialog.confirmDisabled).toBe(true);

      // UI 禁用之外的 store 级 guard：倒计时未归零时提交无效。
      dialog.submitActive();
      expect(dialog.active?.kind).toBe('confirm');

      vi.advanceTimersByTime(3000);
      expect(dialog.confirmCountdownRemaining).toBe(2);
      dialog.submitActive();
      expect(dialog.active?.kind).toBe('confirm');

      vi.advanceTimersByTime(2000);
      expect(dialog.confirmCountdownRemaining).toBe(0);
      expect(dialog.confirmDisabled).toBe(false);
      dialog.submitActive();
      await expect(confirmed).resolves.toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it('倒计时期间取消随时生效，并清理定时器与剩余秒数', async () => {
    vi.useFakeTimers();
    try {
      const dialog = useDialogStore();
      const confirmed = dialog.confirm({
        title: '高风险操作',
        message: '倒计时期间应可随时取消。',
        confirmCountdownSeconds: 5,
      });

      vi.advanceTimersByTime(1000);
      expect(dialog.confirmCountdownRemaining).toBe(4);

      dialog.cancelActive();
      await expect(confirmed).resolves.toBe(false);
      expect(dialog.confirmCountdownRemaining).toBe(0);

      // 定时器已清理：时间继续推进不会把剩余秒数改成负数或复活弹窗。
      vi.advanceTimersByTime(10000);
      expect(dialog.confirmCountdownRemaining).toBe(0);
      expect(dialog.active).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('带倒计时的弹窗关闭后，队列中无倒计时的弹窗不继承倒计时', async () => {
    vi.useFakeTimers();
    try {
      const dialog = useDialogStore();
      const first = dialog.confirm({
        title: '第一个',
        message: '带 5 秒倒计时。',
        confirmCountdownSeconds: 5,
      });
      const second = dialog.confirm({
        title: '第二个',
        message: '普通确认框。',
      });

      dialog.cancelActive();
      await expect(first).resolves.toBe(false);

      expect(dialog.active?.title).toBe('第二个');
      expect(dialog.confirmCountdownRemaining).toBe(0);
      expect(dialog.confirmDisabled).toBe(false);
      dialog.submitActive();
      await expect(second).resolves.toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
