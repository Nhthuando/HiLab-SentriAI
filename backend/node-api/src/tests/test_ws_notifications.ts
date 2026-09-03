import { SentriWebSocketServer } from '../ws/server';
import http from 'http';
import WebSocket from 'ws';
import { notificationService } from '../services/notificationService';

async function runTest() {
  console.log('Testing WS Inbound Publisher Notification Hook...');
  
  let areaNotified = false;
  let gateNotified = false;

  // Spy on notificationService
  const origArea = notificationService.notifyAreaViolation.bind(notificationService);
  const origGate = notificationService.notifyGateStranger.bind(notificationService);

  notificationService.notifyAreaViolation = async (violation: any) => {
    console.log('✓ Hook triggered notifyAreaViolation with:', violation.objectLabel, 'in', violation.zoneName);
    areaNotified = true;
  };

  notificationService.notifyGateStranger = async (event: any) => {
    console.log('✓ Hook triggered notifyGateStranger with plate:', event.licensePlate);
    gateNotified = true;
  };

  const server = http.createServer();
  new SentriWebSocketServer(server);

  await new Promise<void>((resolve) => server.listen(3991, resolve));

  const wsArea = new WebSocket('ws://localhost:3991/ws/publish/events/area');
  await new Promise<void>((resolve) => wsArea.on('open', resolve));

  wsArea.send(JSON.stringify({
    type: 'zone_violation',
    action: 'STARTED',
    id: 'test-v1',
    cameraId: 'BAI-KIEM',
    zoneName: 'Zone mới 1',
    objectLabel: 'Người',
    status: 'OPEN',
    enteredAt: new Date().toISOString()
  }));

  const wsGate = new WebSocket('ws://localhost:3991/ws/publish/events/gate');
  await new Promise<void>((resolve) => wsGate.on('open', resolve));

  wsGate.send(JSON.stringify({
    type: 'gate_event',
    id: 'test-g1',
    cameraId: 'GATE-01',
    lane: 'IN_1',
    licensePlate: '51F-999.99',
    status: 'la',
    confidence: 0.98
  }));

  // Wait 500ms
  await new Promise((r) => setTimeout(r, 500));

  wsArea.close();
  wsGate.close();
  await new Promise<void>((resolve) => server.close(() => resolve()));

  notificationService.notifyAreaViolation = origArea;
  notificationService.notifyGateStranger = origGate;

  if (areaNotified && gateNotified) {
    console.log('🎉 ALL INBOUND WS NOTIFICATION HOOKS VERIFIED SUCCESSFULLY!');
    process.exit(0);
  } else {
    console.error('❌ Failed! Area notified:', areaNotified, 'Gate notified:', gateNotified);
    process.exit(1);
  }
}

runTest().catch((err) => {
  console.error(err);
  process.exit(1);
});
