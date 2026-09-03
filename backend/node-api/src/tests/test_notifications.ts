/**
 * test_notifications.ts — Automated test suite for Notification System & Anti-Spam Cooldown
 */
import assert from 'node:assert/strict';
import {
  getNotificationSettings,
  updateNotificationSettings,
} from '../services/notificationConfigService';
import { notificationService } from '../services/notificationService';
import { sendTelegramMessage } from '../services/telegramService';
import { sendEmailAlert, renderAlertEmailHtml } from '../services/emailService';

async function runNotificationTests() {
  console.log('--- [Test 1/3] Notification Settings Persistence ---');
  const initial = getNotificationSettings();
  assert.ok(initial, 'Settings must be initialized');
  assert.equal(typeof initial.cooldownSeconds, 'number');

  const updated = updateNotificationSettings({
    cooldownSeconds: 99,
    telegram: {
      enabled: false,
      botToken: 'mock_token',
      chatId: 'mock_chat',
    },
  });
  assert.equal(updated.cooldownSeconds, 99);
  assert.equal(updated.telegram.botToken, 'mock_token');

  // Restore
  updateNotificationSettings({
    cooldownSeconds: initial.cooldownSeconds,
    telegram: initial.telegram,
    email: initial.email,
  });
  console.log('✓ Settings persistence test passed');

  console.log('--- [Test 2/3] Telegram & Email Formatting & Validation ---');
  // Telegram missing credentials should fail gracefully without throwing
  const tgResult = await sendTelegramMessage('', '', '<b>Test</b>');
  assert.equal(tgResult.success, false);
  assert.match(tgResult.error || '', /missing/i);

  // Email template rendering
  const html = renderAlertEmailHtml({
    title: 'Sự cố thử nghiệm',
    badgeText: 'TEST',
    details: [{ label: 'Vị trí', value: 'Bãi kiểm' }],
  });
  assert.ok(html.includes('SentriAI System Alert'));
  assert.ok(html.includes('Sự cố thử nghiệm'));
  assert.ok(html.includes('Bãi kiểm'));
  console.log('✓ Notification validation & HTML render passed');

  console.log('--- [Test 3/3] Anti-Spam Debounce Cooldown Logic ---');
  notificationService.clearCooldowns();
  // Temporarily enable telegram in config to test debounce
  updateNotificationSettings({
    cooldownSeconds: 60,
    telegram: { enabled: true, botToken: 'test_token', chatId: 'test_chat' },
  });

  const testEvent = {
    id: 'test-violation-001',
    cameraId: 'BAI-KIEM',
    zoneName: 'Zone Bốc Xếp',
    objectLabel: 'forklift',
    enteredAt: new Date(),
  };

  // First call should proceed through cooldown check
  let dispatchCount = 0;
  const originalTg = sendTelegramMessage;
  // Monkey-patch for testing
  (global as any).fetch = async () => ({
    json: async () => {
      dispatchCount++;
      return { ok: true, result: { message_id: 123 } };
    },
  });

  await notificationService.notifyAreaViolation(testEvent);
  const countAfterFirst = dispatchCount;

  // Second immediate call with identical object & zone should be debounced!
  await notificationService.notifyAreaViolation(testEvent);
  const countAfterSecond = dispatchCount;

  assert.equal(
    countAfterSecond,
    countAfterFirst,
    'Second immediate violation notification must be suppressed by cooldown',
  );

  // Cleanup
  notificationService.clearCooldowns();
  updateNotificationSettings(initial);
  console.log('✓ Debounce cooldown test passed');

  console.log('\n========================================');
  console.log('All Notification Tests Passed Successfully!');
  console.log('========================================');
}

runNotificationTests().catch((err) => {
  console.error('Test failed:', err);
  process.exit(1);
});
